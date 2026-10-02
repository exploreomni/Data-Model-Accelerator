"""Author-side assertions: hand-derived microfixtures and metamorphic controls, no hidden oracle."""
import copy,json,shutil,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import evaluator as e


def fixture():
    return {'origin':'synthetic','snapshot_at':'2026-09-11T12:00:00Z','tables':{
        'ORDER_CDC':[{'TENANT_ID':'A','ORDER_ID':'O1','ORDER_DATE':'2026-04-01','STATUS':'completed','SEQUENCE':1,'IS_DELETED':False}],
        'ORDER_LINE_CDC':[{'TENANT_ID':'A','ORDER_ID':'O1','LINE_ID':'L1','PRODUCT_ID':'P1','QUANTITY':3,'UNIT_PRICE_CENTS':1000,'DISCOUNT_CENTS':600,'SEQUENCE':1,'IS_DELETED':False}],
        'FULFILLMENT_CDC':[{'TENANT_ID':'A','FULFILLMENT_ID':'F1','ORDER_ID':'O1','LINE_ID':'L1','QUANTITY':2,'SEQUENCE':1,'IS_DELETED':False},{'TENANT_ID':'A','FULFILLMENT_ID':'F2','ORDER_ID':'O1','LINE_ID':'L1','QUANTITY':1,'SEQUENCE':1,'IS_DELETED':False}],
        'RETURN_CDC':[{'TENANT_ID':'A','RETURN_ID':'R1','ORDER_ID':'O1','LINE_ID':'L1','QUANTITY':1,'REFUND_CENTS':800,'SEQUENCE':1,'IS_DELETED':False},{'TENANT_ID':'A','RETURN_ID':'R2','ORDER_ID':'O1','LINE_ID':'L1','QUANTITY':1,'REFUND_CENTS':700,'SEQUENCE':1,'IS_DELETED':False}]}}

class RetailTests(unittest.TestCase):
    def test_hand_derived_fact_no_fanout_discount_once(self):
        r=e.evaluate(fixture(),{});f=r['gold'][0]
        self.assertEqual((f['ORDERED_QUANTITY'],f['FULFILLED_QUANTITY'],f['RETURNED_QUANTITY'],f['LINE_NET_CENTS'],f['REFUND_CENTS'],f['RETAINED_REVENUE_CENTS']),(3,3,2,2400,1500,900))
        self.assertEqual(r['report'][0]['FULFILLMENT_RATE'],1.0)
        self.assertEqual(list(f),e.CONTRACT['gold']['columns'])
    def test_weighted_ratio_recomputed_not_average_line_rates(self):
        raw=fixture();line=dict(raw['tables']['ORDER_LINE_CDC'][0],LINE_ID='L2',QUANTITY=1,DISCOUNT_CENTS=0)
        raw['tables']['ORDER_LINE_CDC'].append(line)
        report=e.evaluate(raw,{})['report'][0]
        self.assertEqual((report['ORDERED_QUANTITY'],report['FULFILLED_QUANTITY'],report['FULFILLMENT_RATE']),(4,3,0.75))
    def test_duplicate_and_reordered_capture_is_idempotent(self):
        raw=fixture();expected=e.evaluate(raw,{})
        for rows in raw['tables'].values():rows[:]=list(reversed(rows+copy.deepcopy(rows)))
        self.assertEqual(e.evaluate(raw,{}),expected)
    def test_later_correction_and_older_conflict(self):
        raw=fixture();raw['tables']['RETURN_CDC'].append(dict(raw['tables']['RETURN_CDC'][1],SEQUENCE=2,REFUND_CENTS=600))
        self.assertEqual(e.evaluate(raw,{})['gold'][0]['REFUND_CENTS'],1400)
        raw['tables']['RETURN_CDC'].append(dict(raw['tables']['RETURN_CDC'][1],REFUND_CENTS=701))
        with self.assertRaisesRegex(e.ValidationError,'conflicting payload'):e.evaluate(raw,{})
    def test_tombstone_applied_after_latest_for_each_event_and_line(self):
        raw=fixture();raw['tables']['RETURN_CDC'].append(dict(raw['tables']['RETURN_CDC'][1],SEQUENCE=2,IS_DELETED=True))
        self.assertEqual(e.evaluate(raw,{})['gold'][0]['REFUND_CENTS'],800)
        for table in ('ORDER_LINE_CDC','FULFILLMENT_CDC','RETURN_CDC'):
            raw['tables'][table]+=[dict(r,SEQUENCE=9,IS_DELETED=True) for r in raw['tables'][table] if r['SEQUENCE']==1]
        self.assertEqual(e.evaluate(raw,{}),{'gold':[],'report':[]})
    def test_orphan_lines_and_children_fail_with_no_accepted_output(self):
        for table in ('ORDER_LINE_CDC','FULFILLMENT_CDC','RETURN_CDC'):
            with self.subTest(table=table):
                raw=fixture();raw['tables'][table][0]['ORDER_ID']='MISSING'
                with self.assertRaisesRegex(e.ValidationError,'orphan'):e.evaluate(raw,{})
    def test_invalid_quantities_and_refund_policy(self):
        raw=fixture();raw['tables']['FULFILLMENT_CDC'][0]['QUANTITY']=4
        with self.assertRaisesRegex(e.ValidationError,'Fulfillment exceeds'):e.evaluate(raw,{})
        raw=fixture();raw['tables']['RETURN_CDC'][0]['QUANTITY']=3
        with self.assertRaisesRegex(e.ValidationError,'Returns exceed'):e.evaluate(raw,{})
        raw=fixture();raw['tables']['RETURN_CDC'][0]['REFUND_CENTS']=4000
        self.assertEqual(e.evaluate(raw,{})['gold'][0]['RETAINED_REVENUE_CENTS'],-2300)
    def test_full_capture_types_keys_and_discount_validation(self):
        cases=[('ORDER_LINE_CDC','QUANTITY',True),('ORDER_LINE_CDC','UNIT_PRICE_CENTS',0),('ORDER_LINE_CDC','DISCOUNT_CENTS',3001),('ORDER_CDC','ORDER_DATE','2026-02-30'),('ORDER_CDC','TENANT_ID','A|B'),('RETURN_CDC','REFUND_CENTS',-1),('ORDER_CDC','IS_DELETED',0),('ORDER_CDC','SEQUENCE',0),('ORDER_CDC','ORDER_ID',None)]
        for table,column,value in cases:
            with self.subTest(column=column,value=value):
                raw=fixture();raw['tables'][table][0][column]=value
                with self.assertRaises(e.ValidationError):e.evaluate(raw,{})
    def test_gold_retains_tenants_and_statuses_independent_of_report(self):
        raw=fixture()
        for table,rows in raw['tables'].items():rows+=[dict(r,TENANT_ID='B') for r in copy.deepcopy(rows)]
        raw['tables']['ORDER_CDC'][1]['STATUS']='pending'
        a=e.evaluate(raw,{});b=e.evaluate(raw,{'tenant':'B','persona_tenant':'B','status':'pending'})
        self.assertEqual(a['gold'],b['gold']);self.assertEqual(len(a['gold']),2)
        self.assertEqual(a['report'][0]['LINE_NET_CENTS'],2400);self.assertEqual(b['report'][0]['LINE_NET_CENTS'],2400)
    def test_half_open_dates_empty_and_product_literal_safety(self):
        raw=fixture()
        for params in ({'end_date':'2026-04-01'},{'start_date':'2026-04-02'},{'product':'OTHER'},{'product':"P1' OR '1'='1"}):
            with self.subTest(params=params):self.assertEqual(e.evaluate(raw,params)['report'],[])
        self.assertTrue(e.evaluate(raw,{'start_date':'2026-04-01','end_date':'2026-04-02'})['report'])
        empty=fixture();empty['tables']={t:[] for t in empty['tables']}
        self.assertEqual(e.evaluate(empty,{}),{'gold':[],'report':[]})
    def test_missing_defaults_distinct_from_explicit_null_or_unauthorized(self):
        self.assertTrue(e.evaluate(fixture(),{})['report'])
        for params in ({'tenant':None},{'tenant':'C'},{'persona_tenant':None},{'persona_tenant':'B'},{'authorized':False},{'authorized':None},{'authorized':1},{'status':'unknown'},{'status':None},{'start_date':'2026-04-05'},{'product':None}):
            with self.subTest(params=params),self.assertRaises(e.ValidationError):e.evaluate(fixture(),params)
    def test_original_staging_bytes_reused(self):
        for name in ('stg_orders','stg_order_lines'):
            self.assertEqual((e.ROOT/'dbt/models/staging'/f'{name}.sql').read_bytes(),(e.ROOT.parent/'input/repo/models/staging'/f'{name}.sql').read_bytes())
    def test_negative_control_removed_tenant_join_is_detected(self):
        raw=fixture()
        for table,rows in raw['tables'].items():rows+=[dict(r,TENANT_ID='B') for r in copy.deepcopy(rows)]
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp);shutil.copytree(e.ROOT/'dbt',target/'dbt')
            p=target/e.MODELS['fct_order_line_fulfillment']['path']
            text=p.read_text();self.assertIn('l.TENANT_ID = f.TENANT_ID and ',text)
            p.write_text(text.replace('l.TENANT_ID = f.TENANT_ID and ',''))
            with patch.object(e,'ROOT',target),self.assertRaises(e.ValidationError):e.evaluate(raw,{})
    def test_negative_control_double_discount_changes_independent_assertion(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp);shutil.copytree(e.ROOT/'dbt',target/'dbt')
            p=target/'dbt/models/staging/stg_order_lines.sql'
            p.write_text(p.read_text().replace('- DISCOUNT_CENTS as LINE_NET_CENTS','- 2 * DISCOUNT_CENTS as LINE_NET_CENTS'))
            with patch.object(e,'ROOT',target):actual=e.evaluate(fixture(),{})['gold'][0]['LINE_NET_CENTS']
            self.assertNotEqual(actual,2400)

if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(RetailTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    evidence={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'successful':result.wasSuccessful(),'basis':'Hand-derived microfixtures and metamorphic assertions; not root hidden oracle or business acceptance','negative_controls':['removed tenant join','double discount'],'diagnostics':[(str(t),msg) for t,msg in result.failures+result.errors]}
    (e.ROOT/'evidence').mkdir(parents=True, exist_ok=True)
    (e.ROOT/'evidence/author-tests.json').write_text(json.dumps(evidence,indent=2)+'\n')
    raise SystemExit(not result.wasSuccessful())
