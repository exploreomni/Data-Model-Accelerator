"""Coverage and oracle integrity checks; optional E2E dependencies required."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills/data-model-accelerator/scripts'
CASE = SCRIPTS.parent / 'examples/looker-omni-e2e'
sys.path.insert(0, str(SCRIPTS))
AVAILABLE = all(importlib.util.find_spec(name) for name in ('duckdb', 'sqlglot', 'lkml', 'yaml'))
if AVAILABLE:
    from run_looker_omni_e2e import load_test_plan, coverage_complete, report_contract, assert_contract
    from e2e_semantics import describe_looker, describe_omni


@unittest.skipUnless(AVAILABLE, 'Install scripts/requirements-e2e.txt for the optional E2E suite')
class E2EReviewIntegrity(unittest.TestCase):
    def test_predeclared_plan_and_report_mapping(self):
        plan = load_test_plan(CASE)
        self.assertEqual(len(plan['scenario_ids']), 9)
        self.assertEqual(len(plan['required_test_ids']), 59)
        for describe, path in [(describe_looker, CASE/'input/repo'), (describe_omni, CASE/'target/omni')]:
            assert_contract(report_contract(describe(path)), plan['report_contract'])

    def test_missing_required_test_fails(self):
        with self.assertRaisesRegex(ValueError, 'missing='):
            coverage_complete(['grain', 'tenant'], [{'id':'grain', 'status':'pass'}])

    def test_duplicate_check_cannot_fill_coverage(self):
        with self.assertRaises(ValueError):
            coverage_complete(['grain', 'tenant'], [{'id':'grain','status':'pass'}]*2)

    def test_failed_required_check_cannot_pass(self):
        self.assertFalse(coverage_complete(['grain'], [{'id':'grain','status':'fail'}]))

    def test_expected_rows_cannot_be_rewritten_to_match_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp)/'case'; shutil.copytree(CASE, copy)
            path = copy/'expected/expected_rows.json'
            rows = json.loads(path.read_text()); rows[0]['net_cents'] += 1
            path.write_text(json.dumps(rows))
            with self.assertRaisesRegex(ValueError, 'Frozen oracle/scenario changed'):
                load_test_plan(copy)

    def test_scenario_inventory_cannot_silently_shrink(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp)/'case'; shutil.copytree(CASE, copy)
            path = copy/'test-plan.json'; plan = json.loads(path.read_text())
            plan['scenario_ids'].pop(); path.write_text(json.dumps(plan))
            with self.assertRaisesRegex(ValueError, 'scenario inventory'):
                load_test_plan(copy)

    def test_dashboard_behavior_change_fails_even_with_explicit_query_overrides(self):
        contract = load_test_plan(CASE)['report_contract']
        for key, replacement in [('defaults', {'currency':'EUR'}), ('fields', ['invoices.invoice_count']),
                                 ('limit', 1), ('listen', {})]:
            changed = deepcopy(contract); changed[key] = replacement
            with self.subTest(key=key), self.assertRaises(AssertionError):
                assert_contract(changed, contract)


if __name__ == '__main__':
    unittest.main()
