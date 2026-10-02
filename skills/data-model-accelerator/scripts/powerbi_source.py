"""Bounded, read-only PBIP/TMSL/enhanced-PBIR inventory; never executes M/DAX/SQL."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import unicodedata

MAX_FILE_BYTES=2_000_000
MAX_FILES=200
MAX_TOTAL_BYTES=10_000_000
SCHEMAS=Path(__file__).with_name('schemas')/'powerbi'
SCHEMA_PROVENANCE_SHA256='939042215adc168995a46a57b7276bfd58ab5fd00254e97245f75c2abe025bd6'
SCHEMA_BASE='https://developer.microsoft.com/json-schemas/'
M_STRING=r'"(?:[^"]|"")*"'


def sha(data): return hashlib.sha256(data).hexdigest()
def unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError('Duplicate JSON key: '+key)
        result[key]=value
    return result

def read_json(data):
    if len(data)>MAX_FILE_BYTES: raise ValueError('JSON exceeds bounded file size')
    obj=json.loads(data.decode('utf-8'),object_pairs_hook=unique_object,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('Nonfinite JSON number')))
    if not isinstance(obj,dict): raise ValueError('Native JSON root must be an object')
    return obj

def expression(value):
    if isinstance(value,str) and value.strip(): return value
    if isinstance(value,list) and value and all(isinstance(v,str) for v in value): return '\n'.join(value)
    raise ValueError('Missing or malformed native expression')

def confined(root,parent,relative):
    if not isinstance(relative,str) or not relative or '\\' in relative or ':' in relative or '\x00' in relative or PurePosixPath(relative).is_absolute():
        raise ValueError('Reference must be a confined relative POSIX path')
    candidate=parent/relative
    # Check lexical ancestors before resolving so even an internal symlink is rejected.
    for component in (candidate,*candidate.parents):
        if component.is_symlink(): raise ValueError('Symlink path reference is unsupported')
        if component==root: break
    target=candidate.resolve()
    if not target.is_relative_to(root): raise ValueError('Path reference escapes repository')
    if not target.exists(): raise ValueError('Referenced path is missing: '+relative)
    return target

def schema_registry():
    from referencing import Registry,Resource
    if sha((SCHEMAS/'provenance.json').read_bytes())!=SCHEMA_PROVENANCE_SHA256: raise ValueError('Pinned schema provenance changed')
    provenance=read_json((SCHEMAS/'provenance.json').read_bytes());resources={}
    for relative,entry in provenance['files'].items():
        path=SCHEMAS/relative
        if path.is_symlink() or sha(path.read_bytes())!=entry['sha256']: raise ValueError('Pinned Microsoft schema hash mismatch: '+relative)
        value=read_json(path.read_bytes());resources[SCHEMA_BASE+relative]=Resource.from_contents(value)
    # Retrieval URI matters: Microsoft embedded schemas can declare a non-embedded $id.
    return Registry().with_resources(resources.items()),resources

def field_reference(value,aliases=None):
    if not isinstance(value,dict) or len(value)!=1 or next(iter(value)) not in ('Column','Measure'): raise ValueError('Unsupported native field expression')
    native_kind=next(iter(value));body=value[native_kind]
    if not isinstance(body,dict) or set(body)!={'Expression','Property'}: raise ValueError('Unsupported field properties')
    ref=body['Expression']
    if not isinstance(ref,dict) or set(ref)!={'SourceRef'}: raise ValueError('Unsupported field source expression')
    source=ref['SourceRef']
    if set(source)=={'Entity'}: table=source['Entity']
    elif set(source)=={'Source'} and aliases is not None and source['Source'] in aliases: table=aliases[source['Source']]
    else: raise ValueError('Unresolved or unsupported field source')
    if not isinstance(table,str) or not isinstance(body['Property'],str): raise ValueError('Malformed field identity')
    return {'kind':native_kind.lower(),'table':table,'property':body['Property']}

def literal(value):
    if not isinstance(value,dict) or set(value)!={'Literal'} or set(value['Literal'])!={'Value'}: raise ValueError('Filter value must be a native literal')
    raw=value['Literal']['Value']
    if not isinstance(raw,str): raise ValueError('Malformed native literal')
    if re.fullmatch(r"datetime'\d{4}-\d{2}-\d{2}T00:00:00'",raw): return raw[9:19]
    if re.fullmatch(r'-?\d+L',raw): return int(raw[:-1])
    if re.fullmatch(r"'(?:[^']|'')*'",raw): return raw[1:-1].replace("''", "'")
    if raw in ('true','false'): return raw=='true'
    raise ValueError('Unsupported native filter literal: '+raw)

def condition_filters(condition,aliases):
    if not isinstance(condition,dict) or len(condition)!=1: raise ValueError('Malformed filter condition')
    if 'And' in condition:
        body=condition['And']
        if set(body)!={'Left','Right'}: raise ValueError('Unsupported And condition')
        return condition_filters(body['Left'],aliases)+condition_filters(body['Right'],aliases)
    if 'Comparison' in condition:
        body=condition['Comparison']
        if set(body)!={'ComparisonKind','Left','Right'} or type(body['ComparisonKind']) is not int or body['ComparisonKind'] not in (0,1,2,3,4): raise ValueError('Unsupported comparison')
        ref=field_reference(body['Left'],aliases)
        return [{**ref,'operator':{0:'eq',1:'gt',2:'gte',3:'lt',4:'lte'}[body['ComparisonKind']],'values':[literal(body['Right'])]}]
    if 'In' in condition:
        body=condition['In']
        if set(body)!={'Expressions','Values'} or not isinstance(body['Expressions'],list) or len(body['Expressions'])!=1: raise ValueError('Only one-column literal In filters are supported')
        ref=field_reference(body['Expressions'][0],aliases);values=[]
        if not isinstance(body['Values'],list): raise ValueError('Malformed In values')
        for value in body['Values']:
            if not isinstance(value,list) or len(value)!=1: raise ValueError('Unsupported tuple filter')
            values.append(literal(value[0]))
        if len({(type(x).__name__,str(x)) for x in values})!=len(values): raise ValueError('Duplicate categorical filter value')
        return [{**ref,'operator':'in','values':values}]
    raise ValueError('Unsupported filter condition: '+next(iter(condition)))

def m_metadata(text):
    """Recognize literal Snowflake native-query evidence, without evaluating M."""
    connection=re.search(r'Snowflake\.Databases\(\s*('+M_STRING+r')\s*,\s*('+M_STRING+r')\s*\)\s*\{\s*\[\s*Name\s*=\s*('+M_STRING+r')\s*,\s*Kind\s*=\s*"Database"\s*\]\s*\}\s*\[Data\]',text)
    if text.strip().startswith('#table('):
        return {'kind':'inline_table','expression':text,'native_sql':None,'connection':None,'sql_analysis':None}
    native=re.search(r'Value\.NativeQuery\(.*?\[Data\]\s*,\s*('+M_STRING+r')\s*,\s*null\s*,\s*\[EnableFolding\s*=\s*true\]\s*\)',text,re.S)
    if not connection or not native or text.count('Value.NativeQuery')!=1 or text.count('Snowflake.Databases')!=1:
        raise ValueError('Dynamic/unbound or unsupported M native-query connection; no M execution attempted')
    decode=lambda s:s[1:-1].replace('""','"').replace('#(lf)','\n').replace('#(cr)','\r').replace('#(tab)','\t')
    server,warehouse,catalog=map(decode,connection.groups());sql=decode(native.group(1))
    import sqlglot
    from sqlglot import exp
    from sqlglot.errors import ErrorLevel
    from sqlglot.optimizer.scope import traverse_scope,Scope
    trees=sqlglot.parse(sql,read='snowflake',error_level=ErrorLevel.RAISE)
    if len(trees)!=1 or not isinstance(trees[0],exp.Query): raise ValueError('Native query must be one read-only SQL query')
    tree=trees[0];physical=set()
    for scope in traverse_scope(tree):
        for _,(_,item) in scope.selected_sources.items():
            if isinstance(item,Scope): continue
            if not isinstance(item,exp.Table) or len(item.parts)!=3: raise ValueError('Unbound native SQL physical source')
            physical.add('.'.join(p.sql(dialect='snowflake') for p in item.parts))
    return {'kind':'snowflake_native_query','expression':text,'native_sql':sql,
            'connection':{'platform_instance':server,'warehouse':warehouse,'catalog':catalog,'connector':'Snowflake.Databases','declared_only':True},
            'sql_analysis':{'physical_refs':sorted(physical),'ctes':[{'name':x.alias,'sql':x.sql(dialect='snowflake')} for x in tree.find_all(exp.CTE)],
              'joins':[x.sql(dialect='snowflake') for x in tree.find_all(exp.Join)],'filters':[x.sql(dialect='snowflake') for x in tree.find_all(exp.Where)],
              'projections':[{'name':x.alias_or_name,'sql':x.sql(dialect='snowflake')} for x in tree.expressions]}}

def inspect_repo(repo):
    root=Path(repo).absolute()
    result={'schema_version':1,'kind':'powerbi_source_inventory','repo':str(root),'assets':[],'projects':[],'model':None,'model_path':None,'tables':[],
            'columns':[],'measures':[],'partitions':[],'relationships':[],'roles':[],'pages':[],'visuals':[],'filters':[],'report_defaults':{},
            'report_default_evidence':{},'edges':[],'gaps':[],'schema_validation':[],'native_runtime_validated':False}
    def gap(kind,message,path=None,severity='error'):
        result['gaps'].append({'kind':kind,'message':str(message),'path':path,'severity':severity})
    def finish():
        result['counts']={key:len(result[key]) for key in ('assets','projects','tables','columns','measures','partitions','relationships','roles','pages','visuals','filters','edges')}
        result['counts'].update(errors=sum(g['severity']=='error' for g in result['gaps']),review_gaps=sum(g['severity']=='review' for g in result['gaps']),schema_validated_files=sum(v['valid'] for v in result['schema_validation']))
        result['static_coverage_complete']=result['counts']['errors']==0
        canonical=json.dumps(result['assets'],sort_keys=True,separators=(',',':')).encode()
        result['source_snapshot_sha256']=sha(canonical)
        result['source_snapshot_basis']='SHA-256 of UTF-8 canonical JSON assets array sorted by repository path, sort_keys=True, separators=(comma,colon); not proof of absent-file completeness.'
        return result
    if not root.is_dir() or root.is_symlink():
        gap('unsafe_repository','Repository root must be a regular directory, not a symlink');return finish()
    root=root.resolve();documents={};all_paths={};total=0;seen=set()
    for directory,dirs,files in os.walk(root,followlinks=False):
        for name in list(dirs):
            path=Path(directory)/name
            if path.is_symlink():gap('symlink_asset','Directory symlink is unsupported',str(path.relative_to(root)));dirs.remove(name)
        for name in sorted(files):
            path=Path(directory)/name;relative=path.relative_to(root).as_posix()
            if path.is_symlink() or not path.is_file():gap('symlink_asset','Nonregular source asset is unsupported',relative);continue
            identity=unicodedata.normalize('NFC',relative).casefold()
            if identity in seen:gap('path_collision','Case/Unicode-colliding asset identity',relative);continue
            seen.add(identity)
            size=path.stat().st_size;total+=size
            if size>MAX_FILE_BYTES or total>MAX_TOTAL_BYTES or len(all_paths)>=MAX_FILES:gap('inventory_limit','Repository exceeds bounded inventory limits',relative);continue
            data=path.read_bytes();result['assets'].append({'path':relative,'sha256':sha(data),'bytes':len(data)});all_paths[relative]=path
            if path.suffix.lower() in ('.json','.pbip','.pbir','.pbism','.bim'):
                try:documents[relative]=read_json(data)
                except (ValueError,UnicodeError) as error:gap('json_invalid',error,relative)
            elif relative!='adjustments.csv':gap('unsupported_asset','Opaque or unsupported asset; PBIX/TMDL/other definitions require separate tooling',relative)
    result['assets'].sort(key=lambda a:a['path'])
    try:registry,resources=schema_registry()
    except (ImportError,ValueError,OSError) as error:gap('schema_validation_unavailable',error);return finish()
    from jsonschema import Draft7Validator
    for relative,obj in documents.items():
        if relative.endswith('model.bim'):continue
        uri=obj.get('$schema')
        if not isinstance(uri,str) or uri not in resources:gap('unknown_schema','Source schema is missing or not in pinned Microsoft bundle',relative);continue
        try:
            errors=list(Draft7Validator(resources[uri].contents,registry=registry).iter_errors(obj))
            result['schema_validation'].append({'path':relative,'schema':uri,'valid':not errors,'errors':[e.message for e in errors],'scope':'Official Microsoft JSON syntax only'})
            for error in errors:gap('schema_invalid',error.message,relative)
        except Exception as error:gap('schema_validation_unavailable',error,relative)
    consumed=set()
    def doc(path):
        relative=path.relative_to(root).as_posix();consumed.add(relative)
        if relative not in documents:raise ValueError('Missing/invalid native JSON artifact: '+relative)
        return documents[relative],relative
    def distinct(values,label):
        names=[v.get('name') for v in values]
        if any(not isinstance(n,str) or not n for n in names) or len({n.casefold() for n in names})!=len(names):raise ValueError('Duplicate/missing '+label+' identity')
    try:
        pbips=[p for p in all_paths.values() if p.suffix.lower()=='.pbip']
        if len(pbips)!=1:raise ValueError('Exactly one PBIP entrypoint is supported')
        project,project_path=doc(pbips[0]);artifacts=project.get('artifacts',[])
        if len(artifacts)!=1:raise ValueError('Exactly one PBIP report pointer is supported')
        report_dir=confined(root,pbips[0].parent,artifacts[0]['report']['path'])
        report_def,report_def_path=doc(report_dir/'definition.pbir')
        reference=report_def.get('datasetReference',{})
        if set(reference)!={'byPath'} or set(reference['byPath'])!={'path'}:raise ValueError('Remote/ambiguous report model references are unsupported')
        model_dir=confined(root,report_dir,reference['byPath']['path'])
        model_def,model_def_path=doc(model_dir/'definition.pbism')
        database,model_path=doc(model_dir/'model.bim');result['model']=database;result['model_path']=model_path
        result['projects'].append({'id':project_path,'path':project_path,'native':project,'report_path':report_dir.relative_to(root).as_posix(),'model_path':model_path,
            'dataset_reference':reference,'definition_pbir_path':report_def_path,'definition_pbism_path':model_def_path})
        if set(database)-{'name','compatibilityLevel','model','description','id'} or not isinstance(database.get('name'),str):raise ValueError('Unsupported/malformed TMSL database properties')
        model=database['model']
        if set(model)-{'name','culture','defaultPowerBIDataSourceVersion','tables','relationships','roles','annotations'}:gap('unsupported_model_behavior','Uninterpreted TMSL model properties require review',model_path)
        tables=model.get('tables',[]);distinct(tables,'table');columns={};measures={};tags=set()
        for table in tables:
            name=table['name'];tid=model_path+'/table:'+name
            result['tables'].append({'id':tid,'name':name,'lineageTag':table.get('lineageTag'),'native':table})
            if set(table)-{'name','lineageTag','columns','measures','partitions','description','annotations','isHidden'}:gap('unsupported_table_behavior','Uninterpreted table properties',model_path)
            for kind in ('columns','measures'):
                values=table.get(kind,[]);distinct(values,kind)
                for item in values:
                    item_name=item['name'];key=(name,item_name);record={'id':tid+'/'+kind[:-1]+':'+item_name,'table':name,'name':item_name,'native':item,'lineageTag':item.get('lineageTag')}
                    tag=item.get('lineageTag')
                    if tag and tag in tags:raise ValueError('Duplicate native lineageTag')
                    if tag:tags.add(tag)
                    if kind=='columns':
                        columns[key]=record;record.update(data_type=item.get('dataType'),source_column=item.get('sourceColumn'),expression=item.get('expression'))
                        if item.get('type')=='calculated':record['expression']=expression(item.get('expression'))
                        elif not isinstance(item.get('sourceColumn'),str):raise ValueError('Source column mapping is missing')
                    else:
                        if item_name.casefold() in {m.casefold() for m in measures}:raise ValueError('Duplicate model measure identity')
                        measures[item_name]=record;record['expression']=expression(item.get('expression'))
                    result[kind].append(record)
            if {c['name'].casefold() for c in table.get('columns',[])} & {m['name'].casefold() for m in table.get('measures',[])}:raise ValueError('Same-table column/measure identity collision')
            partitions=table.get('partitions',[]);distinct(partitions,'partition')
            if len(partitions)!=1:gap('unsupported_partition_inventory','Exactly one partition per table is supported',model_path)
            for partition in partitions:
                text=expression(partition.get('source',{}).get('expression'))
                record={'id':tid+'/partition:'+partition['name'],'table':name,'name':partition['name'],'mode':partition.get('mode'),'expression':text,'native':partition,'path':model_path}
                result['partitions'].append(record)
                if partition.get('mode')!='import' or partition.get('source',{}).get('type')!='m':gap('unsupported_partition_mode','Only Import M partitions are statically profiled',model_path)
                try:
                    record.update(m_metadata(text))
                    for physical in (record.get('sql_analysis') or {}).get('physical_refs',[]):result['edges'].append({'from':'warehouse:'+physical,'to':record['id'],'kind':'native_sql_read','evidence_path':model_path})
                except (ValueError,ImportError) as error:gap('unbound_m',error,model_path)
        for table in tables:
            tag=table.get('lineageTag')
            if tag and tag in tags:raise ValueError('Duplicate native lineageTag')
            if tag:tags.add(tag)
        def bind(ref):
            if ref['kind']=='column' and (ref['table'],ref['property']) in columns:return columns[(ref['table'],ref['property'])]['id']
            if ref['kind']=='measure' and ref['property'] in measures and measures[ref['property']]['table']==ref['table']:return measures[ref['property']]['id']
            raise ValueError('Unresolved native field reference: '+repr(ref))
        # Resolve qualified columns and unqualified measures in the preserved DAX subset.
        dax_ref=re.compile(r"(?:(?:'((?:[^']|'')+)'|([A-Za-z_][A-Za-z0-9_]*))\s*)?\[([^\]]+)\]")
        expressions=[*result['measures'],*[c for c in result['columns'] if c.get('expression')]]
        for item in expressions:
            text=re.sub(r'"(?:[^"]|"")*"','""',item['expression'])
            for match in dax_ref.finditer(text):
                table=(match.group(1) or match.group(2));name=match.group(3)
                ref={'kind':'column' if table else 'measure','table':table or (measures.get(name) or {}).get('table'),'property':name}
                target=bind(ref);result['edges'].append({'from':target,'to':item['id'],'kind':'dax_reference','evidence_path':model_path})
        relationships=model.get('relationships',[]);distinct(relationships,'relationship')
        for relation in relationships:
            record={'id':model_path+'/relationship:'+relation['name'],**relation,'path':model_path};result['relationships'].append(record)
            for side in ('from','to'):bind({'kind':'column','table':relation.get(side+'Table'),'property':relation.get(side+'Column')})
            if not (relation.get('type')=='singleColumn' and relation.get('isActive') is True and relation.get('fromCardinality')=='many' and relation.get('toCardinality')=='one' and relation.get('crossFilteringBehavior')=='oneDirection' and relation.get('securityFilteringBehavior')=='oneDirection'):
                gap('unsupported_relationship_behavior','Relationship is not the active many-to-one single-direction subset',model_path)
            result['edges'].append({'from':model_path+'/table:'+relation['toTable'],'to':model_path+'/table:'+relation['fromTable'],'kind':'relationship_filter','relationship_id':record['id']})
        if len(relationships)!=1:gap('unsupported_relationship_inventory','Expected one unambiguous active relationship for this profile',model_path)
        roles=model.get('roles',[]);distinct(roles,'role')
        for role in roles:
            result['roles'].append({'id':model_path+'/role:'+role['name'],**role,'path':model_path})
            permissions=role.get('tablePermissions',[]);distinct(permissions,'role table permission')
            for permission in permissions:
                if permission['name'] not in {t['name'] for t in tables}:raise ValueError('Role references unknown table')
                text=expression(permission.get('filterExpression'))
                for match in dax_ref.finditer(re.sub(r'"(?:[^"]|"")*"','""',text)):
                    table=match.group(1) or match.group(2) or permission['name']
                    target=bind({'kind':'column','table':table,'property':match.group(3)})
                    result['edges'].append({'from':target,'to':model_path+'/role:'+role['name'],'kind':'security_filter_reference','evidence_path':model_path})
        definition=report_dir/'definition';report,report_path=doc(definition/'report.json');result['report_path']=report_path;result['report_native']=report
        version,_=doc(definition/'version.json');pages,metadata_path=doc(definition/'pages/pages.json')
        if version.get('version')!='2.0.0':gap('unsupported_report_version','Unsupported enhanced PBIR content version',report_path)
        expected_pages=pages.get('pageOrder',[])
        if not expected_pages or len(set(expected_pages))!=len(expected_pages):raise ValueError('Missing/duplicate native page order')
        if pages.get('activePageName') not in expected_pages:raise ValueError('Active page does not resolve')
        filter_ids=set()
        def filters(config,scope,path):
            if set(config)-{'filters','filterSortOrder'}:raise ValueError('Unsupported filter configuration')
            if config.get('filterSortOrder') not in (None,'Ascending','Custom'):raise ValueError('Unsupported filter sort order')
            normalized=[]
            for item in config.get('filters',[]):
                if item['name'] in filter_ids:raise ValueError('Duplicate report filter identity')
                filter_ids.add(item['name']);ref=field_reference(item['field']);bind(ref)
                if item.get('type') not in ('Categorical','Advanced') or item.get('isHiddenInViewMode') or item.get('objects'):raise ValueError('Unsupported or hidden report filter behavior')
                if 'filter' not in item:conditions=[{**ref,'operator':'all','values':[]}]
                else:
                    f=item['filter']
                    if set(f)-{'Version','From','Where'} or f.get('Version')!=2:raise ValueError('Unsupported semantic filter definition')
                    aliases={}
                    for source in f['From']:
                        if set(source)-{'Name','Entity','Type'} or source.get('Type',0)!=0 or source['Name'] in aliases:raise ValueError('Unsupported/duplicate filter source')
                        aliases[source['Name']]=source['Entity']
                    conditions=[]
                    for where in f['Where']:
                        if set(where)!={'Condition'}:raise ValueError('Unsupported filter target/annotation behavior')
                        conditions+=condition_filters(where['Condition'],aliases)
                    if not conditions:raise ValueError('Empty native filter definition')
                for condition in conditions:
                    if any(condition[k]!=ref[k] for k in ('table','property','kind')):raise ValueError('Filter field and predicate provenance mismatch')
                    bind(condition)
                    normalized.append({'id':item['name'],'table':condition['table'],'column':condition['property'],'operator':condition['operator'],'values':condition['values'],'scope':scope,'path':path,'native':item})
            result['filters'].extend(normalized)
            if normalized and scope!='report':gap('unsupported_filter_scope','Page/visual filters are preserved but outside the qualified report-only replay subset',path)
            return normalized
        report_filters=filters(report.get('filterConfig',{}),'report',report_path)
        if set(report)-{'$schema','themeCollection','filterConfig','annotations'}:gap('unsupported_report_behavior','Report settings/resources/extensions require another profile',report_path)
        for page_name in expected_pages:
            if '/' in page_name or '\\' in page_name or page_name in ('.','..'):raise ValueError('Unsafe page identity')
            page_dir=confined(root,definition/'pages',page_name);page,page_path=doc(page_dir/'page.json')
            if page.get('name')!=page_name:raise ValueError('Native page identity/path mismatch')
            if set(page)-{'$schema','name','displayName','displayOption','height','width','filterConfig','annotations'}:gap('unsupported_page_behavior','Page interactions/visibility/bookmarks/bindings require explicit review',page_path)
            result['pages'].append({'id':page_path+'#'+page_name,'name':page_name,'path':page_path,'native':page});filters(page.get('filterConfig',{}),'page:'+page_name,page_path)
            native_ids=set();found=0
            for path in sorted((page_dir/'visuals').glob('*/visual.json')):
                native,relative=doc(path);name=native.get('name')
                if not name or name in native_ids or name!=path.parent.name:raise ValueError('Duplicate/missing/path-mismatched visual identity')
                native_ids.add(name);found+=1
                visual=native.get('visual',{})
                if set(native)-{'$schema','name','position','visual','filterConfig','annotations'}:gap('unsupported_visual_behavior','Hidden/grouped visual behavior requires explicit review',relative)
                if set(visual)-{'visualType','query','visualContainerObjects'} or visual.get('visualType')!='tableEx':gap('unsupported_visual_behavior','Only native tableEx query projections are profiled',relative)
                query=visual.get('query',{});projections=[]
                if set(query)!={'queryState'} or set(query.get('queryState',{}))!={'Values'}:raise ValueError('Unsupported visual query role/sort/options')
                state=query['queryState']['Values']
                if set(state)-{'projections','showAll'} or state.get('showAll',False) is not False:raise ValueError('Unsupported show-items-with-no-data/field parameter behavior')
                for projection in state.get('projections',[]):
                    if set(projection)-{'field','queryRef','displayName','nativeQueryRef','format'}:raise ValueError('Hidden/inactive/unsupported visual projection')
                    ref=field_reference(projection['field']);target=bind(ref)
                    if projection['queryRef']!=ref['table']+'.'+ref['property']:raise ValueError('Stale visual queryRef provenance')
                    if any(p['queryRef']==projection['queryRef'] for p in projections):raise ValueError('Duplicate visual queryRef')
                    projections.append({**ref,'queryRef':projection['queryRef'],'native':projection})
                    result['edges'].append({'from':target,'to':relative+'#'+name,'kind':'visual_projection','evidence_path':relative})
                if not projections:raise ValueError('Visual query has no projections')
                objects=visual.get('visualContainerObjects',{});title=name
                if set(objects)-{'title'}:gap('unsupported_visual_formatting','Uninterpreted visual container objects',relative)
                if objects.get('title'):
                    entries=objects['title']
                    if len(entries)!=1 or set(entries[0])!={'properties'}:raise ValueError('Unsupported conditional visual title')
                    props=entries[0]['properties']
                    if set(props)-{'text','show'}:raise ValueError('Unsupported visual title property')
                    title=literal(props['text']['expr'])
                    if props.get('show') and literal(props['show']['expr']) is not True:raise ValueError('Hidden visual title')
                vf=filters(native.get('filterConfig',{}),'visual:'+name,relative)
                result['visuals'].append({'id':name,'scoped_id':relative+'#'+name,'name':title,'title':title,'path':relative,'page':page_name,'visual_type':visual.get('visualType'),
                    'projections':projections,'filters':vf,'native':native,'position':native['position']})
            if not found:gap('missing_visuals','No visuals supplied for declared page',page_path)
        result['visuals'].sort(key=lambda v:(expected_pages.index(v['page']),v['position'].get('tabOrder',v['position'].get('z',0)),v['id']))
        mappings={('Invoices','Invoice Date','gte'):'start_date',('Invoices','Invoice Date','lt'):'end_date',('Invoices','Status','in'):'status',('Customers','Segment','all'):'segment',('Customers','Segment','in'):'segment',('Scenario','Multiplier','in'):'multipliers'}
        for f in report_filters:
            key=mappings.get((f['table'],f['column'],f['operator']))
            if key is None:gap('unsupported_default_filter','Report filter not interpreted as a supported default',f['path']);continue
            if key in result['report_defaults']:raise ValueError('Ambiguous duplicate report default')
            values=f['values']
            if key=='multipliers':value=values
            elif key=='segment' and f['operator']=='all':value='ALL'
            elif len(values)==1:value=values[0]
            else:raise ValueError('Unsupported multivalue report default')
            result['report_defaults'][key]=value;result['report_default_evidence'][key]={'filter_id':f['id'],'path':f['path'],'operator':f['operator'],'basis':'Native report filter; ALL denotes explicit unfiltered Segment card' if key=='segment' else 'Native report filter'}
        if set(result['report_defaults'])!={'start_date','end_date','segment','status','multipliers'}:gap('missing_report_defaults','Native report default coverage is incomplete',report_path)
        result['security_context_basis']='Tenant role/persona selection is external harness input; no role membership or active role is inferred from PBIR.'
        for path in documents:
            if path not in consumed:gap('unbound_native_asset','Unreferenced model/report/JSON asset requires explicit authority selection',path)
    except (KeyError,TypeError,ValueError,OSError,AttributeError,IndexError) as error:gap('native_binding_error',error)
    gap('native_runtime_unverified','No Power BI Desktop/TOM/Analysis Services/M/DAX execution, native SQL authentication, RLS service membership, refresh/folding or visual acceptance occurred',severity='review')
    gap('bounded_semantics','M/DAX text and references are retained; complete language semantics and runtime behavior require the separate reviewed interpreter or native validation',severity='review')
    return finish()
