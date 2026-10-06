"""Platform discovery must surface security qualification separately from lint."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import platform_matrix as matrix
from security_capabilities import capabilities


class PlatformSecurityMatrixTests(unittest.TestCase):
    def test_all_platforms_surface_security_without_claiming_live_enforcement(self):
        for warehouse in matrix.WAREHOUSES:
            with self.subTest(warehouse=warehouse):
                profile = matrix.get_platform(warehouse)
                access = profile['access_enforcement']
                self.assertEqual(access, capabilities(warehouse))
                self.assertFalse(access['live_qualified'])
                self.assertTrue(access['documented'])
                self.assertTrue(access['unsupported_functions'])
                json.dumps(profile, allow_nan=False)

    def test_framework_routes_carry_independent_access_profile_even_if_unsupported(self):
        for framework in (*matrix.FRAMEWORKS, 'dbt_platform'):
            for warehouse in matrix.WAREHOUSES:
                with self.subTest(framework=framework, warehouse=warehouse):
                    pair = matrix.get_pairing(framework, warehouse)
                    self.assertEqual(pair['access_enforcement'], capabilities(warehouse, framework))
                    self.assertFalse(pair['access_enforcement']['live_qualified'])

    def test_returned_capability_cannot_mutate_shared_profile(self):
        first = matrix.get_platform('snowflake')['access_enforcement']
        first['live_qualified'] = True
        first['unsupported_functions'].append('mutable-test')
        next_profile = matrix.get_platform('snowflake')['access_enforcement']
        self.assertFalse(next_profile['live_qualified'])
        self.assertNotIn('mutable-test', next_profile['unsupported_functions'])


if __name__ == '__main__':
    unittest.main()
