from pathlib import Path
import json
from evaluate import evaluate,mutation,InvalidInput
folder=Path(__file__).parent
raw=json.loads((folder.parent/'input/raw-data.json').read_text())
scenarios=[('default_a',{}),('tenant_b',{'tenant':'B'}),('product_p1',{'product':'P1'}),('pending_status',{'status':'pending'}),('empty_window',{'start_date':'2026-04-10','end_date':'2026-04-11'})]
valid=[]
for name,params in scenarios:valid.append({'name':name,'params':params,'expected':evaluate(raw,params)})
mutations=[]
for kind in ('duplicate_capture','late_fulfillment_correction','late_return_deletion'):
 changed=mutation(raw,kind);mutations.append({'name':kind,'params':{},'expected':evaluate(changed)})
invalid=[]
for kind,params in [('conflicting_superseded_version',{}),('orphan_fulfillment',{}),(None,{'tenant':'A','persona_tenant':'B'}),(None,{'authorized':None}),(None,{'status':'other'})]:
 try:evaluate(mutation(raw,kind) if kind else raw,params)
 except InvalidInput as error:invalid.append({'mutation':kind,'params':params,'expected_status':'failed','observed_error_type':type(error).__name__,'observed_error':str(error)})
 else:raise AssertionError('Negative scenario unexpectedly succeeded')
# Hand-derived checks independent of any source/target SQL.
base=valid[0]['expected'];assert len(base['gold'])==5 and len(base['report'])==3
line=next(r for r in base['gold'] if r['LINE_KEY']=='A|O1|L1')
assert (line['LINE_NET_CENTS'],line['FULFILLED_QUANTITY'],line['RETURNED_QUANTITY'],line['REFUND_CENTS'],line['RETAINED_REVENUE_CENTS'])==(2400,3,2,1500,900)
assert sum(r['LINE_NET_CENTS'] for r in base['report'])==8900
assert sum(r['REFUND_CENTS'] for r in base['report'])==3750
assert mutations[0]['expected']==base
assert len(valid[3]['expected']['report'])==1 and valid[3]['expected']['report'][0]['LINE_NET_CENTS']==1000
assert not valid[4]['expected']['report'] and valid[4]['expected']['gold']==base['gold']
expected={'schema_version':1,'kind':'private_independent_dbt_holdout_oracle','basis':'Stdlib raw-data/contract derivation, no source or target SQL read by evaluator. Input already frozen.','valid_scenarios':valid,'valid_mutations':mutations,'invalid_scenarios':invalid}
(folder/'expected.json').write_text(json.dumps(expected,indent=2)+'\n')
print(json.dumps({'gold_rows':len(base['gold']),'default_report_rows':len(base['report']),'valid_report_scenarios':len(valid),'valid_mutation_scenarios':len(mutations),'invalid_scenarios':len(invalid),'hand_checked':True},indent=2))
