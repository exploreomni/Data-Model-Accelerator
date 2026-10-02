"""Capability and recipe contracts; no live platform execution or qualification."""
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
import platform_matrix as matrix
import platform_readiness
import guided_workflow
import verify_catalogue
import plan_specialists


class PlatformMatrixTests(unittest.TestCase):
    def test_six_products_are_shared_by_intake_inventory_catalogue_and_specialists(self):
        products = set(matrix.WAREHOUSES)
        self.assertEqual(products, {'snowflake', 'databricks', 'bigquery', 'redshift', 'clickhouse', 'motherduck'})
        self.assertEqual(set(platform_readiness.ADAPTER_REGISTRY['warehouses']), products)
        self.assertEqual(guided_workflow.ENUMS['warehouse'], products | {'gcp'})
        self.assertEqual(set(guided_workflow.QUESTIONS['warehouse'][1]), products)
        self.assertEqual(verify_catalogue.PROVIDERS, products)
        self.assertTrue(products <= plan_specialists.SOURCE_TYPES)
        self.assertEqual(guided_workflow.ENUMS['framework'], {'dbt', 'coalesce', 'native_sql'})

    def test_profiles_are_json_safe_detached_and_never_live_qualified(self):
        with patch('subprocess.run', side_effect=AssertionError('must not execute')):
            for warehouse in matrix.WAREHOUSES:
                profile = matrix.get_platform(warehouse)
                json.dumps(profile, allow_nan=False)
                self.assertFalse(profile['native_qualified'])
                self.assertEqual(profile['static_lint']['version'], '4.3.0')
                self.assertEqual(profile['static_lint']['dialect'], 'duckdb' if warehouse == 'motherduck' else warehouse)
                self.assertTrue(profile['metadata']['identity_fields'])
                self.assertTrue(profile['physical_design'])
                self.assertTrue((SCRIPTS.parent / profile['metadata']['template']).is_file())
                for check in profile['native_checks']:
                    self.assertEqual(check['status'], 'recipe_only')
                    self.assertIs(type(check['connection_required']), bool)
                    self.assertTrue(check['cost'] and check['side_effects'] and check['coverage_gaps'])
                    self.assertTrue(check['documentation'].startswith('https://'))
                profile['native_checks'][0]['recipe'].append('CORRUPT')
                self.assertNotIn('CORRUPT', json.dumps(matrix.get_platform(warehouse)))

    def test_framework_matrix_does_not_infer_all_pairs_support(self):
        for warehouse in matrix.WAREHOUSES:
            self.assertEqual(matrix.get_pairing('dbt', warehouse)['status'], 'conditional')
            self.assertEqual(matrix.get_pairing('dbt_core', warehouse), matrix.get_pairing('dbt', warehouse))
            self.assertEqual(matrix.get_pairing('native_sql', warehouse)['status'], 'supported')
            hosted = matrix.get_pairing('dbt_platform', warehouse)
            coalesce = matrix.get_pairing('coalesce', warehouse)
            self.assertEqual(hosted['status'], 'conditional' if warehouse in matrix.DBT_PLATFORM_WAREHOUSES else 'unsupported')
            self.assertEqual(coalesce['status'], 'conditional' if warehouse in matrix.COALESCE_WAREHOUSES else 'unsupported')
            self.assertFalse(hosted['native_qualified'] or coalesce['native_qualified'])
        self.assertIn('Private beta', matrix.get_pairing('dbt_platform', 'clickhouse')['reason'])
        self.assertIn('CLI only', matrix.get_pairing('dbt_platform', 'motherduck')['reason'])

    def test_unknown_products_and_frameworks_fail_closed(self):
        for value in ('gcp', 'duckdb', '', None, []):
            with self.subTest(value=value), self.assertRaises(ValueError):
                matrix.get_platform(value)
        with self.assertRaises(ValueError):
            matrix.get_pairing('invented', 'snowflake')

    def test_native_formatting_is_not_semantic_lint_and_compile_is_not_offline(self):
        checks = {c['id']: c for c in matrix.get_platform('clickhouse')['native_checks']}
        self.assertEqual(checks['clickhouse_format_syntax']['kind'], 'native_syntax')
        self.assertFalse(checks['clickhouse_format_syntax']['connection_required'])
        self.assertIn('--quiet', checks['clickhouse_format_syntax']['recipe'])
        checks = {c['id']: c for c in matrix.get_pairing('dbt', 'redshift')['checks']}
        self.assertFalse(checks['dbt_parse']['connection_required'])
        self.assertTrue(checks['dbt_compile']['connection_required'])
        self.assertIn('DDL/DML', checks['dbt_compile']['side_effects'])
        self.assertIn('cloud extensions', ' '.join(matrix.get_platform('motherduck')['static_lint']['coverage_gaps']))

    def test_new_metadata_templates_only_contain_scoped_selects(self):
        # Contract guard, not a SQL parser or native acceptance claim.
        for warehouse in ('redshift', 'clickhouse', 'motherduck'):
            raw = (SCRIPTS.parent / matrix.get_platform(warehouse)['metadata']['template']).read_text()
            text = re.sub(r'--[^\n]*', '', raw)
            statements = [s.strip() for s in text.split(';') if s.strip()]
            self.assertGreaterEqual(len(statements), 3)
            self.assertTrue(all(re.match(r'^SELECT\b', s, re.I) for s in statements))
            self.assertFalse(re.search(r'\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|INSTALL|ATTACH|COPY)\b', text, re.I))
            self.assertIn('__DATABASE__', text)
            self.assertIn('NOT live-validated', raw)

    def test_demo_exercises_full_selection_space_without_enabling_unsupported_routes(self):
        from run_guided_delivery_demo import run
        with tempfile.TemporaryDirectory() as root:
            result = run(Path(root).resolve() / 'exercise')
            self.assertEqual(len(result['platform_routes']), len(matrix.WAREHOUSES) * len(matrix.FRAMEWORKS))
            rejected = [route for route in result['platform_routes'] if route['generation'] == 'unsupported']
            self.assertEqual({r['warehouse'] for r in rejected}, {'redshift', 'clickhouse', 'motherduck'})
            self.assertTrue(all(r['framework'] == 'coalesce' and r['execution'] == 'blocked' for r in rejected))
            self.assertFalse(result['native_execution_performed'])


if __name__ == '__main__':
    unittest.main()
