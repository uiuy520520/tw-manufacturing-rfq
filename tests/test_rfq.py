import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import rfq


class RFQTests(unittest.TestCase):
    def setUp(self):
        self.request = rfq.read(ROOT / 'examples/quote-request.json')
        self.case = rfq.read(ROOT / 'examples/case.json')
        self.catalog = rfq.read(ROOT / 'examples/catalog.json')
        self.po = rfq.read(ROOT / 'examples/po.json')

    def quote(self):
        return rfq.quote(self.request)

    def test_margin_and_tax(self):
        q = self.quote()
        self.assertEqual(q['blockers'], [])
        self.assertEqual(q['payload']['lines'][0]['unit_price'], '100.00')
        self.assertEqual(q['payload']['total'], '54600')

    def test_round_unit_before_line(self):
        self.request['lines'][0].update(unit_cost='0.804', quantity='3')
        self.request['fees'] = []
        self.request['policy']['amount_places'] = 2
        q = self.quote()['payload']
        self.assertEqual(q['lines'][0]['unit_price'], '1.01')
        self.assertEqual(q['subtotal'], '3.03')
        self.assertEqual(q['tax'], '0.15')

    def test_invalid_numbers(self):
        for bad in ['-1', 'NaN', 'Infinity', 1.5, True, '1e999', '0.000000001']:
            with self.subTest(value=bad), self.assertRaises(rfq.InputError):
                rfq.number(bad, 'test')

    def test_zero_quantity(self):
        self.request['lines'][0]['quantity'] = '0'
        with self.assertRaises(rfq.InputError):
            self.quote()

    def test_low_margin(self):
        self.request['lines'][0]['unit_price'] = '81'
        self.assertIn('margin below', ' '.join(self.quote()['blockers']))

    def test_expired_and_future_cost(self):
        for start, end in [('2026-10-01', '2026-10-31'), ('2026-11-20', '2026-11-30')]:
            self.request['lines'][0].update(cost_valid_from=start, cost_valid_until=end)
            self.assertIn('cost is not current', ' '.join(self.quote()['blockers']))

    def test_validity_exceeds_cost(self):
        self.request['valid_until'] = '2026-12-01'
        self.assertIn('exceeds cost', ' '.join(self.quote()['blockers']))

    def test_unsupported_tax_currency_unit(self):
        for key, val in [('cost_currency', 'USD'), ('cost_unit', 'KG')]:
            req = copy.deepcopy(self.request)
            req['lines'][0][key] = val
            with self.assertRaises(rfq.InputError):
                rfq.quote(req)
        self.request['tax_mode'] = 'inclusive'
        with self.assertRaises(rfq.InputError):
            self.quote()

    def test_missing_policy_delivery_credit_issues(self):
        self.request['policy']['approved_policy_id'] = None
        self.request['delivery_date'] = None
        self.request['credit_cleared'] = False
        self.request.pop('unresolved_issues')
        self.assertGreaterEqual(len(self.quote()['blockers']), 4)

    def test_duplicate_lines_fees(self):
        self.request['lines'].append(copy.deepcopy(self.request['lines'][0]))
        with self.assertRaises(rfq.InputError):
            self.quote()
        self.request['lines'].pop()
        self.request['fees'].append(copy.deepcopy(self.request['fees'][0]))
        with self.assertRaises(rfq.InputError):
            self.quote()

    def test_evidence_and_conflicts(self):
        self.assertTrue(rfq.validate_case(self.case)['ok'])
        del self.case['lines'][0]['evidence']['quantity']
        self.case['issues'] = [{'blocking': True, 'message': 'quantity conflict'}]
        self.assertEqual(len(rfq.validate_case(self.case)['blockers']), 2)

    def test_exact_match_and_revision(self):
        self.assertTrue(rfq.match(self.case, self.catalog)['ok'])
        self.case['lines'][0]['revision'] = 'B'
        self.assertFalse(rfq.match(self.case, self.catalog)['ok'])

    def test_ambiguous_and_customer_isolation(self):
        self.catalog.append(copy.deepcopy(self.catalog[0]))
        self.assertFalse(rfq.match(self.case, self.catalog)['ok'])
        self.catalog.pop()
        self.case['customer_id'] = 'OTHER'
        self.assertFalse(rfq.match(self.case, self.catalog)['ok'])

    def test_conflicting_internal_and_customer_part(self):
        self.case['lines'][0]['internal_part'] = 'P-002'
        self.catalog.append({'internal_part': 'P-002', 'revision': 'A', 'unit': 'PCS', 'customer_parts': {}})
        self.assertFalse(rfq.match(self.case, self.catalog)['ok'])

    def test_intake_replay_and_payload_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / 'cases.db')
            a = rfq.intake(self.case, db)
            b = rfq.intake(self.case, db)
            self.assertTrue(a['created'])
            self.assertFalse(b['created'])
            self.assertEqual(a['case_id'], b['case_id'])
            self.case['lines'][0]['quantity'] = '600'
            self.assertTrue(rfq.intake(self.case, db)['payload_conflict'])
            self.case['customer_id'] = 'OTHER'
            self.assertTrue(rfq.intake(self.case, db)['created'])

    def approvals(self, q):
        return [{'quote_hash': q['quote_hash'], 'actor_id': role + '-person', 'role': role,
                 'decision': 'approved', 'approved_on': '2026-11-12', 'expires_on': '2026-11-20',
                 'audit_event_id': 'DEMO-' + role} for role in q['required_roles']]

    def test_approval_required(self):
        q = self.quote()
        self.assertFalse(rfq.approval_gate(q, [], '2026-11-12')['ok'])
        self.assertTrue(rfq.approval_gate(q, self.approvals(q), '2026-11-12')['ok'])
        self.assertFalse(rfq.approval_gate(q, self.approvals(q), '2026-11-21')['ok'])

    def test_edited_quote_rejected(self):
        q = self.quote()
        q['payload']['total'] = '1'
        with self.assertRaises(rfq.InputError):
            rfq.approval_gate(q, [], '2026-11-12')

    def test_recalculated_quote_requires_new_approvals(self):
        q = self.quote()
        approvals = self.approvals(q)
        self.request['recipient_id'] = 'DIFFERENT'
        q2 = self.quote()
        self.assertFalse(rfq.approval_gate(q2, approvals, '2026-11-12')['ok'])

    def test_internal_changes_change_hash(self):
        q = self.quote()
        self.request['lines'][0]['cost_source'] = 'NEW-COST'
        self.assertNotEqual(q['quote_hash'], self.quote()['quote_hash'])

    def test_po_matching_and_numeric_equivalence(self):
        self.po['lines'][0]['unit_price'] = '100'
        self.assertTrue(rfq.reconcile(self.quote(), self.po, '2026-11-12')['ok'])

    def test_po_changes_and_missing_fields(self):
        self.po['lines'][0]['quantity'] = '499'
        self.po['payment_terms'] = '月結90天'
        self.po.pop('tax')
        result = rfq.reconcile(self.quote(), self.po, '2026-11-12')
        self.assertFalse(result['ok'])
        self.assertEqual(len(result['differences']), 3)

    def test_po_duplicates_and_extra_terms(self):
        self.po['additional_terms'] = ['額外保固條款']
        self.assertFalse(rfq.reconcile(self.quote(), self.po, '2026-11-12')['ok'])
        self.po['lines'].append(copy.deepcopy(self.po['lines'][0]))
        with self.assertRaises(rfq.InputError):
            rfq.reconcile(self.quote(), self.po, '2026-11-12')

    def test_po_expired_quote(self):
        self.assertFalse(rfq.reconcile(self.quote(), self.po, '2026-12-01')['ok'])

    def test_customer_render_no_internal_data(self):
        self.request['lines'][0]['internal_part'] = 'SECRET-INTERNAL-PART'
        q = self.quote()
        text = rfq.render(q)
        for secret in ('unit_cost', 'actual_margin', 'DEMO-COST-001', 'minimum_margin', 'SECRET-INTERNAL-PART'):
            self.assertNotIn(secret, text)
        self.assertIn('54600', text)
        self.assertIn('尚未核准', text)

    def test_render_escapes_untrusted_text(self):
        self.request['lines'][0]['description'] = '<script>x</script> | [click](https://example.test)'
        text = rfq.render(self.quote())
        self.assertNotIn('<script>', text)
        self.assertNotIn('[click]', text)

    def test_json_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'bad.json'
            p.write_text('{"quantity":1,"quantity":2}')
            with self.assertRaises(rfq.InputError):
                rfq.read(p)

    def test_explicit_wrong_internal_part(self):
        self.case['lines'][0]['internal_part'] = 'UNKNOWN-PART'
        self.assertFalse(rfq.match(self.case, self.catalog)['ok'])

    def test_unmodeled_quote_fields_block(self):
        self.request['discount'] = '0.10'
        with self.assertRaises(rfq.InputError):
            self.quote()

    def test_unmodeled_po_fields_review(self):
        self.po['warranty'] = '10 years'
        self.assertFalse(rfq.reconcile(self.quote(), self.po, '2026-11-12')['ok'])

    def test_large_supported_amount(self):
        self.request['lines'][0].update(unit_cost='100000000000', quantity='1000000000000')
        self.assertEqual(self.quote()['payload']['lines'][0]['amount'], '125000000000000000000000')

    def test_demo(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = rfq.demo(tmp)
            self.assertTrue(result['po_match'])
            self.assertEqual(result['total'], '54600')


if __name__ == '__main__':
    unittest.main()
