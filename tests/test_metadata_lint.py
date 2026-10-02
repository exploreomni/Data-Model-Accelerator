"""Metadata participates in real six-dialect lint; exceptions remain explicit."""
import unittest
from test_lint_delivery import Fixture, RUNTIME, lint
from test_metadata_contract import dictionary, configuration
from test_warehouse_metadata_plan import observation
from metadata_contract import build_contract
from plan_warehouse_metadata import plan_metadata


@unittest.skipUnless(RUNTIME, 'Pinned SQLFluff runtime is required for metadata lint qualification')
class MetadataLintTests(Fixture):
    def test_six_dialects_retain_findings_and_exact_reviewed_style_exceptions(self):
        for warehouse in ('snowflake','databricks','bigquery','redshift','clickhouse','motherduck'):
            with self.subTest(warehouse=warehouse):
                self.manifest={'schema_version':1,'kind':'sql_lint_manifest','files':[],'expected_execution_units':[]}
                self.target['warehouse']=warehouse
                contract=build_contract(dictionary(),configuration(warehouse))
                plan=plan_metadata(contract,observation(contract))
                for index,operation in enumerate(plan['operations']):
                    self.assertTrue(operation['sql'].endswith('\n'))
                    item=self.add('metadata-%s.sql'%index,operation['sql'])
                    self.assertEqual(item['sha256'],operation['sha256'])
                raw=self.run_lint()
                for file in raw['files']:
                    codes={finding['code'] for finding in file['findings']}
                    self.assertTrue(codes <= {'LT05','RF06'},file['findings'])
                    for code in sorted(codes):
                        self.allow_style(file['path'],code,'Preserve exact identifiers and complete metadata literals in this reviewed fixture.')
                report=self.run_lint()
                self.assertEqual(report['status'],'passed',report['files'])
                self.assertFalse(report['style_exceptions']['human_approval'])
                verified=lint.verify_report(report,self.root,self.target,self.manifest,runtime=RUNTIME)
                self.assertFalse(verified['native_verified'])


if __name__=='__main__':
    unittest.main()
