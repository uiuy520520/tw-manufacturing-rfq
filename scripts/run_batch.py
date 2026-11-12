#!/usr/bin/env python3
"""GitHub/local batch wrapper. Never sends email or writes ERP."""
import argparse
import json
import sys
from pathlib import Path

import rfq


def case_directory(value, root):
    p = Path(value)
    rfq.require(not p.is_absolute(), 'case directory must be repo-relative')
    resolved = (root / p).resolve()
    rfq.require(resolved.is_relative_to(root.resolve()) and resolved.is_dir(), 'case directory escapes repo or is missing')
    return resolved


def run(mode, case_dir, output_dir, root=None, as_of=None):
    root = root or Path(__file__).resolve().parents[1]
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    if mode == 'demo':
        return rfq.demo(out), 0
    rfq.require(mode == 'batch', 'unsupported mode')
    case_root = case_directory(case_dir, root)
    for name in ('quote-request.json', 'po.json'):
        rfq.require((case_root / name).resolve().is_relative_to(root.resolve()), 'input symlink escapes repo')
    request = rfq.read(case_root / 'quote-request.json')
    # Actual batches use the execution date, never an old date supplied by the document.
    request['as_of'] = as_of or rfq.today()
    q = rfq.quote(request)
    rfq.write(out / 'quote.json', q)
    (out / 'customer-draft.md').write_text(rfq.render(q), encoding='utf-8')
    needs_review = bool(q['blockers'])
    po_path = case_root / 'po.json'
    po_match = None
    if po_path.exists():
        report = rfq.reconcile(q, rfq.read(po_path), request['as_of'])
        rfq.write(out / 'reconciliation.json', report)
        po_match = report['ok']
        needs_review = needs_review or not po_match
    summary = {'mode': 'batch', 'status': 'REVIEW_REQUIRED' if needs_review else 'DRAFT_REQUIRES_APPROVAL',
               'as_of': request['as_of'], 'blocker_count': len(q['blockers']), 'po_fields_match': po_match,
               'external_actions': 'NONE'}
    rfq.write(out / 'batch-summary.json', summary)
    return summary, 2 if needs_review else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('demo', 'batch'), default='demo')
    parser.add_argument('--case-dir', default='examples')
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    try:
        summary, code = run(args.mode, args.case_dir, args.output_dir)
        # Keep costs, customer data and raw inputs out of workflow logs.
        print(json.dumps({'status': summary.get('status', 'DEMO_COMPLETE'), 'external_actions': 'NONE'}))
        return code
    except (ValueError, TypeError, KeyError, OSError, ArithmeticError):
        # Error strings could include source values; detailed diagnosis stays local.
        print('INPUT_OR_PROCESSING_ERROR: inspect input locally; no external action executed.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
