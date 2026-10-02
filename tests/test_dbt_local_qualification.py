"""Focused overlay, timeout evidence, and independent Hex fact comparison tests."""
import copy
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SKILL=Path(__file__).resolve().parents[1]/'skills/data-model-accelerator'
sys.path.insert(0,str(SKILL/'scripts'))

def optional_dependencies_available():
    if not all(importlib.util.find_spec(name) for name in ('duckdb','yaml')):return False
    try:
        for distribution in ('dbt-core','dbt-duckdb'):importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:return False
    return True

HAS_NATIVE_DBT=optional_dependencies_available()
if HAS_NATIVE_DBT:
    import run_dbt_local_qualification as qualification


@unittest.skipUnless(HAS_NATIVE_DBT,'Optional native dbt/DuckDB qualification dependencies are required')
class ReviewedFixturePinTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.repo=Path(self.tmp.name).resolve()
        self.project=self.repo/'target/dbt';self.project.mkdir(parents=True)
        self.sql=self.project/'model.sql';self.sql.write_text('select 1 as invoice_id\n')
        self.expected=self.repo/'expected.json';self.expected.write_text('{"invoices": [{"invoice_id": 1}]}\n')
        self.paths=[self.sql,self.expected]
        self.manifest=self.repo/'review.json'
        self.manifest.write_text(json.dumps({'artifacts':[{'path':p.relative_to(self.repo).as_posix(),'sha256':qualification.digest(p)} for p in self.paths]})+'\n')

    def test_altered_pinned_sql_or_expected_results_are_rejected(self):
        self.assertEqual(qualification.verify_file_pins(self.repo,self.manifest,self.paths),qualification.digest(self.manifest))
        for path in self.paths:
            with self.subTest(path=path.name):
                original=path.read_bytes();path.write_bytes(original+b'\n')
                with self.assertRaisesRegex(ValueError,'Bundled fixture changed from reviewed pin'):
                    qualification.verify_file_pins(self.repo,self.manifest,self.paths)
                path.write_bytes(original)

    def test_added_unpinned_project_file_is_rejected(self):
        added=self.project/'unreviewed.sql';added.write_text('select 2 as invoice_id\n')
        current_paths=[p for p in self.project.rglob('*') if p.is_file()]+[self.expected]
        with self.assertRaisesRegex(ValueError,'Bundled fixture changed from reviewed pin: target/dbt/unreviewed.sql'):
            qualification.verify_file_pins(self.repo,self.manifest,current_paths)


@unittest.skipUnless(HAS_NATIVE_DBT,'Optional native dbt/DuckDB qualification dependencies are required')
class DbtOverlayAndTimeoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.source=SKILL/'examples/hex-omni-e2e/target/dbt'
        self.before=qualification.hashes(self.source)
        self.state=qualification.prepare('hex',Path(self.tmp.name).resolve()/'hex')
        self.addCleanup(lambda:self.assertEqual(qualification.hashes(self.source),self.before,'Frozen source candidate changed'))

    def test_qualified_month_overlay_preserves_source_and_records_exact_changed_artifact(self):
        relative='models/gold/fct_customer_month.sql'
        source=self.source/relative;executed=self.state['project']/relative
        original=source.read_text();overlay=executed.read_text()
        native="TO_CHAR(m.INVOICE_MONTH, 'YYYY-MM-DD')"
        local="STRFTIME(m.INVOICE_MONTH, '%Y-%m-%d')"
        self.assertEqual(original.count(native),1)
        self.assertEqual(overlay,original.replace(native,local))
        self.assertEqual(qualification.hashes(self.source),self.before)
        receipt=json.loads((self.state['output']/'overlay.json').read_text())
        changed=next(item for item in receipt['changes'] if item['path']==relative)
        self.assertEqual(changed['iso_month_format'],1)
        self.assertEqual(changed['number_to_decimal'],0)
        self.assertEqual(changed['iso_date_format'],0)
        self.assertEqual(changed['original_sha256'],qualification.digest(source))
        self.assertEqual(changed['overlay_sha256'],qualification.digest(executed))
        self.assertNotEqual(changed['original_sha256'],changed['overlay_sha256'])
        self.assertEqual(receipt['original_project_hashes'],self.before)
        self.assertEqual(receipt['executed_project_hashes'],qualification.hashes(self.state['project']))
        self.assertIn('Snowflake remains unverified',receipt['scope'])

    def test_parse_timeout_retains_partial_text_and_bytes_output(self):
        qualification.load_raw(self.state,self.state['raw'],self.state['adjustments'])
        for kind,stdout,stderr in [('text','partial parse progress\n','partial adapter diagnostic\n'),('bytes',b'partial parse bytes\n',b'partial adapter bytes\n')]:
            with self.subTest(kind=kind):
                label='timeout-'+kind
                timeout=subprocess.TimeoutExpired(cmd=['dbt','parse'],timeout=120,output=stdout,stderr=stderr)
                with patch.object(qualification.subprocess,'run',side_effect=timeout) as process:
                    summary=qualification.dbt(self.state,label,command='parse')
                process.assert_called_once()
                self.assertEqual(summary['exit_code'],124)
                self.assertEqual(summary['command'],'parse')
                artifact=self.state['output']/label
                out_text=stdout.decode('utf-8') if isinstance(stdout,bytes) else stdout
                err_text=stderr.decode('utf-8') if isinstance(stderr,bytes) else stderr
                self.assertIn(out_text,(artifact/'stdout.txt').read_text())
                self.assertIn(err_text,(artifact/'stderr.txt').read_text())
                self.assertEqual(json.loads((artifact/'summary.json').read_text())['exit_code'],124)
                self.assertTrue(summary['project_unchanged'])


@unittest.skipUnless(HAS_NATIVE_DBT,'Optional native dbt/DuckDB qualification dependencies are required')
class HexCustomerMonthComparisonTests(unittest.TestCase):
    def setUp(self):
        # Same customer/month across tenants catches comparison keyed too narrowly.
        self.expected=[
            {'tenant_id':'A','customer_id':'C1','month':'2026-01-01','net_cents':11000,'paid_cents':10000,'has_invoice':True,'has_paid_invoice':True,'first_paid_month':'2026-01-01'},
            {'tenant_id':'B','customer_id':'C1','month':'2026-01-01','net_cents':2000,'paid_cents':0,'has_invoice':True,'has_paid_invoice':False,'first_paid_month':None},
        ]
        self.actual=[
            {'tenant_id':'A','customer_id':'C1','invoice_month':'2026-01-01','net_cents':11000,'paid_cents':10000,'outstanding_cents':1000,'has_invoice':1,'has_paid_invoice':1,'first_paid_month':'2026-01-01','customer_month_key':'A|C1|2026-01-01'},
            {'tenant_id':'B','customer_id':'C1','invoice_month':'2026-01-01','net_cents':2000,'paid_cents':0,'outstanding_cents':2000,'has_invoice':1,'has_paid_invoice':0,'first_paid_month':None,'customer_month_key':'B|C1|2026-01-01'},
        ]

    def test_matches_oracle_month_and_all_declared_fields(self):
        self.assertTrue(qualification.customer_months_match(self.actual,self.expected))
        self.assertTrue(qualification.customer_months_match(list(reversed(self.actual)),self.expected))

    def test_rejects_incorrect_aggregate_even_when_outstanding_is_consistent(self):
        changed=copy.deepcopy(self.actual)
        changed[0]['net_cents']+=500
        changed[0]['outstanding_cents']+=500
        self.assertFalse(qualification.customer_months_match(changed,self.expected))

    def test_rejects_wrong_tenant_scoped_customer_month_key(self):
        changed=copy.deepcopy(self.actual)
        changed[1]['customer_month_key']='A|C1|2026-01-01'
        self.assertFalse(qualification.customer_months_match(changed,self.expected))

    def test_rejects_wrong_outstanding_value(self):
        changed=copy.deepcopy(self.actual);changed[0]['outstanding_cents']=0
        self.assertFalse(qualification.customer_months_match(changed,self.expected))

    def test_rejects_cohort_and_activity_flag_drift(self):
        for field,value in [('first_paid_month','2026-02-01'),('has_paid_invoice',0),('has_invoice',0)]:
            with self.subTest(field=field):
                changed=copy.deepcopy(self.actual);changed[0][field]=value
                self.assertFalse(qualification.customer_months_match(changed,self.expected))

    def test_rejects_missing_and_duplicate_rows(self):
        self.assertFalse(qualification.customer_months_match(self.actual[:1],self.expected))
        self.assertFalse(qualification.customer_months_match([self.actual[0],self.actual[0]],self.expected))
        self.assertFalse(qualification.customer_months_match(self.actual+[self.actual[0]],self.expected))


if __name__=='__main__':unittest.main()
