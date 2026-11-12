#!/usr/bin/env python3
"""Offline RFQ controls. No network, authentication, email or ERP actions."""
import argparse
import copy
import hashlib
import json
import sqlite3
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, getcontext
from pathlib import Path
from zoneinfo import ZoneInfo

getcontext().prec = 60


class InputError(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise InputError(message)


def number(value, field, positive=False):
    require(isinstance(value, (str, int)) and not isinstance(value, bool),
            f'{field}: use a decimal string or integer, not float/bool')
    try:
        n = Decimal(value)
    except (InvalidOperation, ValueError):
        raise InputError(f'{field}: invalid decimal')
    require(n.is_finite() and (n > 0 if positive else n >= 0),
            f'{field}: must be finite and {"> 0" if positive else ">= 0"}')
    require(n <= Decimal('1000000000000') and n.as_tuple().exponent >= -8,
            f'{field}: exceeds supported numeric range/precision')
    return n


def day(value):
    try:
        require(isinstance(value, str), 'date must be YYYY-MM-DD')
        parsed = date.fromisoformat(value)
        require(parsed.isoformat() == value, 'date must be YYYY-MM-DD')
        return parsed
    except (ValueError, TypeError):
        raise InputError(f'invalid ISO date: {value}')


def today():
    return datetime.now(ZoneInfo('Asia/Taipei')).date().isoformat()


def digest(obj):
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def read(path):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            require(key not in out, f'duplicate JSON key: {key}')
            out[key] = value
        return out
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique,
                      parse_constant=lambda s: (_ for _ in ()).throw(InputError(f'invalid JSON number: {s}')))


def write(path, obj):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def text_field(obj, key):
    require(isinstance(obj.get(key), str) and bool(obj[key].strip()), f'{key}: required nonempty string')
    return obj[key]


def known_fields(obj, allowed, label):
    require(isinstance(obj, dict), f'{label} must be object')
    extra = set(obj) - set(allowed)
    require(not extra, f'{label}: unmodeled fields require review: {sorted(extra)}')


def unique_lines(lines):
    require(isinstance(lines, list) and len(lines) > 0, 'lines: nonempty array required')
    seen = set()
    for line in lines:
        require(isinstance(line, dict), 'line must be object')
        key = text_field(line, 'line_id')
        require(key not in seen, f'duplicate line_id: {key}')
        seen.add(key)


def validate_case(case):
    require(isinstance(case, dict), 'case must be object')
    for k in ('tenant_id', 'customer_id', 'message_id', 'source_sha256'):
        text_field(case, k)
    sha = case['source_sha256']
    require(len(sha) == 64 and all(c in '0123456789abcdef' for c in sha), 'source_sha256: invalid SHA-256')
    unique_lines(case.get('lines'))
    blockers = []
    for line in case['lines']:
        lid = line['line_id']
        for field in ('customer_part', 'revision', 'unit'):
            if not isinstance(line.get(field), str) or not line[field].strip():
                blockers.append(f'{lid}: missing {field}')
        if line.get('quantity') is None:
            blockers.append(f'{lid}: missing quantity')
        else:
            number(line['quantity'], f'{lid}.quantity', positive=True)
        evidence = line.get('evidence', {})
        for field in ('customer_part', 'revision', 'unit', 'quantity'):
            e = evidence.get(field) if isinstance(evidence, dict) else None
            if not isinstance(e, dict) or not e.get('source') or not e.get('locator'):
                blockers.append(f'{lid}: missing evidence for {field}')
    require(isinstance(case.get('issues', []), list), 'issues must be array')
    for issue in case.get('issues', []):
        require(isinstance(issue, dict) and isinstance(issue.get('blocking'), bool)
                and isinstance(issue.get('message'), str), 'invalid issue')
        if issue['blocking']:
            blockers.append(issue['message'])
    return {'ok': not blockers, 'blockers': blockers}


def intake(case, db_path):
    validate_case(case)  # incomplete business facts can still be registered
    key = digest({k: case[k] for k in ('tenant_id', 'customer_id', 'message_id', 'source_sha256')})
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path, timeout=10) as db:
        db.execute('CREATE TABLE IF NOT EXISTS cases (event_key TEXT PRIMARY KEY, case_id TEXT NOT NULL, payload TEXT NOT NULL)')
        case_id = 'RFQ-' + key[:24].upper()
        inserted = db.execute('INSERT OR IGNORE INTO cases VALUES (?, ?, ?)',
                              (key, case_id, json.dumps(case, ensure_ascii=False))).rowcount == 1
        saved = db.execute('SELECT case_id, payload FROM cases WHERE event_key=?', (key,)).fetchone()
    same_payload = digest(json.loads(saved[1])) == digest(case)
    return {'case_id': saved[0], 'event_key': key, 'created': inserted,
            'payload_conflict': not same_payload,
            'note': 'Existing event is immutable; create reviewed amendment for changed extraction.' if not same_payload else ''}


def match(case, catalog):
    check = validate_case(case)
    require(isinstance(catalog, list), 'catalog must be array')
    result = []
    for line in case['lines']:
        candidates = []
        for product in catalog:
            text_field(product, 'internal_part')
            aliases = product.get('customer_parts', {})
            require(isinstance(aliases, dict), 'customer_parts must be object')
            customer_alias = aliases.get(case['customer_id'], [])
            require(isinstance(customer_alias, list), 'customer alias list required')
            if line.get('customer_part') in customer_alias or (
                    line.get('internal_part') and line['internal_part'] == product['internal_part']):
                candidates.append(product)
        valid = [p for p in candidates if p.get('revision') == line.get('revision')
                 and p.get('unit') == line.get('unit') and line.get('revision') and line.get('unit')]
        # Multiple aliases, even if only one revision matches, require review.
        exact = (len(candidates) == 1 and len(valid) == 1
                 and (not line.get('internal_part') or line['internal_part'] == valid[0]['internal_part']))
        result.append({'line_id': line['line_id'], 'status': 'EXACT' if exact else 'REVIEW',
                       'internal_part': valid[0]['internal_part'] if exact else None,
                       'candidates': [p['internal_part'] for p in candidates]})
    return {'ok': check['ok'] and all(r['status'] == 'EXACT' for r in result),
            'blockers': check['blockers'], 'matches': result,
            'note': 'Exact identifiers only; engineering must confirm technical equivalence.'}


TERMS = ('currency', 'tax_mode', 'tax_rate', 'payment_terms', 'delivery_terms',
         'ship_to_id', 'delivery_date')
LINE_FIELDS = ('customer_part', 'internal_part', 'revision', 'description', 'unit', 'quantity', 'unit_price', 'amount')
FEE_FIELDS = ('fee_id', 'description', 'amount')


def quote(request):
    require(isinstance(request, dict), 'request must be object')
    known_fields(request, ('company_id', 'customer_id', 'quote_id', 'revision', 'recipient_id',
                          'issued_on', 'valid_until', 'as_of', 'delivery_confirmed', 'credit_cleared',
                          'unresolved_issues', 'lines', 'fees', 'policy') + TERMS, 'quote request')
    policy = request.get('policy')
    require(isinstance(policy, dict), 'policy required')
    known_fields(policy, ('approved_policy_id', 'target_margin', 'minimum_margin', 'unit_price_places',
                          'amount_places', 'required_roles', 'note'), 'policy')
    roles = policy.get('required_roles')
    require(isinstance(roles, list) and roles and all(isinstance(r, str) and r.strip() for r in roles),
            'policy.required_roles required')
    for k in ('company_id', 'customer_id', 'quote_id', 'recipient_id'):
        text_field(request, k)
    require(type(request.get('revision')) is int and request['revision'] > 0, 'revision: positive integer required')
    as_of = day(request.get('as_of', today()))
    expiry = day(request.get('valid_until'))
    require(request.get('currency') in ('TWD', 'USD', 'EUR', 'JPY'), 'unsupported currency')
    require(request.get('tax_mode') == 'exclusive', 'only exclusive single-rate taxation supported')
    rate = number(request.get('tax_rate'), 'tax_rate')
    require(rate <= 1, 'tax_rate must be <= 1')
    require(type(policy.get('unit_price_places')) is int and 0 <= policy['unit_price_places'] <= 6,
            'unit_price_places must be 0..6')
    require(type(policy.get('amount_places')) is int and 0 <= policy['amount_places'] <= 6,
            'amount_places must be 0..6')
    margin = number(policy.get('target_margin'), 'target_margin')
    minimum = number(policy.get('minimum_margin'), 'minimum_margin')
    require(minimum <= margin < 1, 'require 0 <= minimum_margin <= target_margin < 1')
    unique_lines(request.get('lines'))
    blockers = []
    if expiry < as_of:
        blockers.append('quote expired')
    if not policy.get('approved_policy_id'):
        blockers.append('company policy is not approved')
    if request.get('unresolved_issues') != []:
        blockers.append('unresolved_issues must explicitly be an empty list')
    if day(request.get('issued_on')) > as_of or day(request['issued_on']) > expiry:
        blockers.append('invalid issued_on/valid_until interval')
    for field in ('payment_terms', 'delivery_terms', 'ship_to_id'):
        text_field(request, field)
    delivery = request.get('delivery_date')
    if delivery is None:
        blockers.append('delivery date unconfirmed')
    elif day(delivery) < as_of:
        blockers.append('delivery date is in the past')
    if request.get('delivery_confirmed') is not True:
        blockers.append('delivery not confirmed by supply owner')
    if request.get('credit_cleared') is not True:
        blockers.append('credit not cleared')
    unit_step = Decimal(1).scaleb(-policy['unit_price_places'])
    amount_step = Decimal(1).scaleb(-policy['amount_places'])
    rows, internal = [], []
    subtotal = Decimal(0)
    for line in request['lines']:
        known_fields(line, ('line_id', 'customer_part', 'internal_part', 'revision', 'description', 'unit',
                            'quantity', 'unit_cost', 'cost_currency', 'cost_unit', 'cost_source',
                            'cost_valid_from', 'cost_valid_until', 'technical_confirmed', 'unit_price'), 'quote line')
        lid = line['line_id']
        for field in ('customer_part', 'internal_part', 'revision', 'description', 'unit', 'cost_source'):
            text_field(line, field)
        qty = number(line.get('quantity'), f'{lid}.quantity', positive=True)
        cost = number(line.get('unit_cost'), f'{lid}.unit_cost', positive=True)
        require(line.get('cost_currency') == request['currency'], f'{lid}: currency conversion requires reviewed adapter')
        require(line.get('cost_unit') == line['unit'], f'{lid}: cost unit mismatch')
        valid_from, valid_until = day(line.get('cost_valid_from')), day(line.get('cost_valid_until'))
        require(valid_from <= valid_until, f'{lid}: invalid cost validity interval')
        if not valid_from <= as_of <= valid_until:
            blockers.append(f'{lid}: cost is not current')
        if expiry > valid_until:
            blockers.append(f'{lid}: quote validity exceeds cost validity')
        if line.get('technical_confirmed') is not True:
            blockers.append(f'{lid}: technical equivalence not confirmed')
        price = number(line['unit_price'], f'{lid}.unit_price', positive=True) if 'unit_price' in line else cost / (1 - margin)
        price = price.quantize(unit_step, rounding=ROUND_HALF_UP)
        require(price > 0, f'{lid}: rounded price must be > 0')
        actual_margin = (price - cost) / price
        if actual_margin < minimum:
            blockers.append(f'{lid}: margin below policy minimum; revise or obtain policy exception')
        amount = (qty * price).quantize(amount_step, rounding=ROUND_HALF_UP)
        subtotal += amount
        rows.append({k: line[k] for k in ('line_id', 'customer_part', 'internal_part', 'revision', 'description', 'unit')} |
                    {'quantity': str(qty), 'unit_price': str(price), 'amount': str(amount)})
        internal.append({'line_id': lid, 'unit_cost': str(cost), 'actual_margin': str(actual_margin),
                         'cost_source': line['cost_source'], 'cost_valid_from': str(valid_from), 'cost_valid_until': str(valid_until)})
    fees, seen_fees = [], set()
    require(isinstance(request.get('fees'), list), 'fees must be explicit array')
    for fee in request['fees']:
        known_fields(fee, ('fee_id', 'description', 'amount', 'currency'), 'fee')
        key = text_field(fee, 'fee_id')
        require(key not in seen_fees, f'duplicate fee_id: {key}')
        seen_fees.add(key)
        text_field(fee, 'description')
        require(fee.get('currency') == request['currency'], 'fee currency mismatch')
        amount = number(fee.get('amount'), 'fee.amount').quantize(amount_step, rounding=ROUND_HALF_UP)
        fees.append({'fee_id': key, 'description': fee['description'], 'amount': str(amount)})
        subtotal += amount
    tax = (subtotal * rate).quantize(amount_step, rounding=ROUND_HALF_UP)
    payload = {k: request[k] for k in ('company_id', 'customer_id', 'quote_id', 'revision', 'recipient_id', 'issued_on', 'valid_until') + TERMS}
    payload['tax_rate'] = str(rate)
    payload.update({'lines': rows, 'fees': fees, 'subtotal': str(subtotal), 'tax': str(tax), 'total': str(subtotal + tax)})
    out = {'status': 'BLOCKED' if blockers else 'DRAFT_REQUIRES_APPROVAL', 'payload': payload,
           'internal': internal, 'blockers': blockers, 'required_roles': sorted(set(roles)),
           'policy': copy.deepcopy(policy), 'evaluated_on': str(as_of)}
    out['quote_hash'] = digest(out)
    return out


def verify_quote(q):
    require(isinstance(q, dict) and 'quote_hash' in q, 'invalid quote')
    material = {k: v for k, v in q.items() if k != 'quote_hash'}
    require(digest(material) == q['quote_hash'], 'quote integrity mismatch: recalculate and reapprove')


def approval_gate(q, approvals, as_of):
    verify_quote(q)
    current = day(as_of)
    reasons = list(q['blockers'])
    if day(q['payload']['valid_until']) < current:
        reasons.append('quote expired')
    if q['status'] != 'DRAFT_REQUIRES_APPROVAL':
        reasons.append('quote not eligible for approval')
    require(isinstance(approvals, list), 'approvals must be array')
    satisfied = set()
    for a in approvals:
        if not isinstance(a, dict):
            continue
        if (a.get('quote_hash') == q['quote_hash'] and a.get('decision') == 'approved'
                and a.get('actor_id') and a.get('audit_event_id')
                and day(a.get('approved_on')) <= current <= day(a.get('expires_on'))):
            satisfied.add(a.get('role'))
    reasons.extend('missing approval role: ' + r for r in q['required_roles'] if r not in satisfied)
    return {'ok': not reasons, 'blockers': reasons,
            'identity_verification': 'REQUIRED_BY_HOST; this function only checks record consistency'}


def clean(value):
    # Prevent Markdown/table/control characters from breaking the customer document.
    s = ' '.join(str(value).split())
    for old, new in (('&', '&amp;'), ('<', '&lt;'), ('>', '&gt;'), ('|', '&#124;'), ('`', '&#96;'),
                     ('[', '&#91;'), (']', '&#93;'), ('*', '&#42;'), ('_', '&#95;')):
        s = s.replace(old, new)
    return s


def render(q):
    verify_quote(q)
    p = q['payload']
    lines = ['# 報價草稿｜尚未核准，請勿對外承諾', '',
             f'報價：{clean(p["quote_id"])} / Rev.{p["revision"]}',
             f'客戶：{clean(p["customer_id"])}', f'幣別：{p["currency"]}', '',
             '| 品項 | 客戶料號 | 品名 | 版本 | 數量 | 單位 | 未稅單價 | 未稅金額 |',
             '|---|---|---|---|---:|---|---:|---:|']
    for r in p['lines']:
        lines.append('| ' + ' | '.join(clean(r[k]) for k in ('line_id', 'customer_part', 'description', 'revision', 'quantity', 'unit', 'unit_price', 'amount')) + ' |')
    for fee in p['fees']:
        lines.append(f'\n額外費用：{clean(fee["description"])}：{fee["amount"]}')
    lines.extend(['', f'未稅合計：{p["subtotal"]}', f'稅額：{p["tax"]}', f'含稅總額：{p["total"]}',
                  f'付款條件：{clean(p["payment_terms"])}', f'交貨條件：{clean(p["delivery_terms"])}',
                  f'交貨地代碼：{clean(p["ship_to_id"])}', f'交期：{clean(p["delivery_date"] or "待確認")}',
                  f'有效至：{p["valid_until"]}', '', '本文件為內部產生的客戶格式草稿；須完成核准與收件人確認。'])
    # No blocker details, costs, margins, internal part IDs or policy fields in customer view.
    return '\n'.join(lines) + '\n'


def reconcile(q, po, as_of):
    verify_quote(q)
    require(isinstance(po, dict), 'PO must be object')
    p = q['payload']
    differences = []
    for field in set(po) - set(('company_id', 'customer_id', 'quote_id', 'revision', 'subtotal', 'tax', 'total',
                               'additional_terms', 'lines', 'fees') + TERMS):
        differences.append({'field': field, 'expected': 'unmodeled field requires review', 'actual': po[field]})
    if q['blockers']:
        differences.append({'field': 'quote.blockers', 'expected': [], 'actual': q['blockers']})
    if day(p['valid_until']) < day(as_of):
        differences.append({'field': 'valid_until', 'expected': 'current quote', 'actual': p['valid_until']})
    def compare(field, expected, actual, numeric=False):
        if actual is None:
            differences.append({'field': field, 'expected': expected, 'actual': None})
            return
        equal = number(expected, field) == number(actual, field) if numeric else expected == actual
        if not equal:
            differences.append({'field': field, 'expected': expected, 'actual': actual})
    for key in ('company_id', 'customer_id', 'quote_id', 'revision') + TERMS + ('subtotal', 'tax', 'total'):
        compare(key, p[key], po.get(key), key in ('tax_rate', 'subtotal', 'tax', 'total'))
    if po.get('additional_terms') != []:
        differences.append({'field': 'additional_terms', 'expected': [], 'actual': po.get('additional_terms')})
    unique_lines(po.get('lines'))
    require(type(po.get('revision')) is int, 'PO.revision must be integer')
    expected = {r['line_id']: r for r in p['lines']}
    actual = {r['line_id']: r for r in po['lines']}
    compare('line_ids', sorted(expected), sorted(actual))
    for key in expected.keys() & actual.keys():
        for field in set(actual[key]) - set(('line_id',) + LINE_FIELDS):
            differences.append({'field': f'lines.{key}.{field}', 'expected': 'unmodeled field requires review', 'actual': actual[key][field]})
        for field in LINE_FIELDS:
            compare(f'lines.{key}.{field}', expected[key][field], actual[key].get(field), field in ('quantity', 'unit_price', 'amount'))
    require(isinstance(po.get('fees'), list), 'PO.fees must be explicit array')
    actual_fees = {}
    for fee in po['fees']:
        known_fields(fee, FEE_FIELDS, 'PO fee')
        key = text_field(fee, 'fee_id')
        require(key not in actual_fees, 'duplicate PO fee_id')
        actual_fees[key] = fee
    expected_fees = {r['fee_id']: r for r in p['fees']}
    compare('fee_ids', sorted(expected_fees), sorted(actual_fees))
    for key in expected_fees.keys() & actual_fees.keys():
        for field in FEE_FIELDS:
            compare(f'fees.{key}.{field}', expected_fees[key][field], actual_fees[key].get(field), field == 'amount')
    return {'ok': not differences, 'status': 'FIELDS_MATCH_REQUIRES_HOST_APPROVAL' if not differences else 'REVIEW',
            'differences': differences, 'note': 'Matching is not authorization to accept PO or write ERP.'}


def demo(output_dir):
    root = Path(__file__).resolve().parents[1]
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    q = quote(read(root / 'examples/quote-request.json'))
    write(out / 'quote.json', q)
    (out / 'customer-draft.md').write_text(render(q), encoding='utf-8')
    po = read(root / 'examples/po.json')
    report = reconcile(q, po, '2026-11-12')
    write(out / 'reconciliation.json', report)
    result = {'demo_only': True, 'output_dir': str(out), 'quote_status': q['status'],
              'po_match': report['ok'], 'total': q['payload']['total']}
    write(out / 'demo-summary.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='cmd', required=True)
    for cmd in ('validate', 'intake', 'match', 'quote', 'render'):
        p = sub.add_parser(cmd)
        p.add_argument('--input', required=True)
        if cmd in ('quote', 'render'):
            p.add_argument('--output', required=True)
        if cmd == 'intake':
            p.add_argument('--db', required=True)
        if cmd == 'match':
            p.add_argument('--catalog', required=True)
    p = sub.add_parser('reconcile')
    p.add_argument('--quote', required=True)
    p.add_argument('--po', required=True)
    p.add_argument('--as-of', default=today())
    p = sub.add_parser('approval-check')
    p.add_argument('--quote', required=True)
    p.add_argument('--approvals', required=True)
    p.add_argument('--as-of', default=today())
    p = sub.add_parser('demo')
    p.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    try:
        if args.cmd == 'demo':
            result = demo(args.output_dir)
        elif args.cmd == 'reconcile':
            result = reconcile(read(args.quote), read(args.po), args.as_of)
        elif args.cmd == 'approval-check':
            result = approval_gate(read(args.quote), read(args.approvals), args.as_of)
        else:
            data = read(args.input)
            if args.cmd == 'validate':
                result = validate_case(data)
            elif args.cmd == 'intake':
                result = intake(data, args.db)
            elif args.cmd == 'match':
                result = match(data, read(args.catalog))
            elif args.cmd == 'quote':
                result = quote(data)
                write(args.output, result)
            else:
                content = render(data)
                Path(args.output).parent.mkdir(parents=True, exist_ok=True)
                Path(args.output).write_text(content, encoding='utf-8')
                result = {'draft_written': args.output}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if result.get('ok') is False or result.get('status') == 'BLOCKED' or result.get('payload_conflict') else 0
    except (InputError, KeyError, TypeError, ValueError, OSError, sqlite3.Error, InvalidOperation) as exc:
        print(json.dumps({'error': str(exc), 'status': 'INVALID_INPUT'}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
