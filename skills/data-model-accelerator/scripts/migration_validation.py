"""Private source -> warehouse -> Omni parity workflow; no source code execution.

The v1 comparator remains authoritative for comparisons. These helpers acquire
supplied result exports, retain exact private evidence, and emit row-free review
scorecards. Imported claims never authenticate native execution or approval.
"""
import argparse
import copy
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re

from ae_common import hash_json, load_json, require, _json_bytes
from delivery_assurance import validate_bindings
import migration_parity as parity
from omni_native import _private_file

MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 1000
LANES = {'source', 'warehouse', 'omni'}
GAP_STATUSES = {'pending', 'unsupported'}
FORMATS = {'json_rows', 'periscope_csv', 'bigquery_query_response', 'omni_json', 'interaction'}


def _bounded(value):
    require(len(_json_bytes(value)) <= MAX_BYTES, 'validation.byte_limit')


def _fields(value, required, optional=()):
    require(type(value) is dict and set(required) <= set(value) <= set(required) | set(optional),
            'validation.fields')


def _id(value):
    require(type(value) is str and parity.ID.fullmatch(value), 'validation.identifier')


def _label(value):
    require(type(value) is str and 0 < len(value) <= 240 and not any(ord(c)<32 for c in value),
            'validation.label')


def _gaps(items):
    require(type(items) is list and len(items) <= 100, 'validation.gaps')
    for item in items:
        _fields(item, {'code','status','reference'})
        _id(item['code']); _label(item['reference'])
        require(item['status'] in GAP_STATUSES, 'validation.gap_status')


def _plan(plan):
    # Structural validation of a draft is not approval and does not mutate it.
    shadow = copy.deepcopy(plan)
    if shadow.get('review') == {'status':'pending'}:
        shadow['review'] = {'status':'approved','reference':'internal-structure-check-only',
                           'plan_sha256':hash_json({k:v for k,v in shadow.items() if k!='review'})}
    parity.validate_plan(shadow)


def prepare(request):
    """Validate a plan and total crosswalk, retaining draft/unsupported work."""
    _bounded(request)
    _fields(request, {'schema_version','plan','crosswalk'}, {'baseline_document_sha256'})
    require(type(request['schema_version']) is int and request['schema_version']==1, 'validation.version')
    _plan(request['plan'])
    plan = request['plan']
    expected = {('tile', x) for x in plan['inventory']['data_tiles'] + plan['inventory']['text_tiles']} | {
        ('filter', x) for x in plan['inventory']['filter_ids']}
    require(type(request['crosswalk']) is list and len(request['crosswalk']) <= 1000, 'validation.crosswalk')
    found = set()
    for row in request['crosswalk']:
        _fields(row, {'subject_kind','subject_id','dashboard_id','dashboard_label','source_label',
                      'model_ids','topic_ids','status','gaps'})
        key = (row['subject_kind'], row['subject_id'])
        require(key in expected and key not in found, 'validation.crosswalk_inventory')
        found.add(key)
        for name in ('dashboard_id','subject_id'): _id(row[name])
        for name in ('dashboard_label','source_label'): _label(row[name])
        require(parity._ids(row['model_ids']) and parity._ids(row['topic_ids']), 'validation.target_ids')
        require(row['status'] in {'mapped','pending','unsupported'}, 'validation.mapping_status')
        if row['status']=='mapped' and row['subject_id'] in plan['inventory']['data_tiles']:
            require(bool(row['model_ids']), 'validation.models_missing')
            if plan['migration_scope']!='model_only': require(bool(row['topic_ids']), 'validation.topics_missing')
        _gaps(row['gaps'])
    require(found==expected, 'validation.crosswalk_incomplete')
    baseline_digest=request.get('baseline_document_sha256')
    require(baseline_digest is None or type(baseline_digest) is str and parity.SHA.fullmatch(baseline_digest), 'validation.baseline_document_hash')
    body = {'schema_version':1,'kind':'migration_validation_workflow','baseline_document_sha256':baseline_digest,
            'plan':copy.deepcopy(plan),'crosswalk':copy.deepcopy(request['crosswalk'])}
    return dict(body, workflow_sha256=hash_json(body))


def validate_workflow(workflow):
    _fields(workflow, {'schema_version','kind','plan','crosswalk','baseline_document_sha256','workflow_sha256'})
    require(workflow['kind']=='migration_validation_workflow', 'validation.workflow_kind')
    expected = prepare({k:workflow[k] for k in ('schema_version','plan','crosswalk','baseline_document_sha256')})
    require(expected==workflow, 'validation.workflow_changed')
    return workflow


def freeze(workflow, baseline, review_reference):
    """Record an explicitly supplied host review reference; never authenticate it."""
    validate_workflow(workflow); _label(review_reference)
    _validate_capture(workflow, baseline, 'source')
    capture = baseline['capture']
    require(capture['independent_of_candidate'] is True and
            set(capture['cases'])=={c['id'] for c in workflow['plan']['cases']}, 'validation.independent_complete_baseline')
    request = {k:copy.deepcopy(workflow[k]) for k in ('schema_version','plan','crosswalk')}
    request['baseline_document_sha256']=hash_json(baseline)
    plan = request['plan']; plan['baseline_sha256']=hash_json(capture)
    plan['review']={'status':'approved','reference':review_reference,
                    'plan_sha256':hash_json({k:v for k,v in plan.items() if k!='review'})}
    return prepare(request)


def _number(text):
    try:
        value = Decimal(text)
        require(value.is_finite(), 'validation.nonfinite')
        if value == value.to_integral_value(): return int(value)
        result = float(value)
        require(math.isfinite(result) and Decimal(str(result)) == value, 'validation.lossy_number_unsupported')
        return result
    except (InvalidOperation, ValueError, OverflowError):
        raise ValueError('validation.lossy_or_invalid_number') from None


def _scalar(value, kind, null_token=None):
    if value is None or null_token is not None and value == null_token: return None
    if kind == 'number': return _number(value)
    if kind == 'boolean':
        require(value in ('true','false'), 'validation.boolean_unsupported')
        return value=='true'
    return value


def decode_rows(format_name, payload, columns, *, null_token=None):
    """Decode finite exported result shapes. No HTTP requests or code execution."""
    _bounded(payload)
    if format_name in ('json_rows','omni_json'):
        rows = copy.deepcopy(payload)
    elif format_name=='periscope_csv':
        require(type(payload) is str and type(null_token) is str and null_token, 'validation.csv_null_token_required')
        reader = csv.DictReader(io.StringIO(payload))
        require(reader.fieldnames is not None and len(reader.fieldnames)==len(set(reader.fieldnames))
                and set(reader.fieldnames)==set(columns), 'validation.csv_schema')
        rows=[]
        for row in reader:
            require(None not in row and None not in row.values(), 'validation.csv_width')
            rows.append({k:_scalar(v,columns[k],null_token) for k,v in row.items()})
            require(len(rows)<=MAX_ROWS, 'validation.row_limit')
    elif format_name=='bigquery_query_response':
        require(type(payload) is dict and payload.get('jobComplete') is True and not payload.get('errors')
                and not payload.get('pageToken') and 'numDmlAffectedRows' not in payload
                and 'dmlStats' not in payload, 'validation.bigquery_incomplete_or_mutating')
        fields=payload.get('schema',{}).get('fields')
        require(type(fields) is list and len(fields)==len(columns), 'validation.bigquery_schema')
        names=[x.get('name') for x in fields]
        require(len(names)==len(set(names)) and set(names)==set(columns), 'validation.bigquery_columns')
        types={'number':{'INTEGER','INT64','FLOAT','FLOAT64','NUMERIC','BIGNUMERIC'},
               'boolean':{'BOOLEAN','BOOL'},'date':{'DATE'},'string':{'STRING'}}
        require(all(f.get('type') in types[columns[f['name']]] and f.get('mode','NULLABLE') in ('NULLABLE','REQUIRED')
                    for f in fields), 'validation.bigquery_type_unsupported')
        raw=payload.get('rows',[])
        require(type(raw) is list and str(len(raw))==payload.get('totalRows'), 'validation.bigquery_truncated')
        rows=[]
        for row in raw:
            require(type(row) is dict and set(row)=={'f'} and type(row['f']) is list and len(row['f'])==len(names), 'validation.bigquery_row')
            require(all(type(v) is dict and set(v)=={'v'} for v in row['f']), 'validation.bigquery_cell')
            rows.append({name:_scalar(value['v'], columns[name]) for name,value in zip(names,row['f'])})
    else: raise ValueError('validation.format_unsupported')
    require(type(rows) is list and len(rows)<=MAX_ROWS, 'validation.row_limit')
    require(all(type(row) is dict and set(row)==set(columns) for row in rows), 'validation.row_schema')
    return rows


def import_capture(workflow, request):
    """Import exact source/warehouse/Omni exports. Returned rows are PRIVATE."""
    validate_workflow(workflow); _bounded(request)
    _fields(request, {'schema_version','origin','provenance','independent_of_candidate','reference','cases'})
    require(type(request['schema_version']) is int and request['schema_version']==1 and request['origin'] in LANES, 'validation.capture_version')
    require(type(request['cases']) is list and len(request['cases'])<=1000, 'validation.capture_cases')
    capture={k:copy.deepcopy(request[k]) for k in ('schema_version','origin','provenance','independent_of_candidate','reference')}
    capture.update(kind='migration_observations', cases={})
    cases={c['id']:c for c in workflow['plan']['cases']}; evidence={}
    parity._capture(capture,request['origin'],set(cases))
    if request['origin']=='source': require(request['independent_of_candidate'] is True, 'validation.own_oracle')
    for item in request['cases']:
        _fields(item, {'case_id','format','payload','context','reference','captured_at','gaps'},
                {'query','columns','metrics','metrics_reference','truncated','null_token','request_limit','column_map'})
        identity=item['case_id']
        require(identity in cases and identity not in capture['cases'] and item['format'] in FORMATS, 'validation.capture_identity')
        case=cases[identity]; _label(item['reference']); _gaps(item['gaps'])
        try: stamp=datetime.fromisoformat(item['captured_at'].replace('Z','+00:00'))
        except (ValueError,AttributeError): raise ValueError('validation.timestamp') from None
        require(stamp.tzinfo is not None, 'validation.timestamp')
        context=copy.deepcopy(case['context'])
        if case['kind']=='data':
            require(item['format']!='interaction' and item.get('columns')==case['columns'] and type(item.get('query')) in (dict,str), 'validation.query_schema')
            context['query_sha256']=hash_json(item['query'])
            require(context['query_sha256']==case['queries'][request['origin']], 'validation.query_changed')
            require(type(item.get('truncated')) is bool and item['truncated'] is False, 'validation.truncated_unsupported')
            _label(item.get('metrics_reference'))
            require(type(item.get('metrics')) is dict and set(item['metrics'])==set(case['expected_metrics']), 'validation.metrics_required')
            if item['format']=='periscope_csv': require(request['origin']=='source','validation.csv_origin')
            if item['format']=='bigquery_query_response': require(request['origin']=='warehouse','validation.bigquery_origin')
            if item['format']=='omni_json':
                require(request['origin']=='omni' and type(item.get('request_limit')) is int
                        and 1<=item['request_limit']<=MAX_ROWS, 'validation.omni_limit')
                query=item['query']
                require(type(query) is dict and query.get('resultType')=='json' and query.get('formatResults') is False
                        and query.get('query',{}).get('limit')==item['request_limit'], 'validation.omni_request')
            column_map=item.get('column_map',{name:name for name in case['columns']})
            require(type(column_map) is dict and len(column_map)==len(case['columns']) and
                    all(type(k) is str and k for k in column_map) and set(column_map.values())==set(case['columns']), 'validation.column_map')
            if item['format']=='omni_json':
                require(set(item['query']['query'].get('fields',[]))==set(column_map), 'validation.omni_fields')
            native_columns={name:case['columns'][canonical] for name,canonical in column_map.items()}
            decoded=decode_rows(item['format'],item['payload'],native_columns,null_token=item.get('null_token'))
            rows=[{column_map[name]:value for name,value in row.items()} for row in decoded]
            if item['format']=='omni_json': require(len(rows)<item['request_limit'], 'validation.omni_limit_reached')
            observation={'context':item['context'],'rows':rows,'metrics':item['metrics'],'truncated':False}
            # Validate row types/grain separately from invariant agreement: mismatches
            # must remain reviewable failures, never be overwritten with expectations.
            shadow=dict(case,expected_metrics=item['metrics'])
            parity._rows(shadow, observation)
        else:
            require(item['format']=='interaction', 'validation.interaction_format')
            require(not set(item)&{'query','columns','metrics','metrics_reference','truncated','null_token','request_limit','column_map'}, 'validation.interaction_fields')
            observation={'context':item['context'],'value':item['payload']}
        require(item['context']==context, 'validation.context_changed')
        capture['cases'][identity]=copy.deepcopy(observation)
        # Retain the bounded original export privately so reload can replay the
        # exact format/schema/limit rules, including CSV and API response shape.
        evidence[identity]=copy.deepcopy(item)
        evidence[identity]['payload_sha256']=hash_json(item['payload'])
    body={'schema_version':1,'kind':'migration_validation_capture','capture':capture,'evidence':evidence,
          'evidence_authenticated':False,'native_verified':False}
    _bounded(body)
    return dict(body, capture_document_sha256=hash_json(body))


def _validate_capture(workflow, value, origin):
    _bounded(value)
    _fields(value, {'schema_version','kind','capture','evidence','native_verified','evidence_authenticated','capture_document_sha256'})
    require(value['kind']=='migration_validation_capture' and value['schema_version']==1 and
            value['native_verified'] is False and value['evidence_authenticated'] is False and
            value['capture_document_sha256']==hash_json({k:v for k,v in value.items() if k!='capture_document_sha256'}), 'validation.capture_changed')
    ids={c['id'] for c in workflow['plan']['cases']}
    parity._capture(value['capture'],origin,ids)
    require(type(value['evidence']) is dict and set(value['evidence'])==set(value['capture']['cases']), 'validation.evidence_inventory')
    # Re-run the single import validation path rather than maintaining a weaker
    # second validator. A checksum alone does not make a supplied capture valid.
    request={key:copy.deepcopy(value['capture'][key]) for key in
             ('schema_version','origin','provenance','independent_of_candidate','reference')}
    request['cases']=[]
    for identity,ev in value['evidence'].items():
        require(type(ev) is dict and ev.get('case_id')==identity and 'payload' in ev
                and 'payload_sha256' in ev, 'validation.export_payload_required')
        obs=value['capture']['cases'][identity]
        if 'metrics' in ev or 'metrics' in obs:
            require(ev.get('metrics')==obs.get('metrics'), 'validation.evidence_metrics')
        request['cases'].append({key:copy.deepcopy(item) for key,item in ev.items() if key!='payload_sha256'})
    replayed=import_capture(workflow,request)
    require(replayed==value, 'validation.capture_replay_mismatch')
    return value['capture']


def evaluate(workflow, baseline=None, warehouse=None, omni=None, *, current_bindings=None):
    """Produce only declared crosswalk metadata, counts, hashes and safe issue codes."""
    validate_workflow(workflow); plan=workflow['plan']; captures={}
    for lane,value in (('source',baseline),('warehouse',warehouse),('omni',omni)):
        captures[lane]=_validate_capture(workflow,value,lane) if value is not None else None
    if current_bindings is not None: validate_bindings(current_bindings)
    stale=current_bindings is not None and current_bindings!=plan['bindings']
    baseline_changed=baseline is not None and workflow['baseline_document_sha256'] is not None and workflow['baseline_document_sha256']!=hash_json(baseline)
    ready=baseline is not None and workflow['baseline_document_sha256'] is not None and not baseline_changed and plan['review'].get('status')=='approved'
    if ready:
        report=parity.evaluate(plan,captures['source'],captures['warehouse'],captures['omni'])
        comparisons=report['cases']
    else:
        comparisons=[{'case_index':i,'status':'pending','row_counts':{},'issues':[{'code':'independent_baseline_or_plan_review_missing','status':'pending'}]} for i in range(len(plan['cases']))]
    outcomes=[]
    for row in workflow['crosswalk']:
        relevant=[(case,comparisons[i]) for i,case in enumerate(plan['cases']) if (case['subject_kind'],case['subject_id'])==(row['subject_kind'],row['subject_id'])]
        issues=[{'code':g['code'],'status':g['status']} for g in row['gaps']]
        for case,check in relevant:
            issues.extend(check['issues'])
            lanes={'source','omni'} if case['kind']=='interaction' else {'source','warehouse'} | ({'omni'} if plan['migration_scope']!='model_only' else set())
            for lane,value in (('source',baseline),('warehouse',warehouse),('omni',omni)):
                if lane in lanes and value is not None:
                    issues.extend({'lane':lane,'code':g['code'],'status':g['status']} for g in value['evidence'].get(case['id'],{}).get('gaps',[]))
        if baseline_changed: issues.append({'code':'frozen_baseline_document_changed','status':'failed'})
        if stale: issues.append({'code':'input_bindings_changed','status':'failed'})
        if current_bindings is None: issues.append({'code':'current_bindings_unverified','status':'pending'})
        if row['status']!='mapped': issues.append({'code':'mapping_'+row['status'],'status':row['status']})
        if not relevant: issues.append({'code':'interaction_not_assessed','status':'unsupported'})
        statuses={i['status'] for i in issues}
        status='fail' if 'failed' in statuses else 'unsupported' if 'unsupported' in statuses else 'pending' if statuses else 'pass'
        outcomes.append({k:copy.deepcopy(row[k]) for k in ('subject_kind','subject_id','dashboard_id','dashboard_label','source_label','model_ids','topic_ids')} |
                        {'status':status,'required':bool(relevant),'stale':stale,'case_count':len(relevant),'row_counts':[c['row_counts'] for _,c in relevant],'issues':issues})
    counts={s:sum(x['status']==s for x in outcomes) for s in ('pass','fail','pending','unsupported')}
    overall=next((s for s in ('fail','unsupported','pending') if any(x['status']==s and x['required'] for x in outcomes)),'pass')
    return {'schema_version':1,'kind':'migration_validation_scorecard','status':overall,'counts':counts,
            'workflow_sha256':workflow['workflow_sha256'],'bindings':copy.deepcopy(plan['bindings']),
            'current_bindings_verified':current_bindings is not None,'stale':stale,'crosswalk':outcomes,
            'capture_sha256':{k:hash_json(v) if v is not None else None for k,v in captures.items()},
            'native_verified':False,'evidence_authenticated':False,'acceptance_ready':False,
            'assurance':'Pass means local consistency of supplied observations only. Independent observer, native execution, security, rendered behavior and business approval remain separate.'}


def render_markdown(report):
    def cell(text): return str(text).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('|','\\|').replace('\n',' ')
    lines=['Migration parity: '+report['status'],'',report['assurance'],'',
           '| Dashboard | Chart / filter | Warehouse models | Omni topics | Result | Evidence gaps |',
           '|---|---|---|---|---|---|']
    for row in report['crosswalk']:
        lines.append('| '+' | '.join(cell(x) for x in (row['dashboard_label'],row['source_label'],', '.join(row['model_ids']) or 'Pending',
                     ', '.join(row['topic_ids']) or 'Not selected / pending',row['status'],', '.join(sorted({i['code'] for i in row['issues']})) or 'None in local comparison'))+' |')
    return '\n'.join(lines)+'\n'


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('plan','capture','freeze','evaluate'))
    parser.add_argument('--request',type=Path);parser.add_argument('--workflow',type=Path)
    parser.add_argument('--baseline',type=Path);parser.add_argument('--warehouse',type=Path);parser.add_argument('--omni',type=Path)
    parser.add_argument('--bindings',type=Path);parser.add_argument('--review-reference');parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        workflow=load_json(args.workflow,MAX_BYTES) if args.workflow else None
        if args.action=='plan': result=prepare(load_json(args.request,MAX_BYTES))
        elif args.action=='capture': result=import_capture(workflow,load_json(args.request,MAX_BYTES))
        elif args.action=='freeze': result=freeze(workflow,load_json(args.baseline,MAX_BYTES),args.review_reference)
        else:
            result=evaluate(workflow,*(load_json(p,MAX_BYTES) if p else None for p in (args.baseline,args.warehouse,args.omni)),
                            current_bindings=load_json(args.bindings) if args.bindings else None)
            result['markdown']=render_markdown(result)
        _private_file(args.output,result)
        print(json.dumps({'status':result.get('status','recorded'),'native_verified':False}))
        return 1 if result.get('status') in ('fail','pending','unsupported') else 0
    except (ValueError,TypeError,KeyError,OSError,AttributeError,RecursionError,OverflowError):
        print(json.dumps({'status':'blocked','code':'migration_validation.invalid_input'})); return 1


if __name__=='__main__': raise SystemExit(main())
