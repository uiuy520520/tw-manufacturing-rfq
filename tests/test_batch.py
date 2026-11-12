import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import rfq
import run_batch


class BatchTests(unittest.TestCase):
    def test_demo(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary, code = run_batch.run('demo', 'examples', tmp)
            self.assertEqual(code, 0)
            self.assertTrue(summary['po_match'])

    def test_stale_input_date_is_overridden(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary, code = run_batch.run('batch', 'examples', tmp, as_of='2027-01-01')
            self.assertEqual(code, 2)
            self.assertEqual(summary['status'], 'REVIEW_REQUIRED')
            q = rfq.read(Path(tmp) / 'quote.json')
            self.assertIn('quote expired', q['blockers'])
            self.assertTrue((Path(tmp) / 'customer-draft.md').exists())

    def test_current_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary, code = run_batch.run('batch', 'examples', tmp, as_of='2026-11-12')
            self.assertEqual(code, 0)
            self.assertEqual(summary['external_actions'], 'NONE')

    def test_path_traversal(self):
        for path in ('../', '/tmp'):
            with self.subTest(path=path), self.assertRaises(rfq.InputError):
                run_batch.case_directory(path, ROOT)

    def test_symlink_escape(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            (root / 'data').symlink_to(outside, target_is_directory=True)
            with self.assertRaises(rfq.InputError):
                run_batch.case_directory('data', root)


if __name__ == '__main__':
    unittest.main()
