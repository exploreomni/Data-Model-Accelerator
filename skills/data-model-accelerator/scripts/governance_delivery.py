"""One scoped projection for review UI, complete CSV exports and document appendices."""
import copy
import csv
import io
import json

from ae_common import hash_json

QUALIFICATION = ('Requested scope, governed names and public contract comparisons. '
    'Associations and host-recorded decisions are not native validation, parity or deployment approval.')


def project(state, selected=None):
    wf=state.get('workflow',{}); result={'schema_version':1,'qualification':QUALIFICATION}
    if wf.get('naming_governance'):
        from naming_governance import summarize, records
        from naming_artifacts import summary
        result['naming']=summarize(state,selected)
        result['identities']=[{k:r[k] for k in ('id','entity_id','source_id','original_name','target_name',
            'physical_alias','namespace','existing','layer','role','domain')} for r in records(state,selected)]
        result['naming_artifacts']=summary(state,selected)
    if wf.get('migration_inventory'):
        from migration_inventory import summarize
        result['inventory']=summarize(state,selected)
    if wf.get('consumer_contracts'):
        from consumer_contracts import summarize
        result['consumers']=summarize(state,selected)
        for row in result['consumers']['rows']:
            row.pop('evidence_refs',None)
            # Expressions remain in the candidate files, never duplicated here.
            for check in row['definition_checks']: check.pop('query_path',None)
    if (wf.get('review_assurance') or {}).get('coverage'):
        from mapping_coverage import detail_rows
        try:
            result['occurrences']=detail_rows(state,selected)
            result['occurrence_status']='recorded'
        except (OSError,ValueError,KeyError,TypeError):
            result['occurrences']=[]
            result['occurrence_status']='unavailable'
    if len(result)==2: return None
    result['snapshot_sha256']=hash_json(result)
    return result


def _value(value):
    if value is None: return 'Unknown'
    if type(value) in (list,dict): return json.dumps(value,ensure_ascii=False,sort_keys=True)
    return str(value)


def tables(data):
    """Complete rows. UI pagination must not become an export limit."""
    result=[]
    def add(name,headers,rows): result.append({'name':name,'headers':headers,'rows':rows})
    if 'naming' in data:
        statuses={r['id']:r for r in data['naming']['resources']}
        add('Governed names',['Resource ID','Model ID','Source identity','Original name','Target name','Physical alias',
            'Namespace','Existing','Layer','Role','Domain','Conformance','Gaps'],
            [[_value(r.get(k)) for k in ('id','entity_id','source_id','original_name','target_name','physical_alias',
              'namespace','existing','layer','role','domain')]+[statuses.get(r['id'],{}).get('status','Unknown'),
              _value(statuses.get(r['id'],{}).get('gaps',[]))] for r in data['identities']])
        add('Naming checks',['Code','Status','Model ID','Path'],
            [[_value(r.get(k)) for k in ('code','status','model_id','path')] for r in data.get('naming_artifacts',{}).get('findings',[])])
    if 'inventory' in data:
        add('Requested scope',['Domain','Source namespace','Native identity','Kind','Classification','Accounted',
            'Target model IDs','Remaining requirements','Register IDs'],
            [[d['domain_id'],r['source_namespace'],r['native_id'],r['kind'],r['classification'],str(r['accounted']),
              _value(r['model_ids']),_value(r['requirements']),_value(r['register_ids'])]
             for d in data['inventory']['domains'] for r in d['rows']])
        add('Requested counts',['Domain','Requested','Accounted','Unresolved','Replacement mapping','Upstream only',
            'Missing evidence','Missing target','Explicit exclusion'],
            [[d['domain_id']]+[str(d['counts'].get(k,0)) for k in ('requested','accounted','unresolved','replacement_mapping',
              'upstream_only','missing_evidence','missing_target','explicit_exclusion')] for d in data['inventory']['domains']])
        add('Inventory provenance',['Domain','Source namespace','Native identity','Register ID','Register kind','Row ID',
            'Occurrence ID','Evidence references','Omitted from latest import'],
            [[d['domain_id'],r['source_namespace'],r['native_id'],o['register_id'],o['register_kind'],o['row_id'],o['id'],
              str(o['evidence_reference_count']),str(o['omitted_from_latest_import'])]
             for d in data['inventory']['domains'] for r in d['rows'] for o in r['occurrences']])
    if 'consumers' in data:
        add('Consumer changes',['Contract ID','Source identity','Target model ID','Consumers','Review','Change',
            'Field','Before','After','Needs decision','Comparison fingerprint'],
            [[r['contract_id'],r['source_id'],r['entity_id'],_value(r['consumer_ids']),r['review_status'],f['kind'],
              _value(f['column']),_value(f['before']),_value(f['after']),str(f['requires_decision']),r['comparison_sha256']]
             for r in data['consumers']['rows'] for f in r['findings']])
    if 'occurrences' in data:
        add('Source occurrences',['Occurrence ID','Source asset','Name','Domain','Model IDs','Status','Rationale'],
            [[_value(r.get(k)) for k in ('id','asset','name','domain','model_ids','status','rationale')]
             for r in data['occurrences']])
    return result


def document_blocks(data, exclude=()):
    blocks=[{'type':'heading','level':2,'text':'Governed model review'},
            {'type':'paragraph','text':QUALIFICATION+'\nSnapshot: '+data['snapshot_sha256']}]
    if 'naming' in data:
        blocks.append({'type':'paragraph','text':'Selected naming policy: '+_value(data['naming'].get('policy'))})
    for table in tables(data):
        if table['name'] in exclude: continue
        blocks.extend([{'type':'heading','level':3,'text':table['name']},
                       {'type':'table','headers':table['headers'],'rows':table['rows']}])
    return blocks


def files(data):
    """Spreadsheet-safe CSV plus a concise readable index; no filesystem writes."""
    tabs=tables(data); output=[]
    for tab in tabs:
        stream=io.StringIO(newline=''); writer=csv.writer(stream)
        def safe(v):
            v=_value(v)
            return "'"+v if v.lstrip().startswith(('=','+','-','@')) or v.startswith(('\t','\r')) else v
        writer.writerow(tab['headers']); writer.writerows([[safe(v) for v in row] for row in tab['rows']])
        output.append({'path':'05_Migration/Governed_Review/'+tab['name'].lower().replace(' ','-')+'.csv',
                       'content':stream.getvalue().encode('utf-8')})
    from delivery_portal import _markdown_cell
    lines=['# Governed model review','',QUALIFICATION,'','Snapshot: `'+data['snapshot_sha256']+'`','',
           'Each CSV contains the complete selected scope. A recorded name or mapping is not validated behavior.','']
    if 'naming' in data:
        lines+=['Naming policy: '+_markdown_cell(_value(data['naming'].get('policy'))),'',
                'Naming status: '+data['naming']['status']+'. Physical collision checks cover only supplied identities.','']
    for tab,file in zip(tabs,output):
        lines.append('- ['+tab['name']+']('+file['path'].split('/')[-1]+'): '+str(len(tab['rows']))+' rows.')
    output.append({'path':'05_Migration/Governed_Review/README.md','content':('\n'.join(lines)+'\n').encode()})
    return output
