"""Curated Omni handoff rebuilt from exact candidate bytes, never acceptance."""
import copy
import csv
import hashlib
import html
import io
import json
import os
from pathlib import Path
import shutil

from omni_contract import _bounded, _load, canonical_hash, check_model, NAME
from omni_query_views import analyze_query_views

VERSION='omni-handoff-v1'
REVIEW_PATH='omni/SEMANTIC_REVIEW.json'
CONTEXT_PATH='omni-private/MODEL_CONTEXT.json'


def _need(ok,code):
    if not ok:raise ValueError(code)


def _bytes(value):return (json.dumps(value,sort_keys=True,indent=2,ensure_ascii=True,allow_nan=False)+'\n').encode()
def _sha(value):return hashlib.sha256(value).hexdigest()
def artifact_id(path):return 'omni-'+_sha(path.encode())[:20]


def _decisions(value):
    _need(type(value) is list and len(value)<=1000,'handoff.decisions')
    for decision in value:
        _need(type(decision) is dict and set(decision)=={'subject','placement','reason','status'} and
              all(type(v) is str and 0<len(v)<=4000 for v in decision.values()) and
              decision['placement'] in ('warehouse','semantic','workbook','unresolved') and
              decision['status'] in ('proposed','reviewed','unknown'),'handoff.decision')
    return copy.deepcopy(value)


def _graph(views,dependencies):
    """Connected semantic table blocks; no script, URLs, SQL or external assets."""
    names=sorted(views);positions={name:(40+(i%3)*390,80+(i//3)*210) for i,name in enumerate(names)}
    height=max(300,110+((len(names)+2)//3)*210)
    parts=['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="'+str(height)+'" viewBox="0 0 1200 '+str(height)+'">',
           '<rect width="1200" height="'+str(height)+'" fill="#f4f6f9"/>',
           '<text x="40" y="35" font-family="sans-serif" font-size="22" fill="#172e43">Omni semantic dependencies — declared, not live-qualified</text>']
    for edge in dependencies:
        left,right=edge['from'],edge['to']
        if left not in positions or right not in positions or left==right:continue
        x,y=positions[left];a,b=positions[right]
        parts.append('<path d="M '+str(x+175)+' '+str(y+140)+' L '+str(a+175)+' '+str(b)+'" fill="none" stroke="#6b529c" stroke-width="2"/>')
    for name in names:
        x,y=positions[name];obj=views[name]
        parts.append('<rect x="'+str(x)+'" y="'+str(y)+'" width="350" height="150" rx="8" fill="white" stroke="#8fa5b5"/>')
        labels=[name,obj['kind'],str(obj['dimensions'])+' dimensions · '+str(obj['measures'])+' measures']
        for i,label in enumerate(labels):parts.append('<text x="'+str(x+14)+'" y="'+str(y+28+i*26)+'" font-family="sans-serif" font-size="14" fill="#172e43">'+html.escape(label)+'</text>')
        parts.append('<text x="'+str(x+14)+'" y="'+str(y+123)+'" font-family="sans-serif" font-size="11" fill="#546779">See dictionary for all fields and source bindings.</text>')
    parts.append('</svg>');return ''.join(parts).encode()


def build_handoff(state,model_files,model_context,decisions=None):
    """Return artifacts + ready registration records; no disk/network mutations.

    Model context stays audit-only. Native files retain exact names/bytes. The
    reviewer JSON includes hashes and curated metadata, never source SQL bodies.
    All claims are local observations; imported metadata grants no authority.
    """
    from delivery_portal import source_fingerprint,context_fingerprint
    _bounded(state);_bounded(model_files);_bounded(model_context)
    _need(type(state) is dict and type(state.get('answers')) is dict,'handoff.state')
    target={key:state['answers'].get(key) for key in ('framework','warehouse')}
    _need(type(target['framework']) is str and bool(target['framework']),'handoff.framework_required')
    _need(source_fingerprint(state) is not None,'handoff.source_required')
    _need(target['warehouse']==model_context.get('warehouse') and state['answers'].get('semantic_target')=='omni','handoff.target')
    catalogue=state.get('inputs',{}).get('catalogue',{})
    if catalogue.get('sha256') is not None:
        _need(catalogue['sha256']==model_context.get('catalogue_sha256'),'handoff.catalogue_changed')
    _need(type(model_files) is dict and bool(model_files),'handoff.files')
    checked=check_model(model_files,model_context)
    _need(checked.get('candidate_sha256') is not None,'handoff.candidate')
    lineage=analyze_query_views(model_files,model_context)
    _need(bool(lineage['effective_views']),'handoff.inventory_unavailable')
    decisions=_decisions([] if decisions is None else decisions)
    dictionary=[];metrics=[];view_catalog={};dependencies=set();topics=[];unknowns=[]
    for scope,analysis in [(None,lineage)]+[(name,analyze_query_views(model_files,model_context,topic=name)) for name in sorted(checked['topic_scopes'])]:
        for name,definition in sorted(analysis['effective_views'].items()):
            kind='modeled_query' if 'query' in definition else 'sql_query' if 'sql' in definition else 'physical_or_inherited'
            if scope is None:view_catalog[name]={'kind':kind,'dimensions':len(definition.get('dimensions',{})),'measures':len(definition.get('measures',{}))}
            for category in ('dimensions','measures'):
                fields=definition.get(category,{})
                if type(fields) is not dict:continue
                for field,detail in sorted(fields.items()):
                    if type(detail) is not dict:continue
                    key=name+'.'+field;field_lineage=analysis['field_lineage'].get(key,{})
                    # Scoped rows are included only for actually reachable fields.
                    if scope is not None and name not in checked['topic_scopes'][scope].get('views',[]):continue
                    selected=checked['topic_scopes'].get(scope,{}).get('selections',{})
                    def field_selected(selection):
                        return any(ref==key or ref.startswith(key+'[') for ref in selected.get(selection,[]))
                    row={'id':key,'topic':scope,'kind':category[:-1],
                         'selected_for_query':field_selected('fields') if scope else None,
                         'selected_for_ai':field_selected('ai_fields') if scope else None,
                         'runtime_eligibility':'native_qualification_required',
                         'label':detail.get('label',field),'description':detail.get('description',''),
                         'definition_provenance':'declared_candidate','definition_sha256':canonical_hash(detail),
                         'datatype':field_lineage.get('datatype','unknown'),
                         'physical_columns':copy.deepcopy(field_lineage.get('physical_columns',[])),
                         'dependencies':list(field_lineage.get('semantic_fields',[])),
                         'has_local_filter':'filters' in detail,'aggregate_type':detail.get('aggregate_type'),
                         'native_verified':False}
                    dictionary.append(row)
                    if category=='measures':metrics.append({k:row[k] for k in ('id','topic','label','description','aggregate_type','has_local_filter','definition_provenance','definition_sha256','selected_for_query','selected_for_ai')})
                    if scope is None:
                        for dependency in row['dependencies']:
                            source=dependency.split('.')[0]
                            if source!=name:dependencies.add((source,name,'field_dependency',None))
        if scope is not None:
            detail=analysis['topic_definition'] or {}
            for name,definition in detail.get('views',{}).items():
                resolved=analysis['effective_views'].get(name,{})
                node=scope+'/'+name
                view_catalog[node]={'kind':'topic_view_alias_or_override','dimensions':len(resolved.get('dimensions',{})),
                                    'measures':len(resolved.get('measures',{}))}
                origin=analysis['binding_origins'].get(name)
                if origin and origin!=name:dependencies.add((origin,node,'inheritance',scope))
            for relation in detail.get('relationships',[]):
                if type(relation) is dict:
                    left,right=relation.get('join_from_view'),relation.get('join_to_view')
                    if type(left) is str and type(right) is str:
                        left=scope+'/'+left if left in detail.get('views',{}) else left
                        right=scope+'/'+right if right in detail.get('views',{}) else right
                        dependencies.add((left,right,'declared_join',scope))
            topics.append({'id':scope,'label':detail.get('label',scope),'description':detail.get('description',''),
                           'base_view':detail.get('base_view'),'scope':copy.deepcopy(checked['topic_scopes'][scope]),
                           'binding_origins':{v:analysis['binding_origins'].get(v) for v in checked['topic_scopes'][scope].get('views',[])},
                           'definition_provenance':'declared_candidate','native_verified':False})
    for name,descriptor in lineage['descriptors'].items():
        for output in descriptor['outputs'].values():
            for physical in output['physical_columns']:
                if physical['view']!=name:dependencies.add((physical['view'],name,'query_dependency',None))
    for path,text in model_files.items():
        if Path(path).name.removesuffix('.yaml').removesuffix('.yml')=='relationships':
            relations=_load(text)
            if type(relations) is list:
                for relation in relations:
                    if type(relation) is dict and all(type(relation.get(key)) is str for key in ('join_from_view','join_to_view')):
                        dependencies.add((relation['join_from_view'],relation['join_to_view'],'declared_join',None))
    for finding in checked['findings']+lineage['findings']:
        if finding not in unknowns:unknowns.append(copy.deepcopy(finding))
    pins={'source_fingerprint':source_fingerprint(state),'context_sha256':context_fingerprint(state),
          'target':target,'model_candidate_sha256':canonical_hash(model_files),'model_context_sha256':canonical_hash(model_context),
          'catalogue_sha256':model_context.get('catalogue_sha256')}
    native_records=[{'path':path,'artifact_id':artifact_id('omni/model/'+path),'sha256':_sha(text.encode())}
                    for path,text in sorted(model_files.items())]
    context_bytes=_bytes(model_context)
    summary={'schema_version':1,'kind':'omni_semantic_handoff','version':VERSION,'pins':pins,
             'inputs':{'model_files':native_records,'model_context':{'artifact_id':artifact_id(CONTEXT_PATH),'sha256':_sha(context_bytes)}},
             'dictionary':dictionary,'metrics':metrics,'topics':topics,'views':view_catalog,
             'dependencies':[{'from':a,'to':b,'kind':kind,'topic':scope} for a,b,kind,scope in sorted(dependencies,key=lambda v:tuple(x or '' for x in v))],
             'query_views':{name:{'kind':d['kind'],'outputs':list(d['outputs']),
                 'population_fields':d['population_fields'],'complete_population':d['complete_population'],
                 'truncation':d['truncation'],'implicit_whitelist_dependencies':d['implicit_whitelist_dependencies'],
                 'runtime_eligibility':d['runtime_eligibility']} for name,d in sorted(lineage['descriptors'].items())},
             'decisions':decisions,'unknowns':unknowns,'static_status':checked['status'],
             'native_status':'pending','business_status':'pending','deployment_status':'not_authorized',
             'acceptance_ready':False,'native_verified':False,
             'qualification':'Curated candidate only. Local structure and lineage do not prove native execution, security, business acceptance or deployment.',
             'warehouse_documentation':'Bronze, silver and gold documentation belongs to the warehouse handoff; this semantic catalog does not invent those layers.',
             'next_actions':['Review metric definitions, local filters, aliases, placement and unresolved questions.',
                             'Validate the exact model in the selected authorized development branch.',
                             'Execute frozen query, population, access and AI trials with qualified independent evidence.',
                             'Obtain business sign-off; request a separately authorized deployment route.']}
    summary['handoff_sha256']=canonical_hash(summary)
    artifacts={}
    def add(path,content,category,audiences):
        artifacts[path]={'content':content,'category':category,'audiences':audiences}
    add(REVIEW_PATH,_bytes(summary),'documentation',['reviewer','engineer'])
    stream=io.StringIO(newline='');writer=csv.writer(stream)
    writer.writerow(['topic','field','kind','label','description','datatype','aggregate_type','local_filter','query_selected','ai_awareness','provenance'])
    for row in dictionary:
        cells=[row.get(k) if row.get(k) is not None else '' for k in ('topic','id','kind','label','description','datatype','aggregate_type','has_local_filter','selected_for_query','selected_for_ai','definition_provenance')]
        writer.writerow(["'"+v if type(v) is str and v.lstrip().startswith(('=','+','-','@','\t','\r')) else v for v in cells])
    add('omni/SEMANTIC_DICTIONARY.csv',stream.getvalue().encode(),'dictionary',['reviewer','engineer'])
    add('omni/SEMANTIC_DEPENDENCIES.svg',_graph(view_catalog,summary['dependencies']),'diagrams',['reviewer','engineer'])
    runbook='# Omni candidate review\n\n'+summary['qualification']+'\n\n'+summary['warehouse_documentation']+'\n\n'
    runbook+='\n'.join(str(i+1)+'. '+step for i,step in enumerate(summary['next_actions']))+'\n\n'
    runbook+='Native filenames are under `omni/model/` in the artifact workspace; the portable package keeps them under `02_Implementation/`. Model context stays in the separate technical audit. No native queries or deployment were performed by this builder.\n'
    add('omni/OMNI_RUNBOOK.md',runbook.encode(),'documentation',['reviewer','engineer'])
    add(CONTEXT_PATH,context_bytes,'technical_audit',['audit'])
    for path,text in sorted(model_files.items()):add('omni/model/'+path,text.encode(),'implementation',['engineer'])
    records=[{'id':artifact_id(path),'path':path,'category':item['category'],'audiences':item['audiences'],
              'sha256':_sha(item['content'])} for path,item in artifacts.items()]
    return {'summary':summary,'artifacts':artifacts,'registrations':records,
            'review_reference':{'artifact_id':artifact_id(REVIEW_PATH),'sha256':_sha(artifacts[REVIEW_PATH]['content'])},
            'native_verified':False,'acceptance_ready':False}


def verify_handoff(summary,state,model_files,model_context):
    """Pure rebuild verifies exact input/projection integrity, not authority."""
    _need(type(summary) is dict,'handoff.summary')
    rebuilt=build_handoff(state,model_files,model_context,summary.get('decisions'))['summary']
    _need(summary==rebuilt,'handoff.stale_or_changed');return summary


def write_handoff(result,output):
    """Create a new private artifact directory; return registration/reference."""
    from ae_common import _path
    output=_path(output,must_exist=False)
    _need(not output.exists() and output.parent.is_dir(),'handoff.new_output_required')
    _need(type(result) is dict and type(result.get('artifacts')) is dict,'handoff.result')
    from delivery_portal import _relative,CATEGORIES,AUDIENCES
    registrations=result.get('registrations')
    _need(type(registrations) is list and len(registrations)==len(result['artifacts']),'handoff.registrations')
    expected=[];seen=set()
    for path,item in result['artifacts'].items():
        _relative(path)
        _need(path.casefold() not in seen and type(item) is dict and set(item)=={'content','category','audiences'}
              and type(item['content']) is bytes and item['category'] in CATEGORIES
              and type(item['audiences']) is list and set(item['audiences'])<=AUDIENCES,'handoff.artifact')
        seen.add(path.casefold())
        expected.append({'id':artifact_id(path),'path':path,'category':item['category'],'audiences':item['audiences'],'sha256':_sha(item['content'])})
    _need(registrations==expected and result.get('review_reference')=={'artifact_id':artifact_id(REVIEW_PATH),
          'sha256':_sha(result['artifacts'].get(REVIEW_PATH,{}).get('content',b''))},'handoff.registration_changed')
    _need(result['artifacts'].get(REVIEW_PATH,{}).get('content')==_bytes(result.get('summary')),'handoff.summary_changed')
    _need(result['artifacts'].get(CONTEXT_PATH,{}).get('category')=='technical_audit' and
          result['artifacts'][CONTEXT_PATH]['audiences']==['audit'],'handoff.private_context')
    output.mkdir(mode=0o700)
    try:
        for path,item in result['artifacts'].items():
            relative=Path(path);_need(not relative.is_absolute() and '..' not in relative.parts,'handoff.path')
            target=output/relative;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            descriptor=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(descriptor,'wb') as stream:stream.write(item['content'])
    except BaseException:
        shutil.rmtree(output);raise
    return {'artifacts':copy.deepcopy(result['registrations']),'omni':copy.deepcopy(result['review_reference'])}
