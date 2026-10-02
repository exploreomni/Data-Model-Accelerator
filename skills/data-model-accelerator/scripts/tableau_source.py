"""Bounded static Tableau XML/package inventory. Never runs SQL or Tableau."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import unicodedata
import xml.etree.ElementTree as ET
import zipfile

MAX_XML_BYTES=2_000_000
MAX_PACKAGE_BYTES=8_000_000
MAX_MEMBERS=50
SCHEMA_PATH=Path(__file__).with_name('schemas')/'tableau/twb_2026.1.0.xsd'
SCHEMA_SHA256='8bb236b72c1c388aca92bcd00164f65c0d4f5efeaf225252ce0619d8f631e923'
REF=re.compile(r'(?:\[[^\]]+\]\.)?\[[^\]]+\]')


class CredentialContentError(ValueError):
    """A source contains credential fields that must not enter the inventory."""


def _credential_name(value):
    name=re.sub(r'[^a-z0-9]','',value.split('}')[-1].lower())
    return name in {'pwd','pass','token'} or any(part in name for part in
        ('password','passwd','credential','secret','accesstoken','refreshtoken',
         'authtoken','oauthtoken','sessiontoken','authorization','apikey','privatekey'))


def _reject_credentials(root):
    # Reject the whole source before schema diagnostics or native attributes can
    # echo a value. Keep its hash/path as a coverage gap; never mutate source XML.
    message='Credential-bearing XML is excluded; provide a credential-free export'
    for node in root.iter():
        if any(_credential_name(key) and value.strip() for key,value in node.attrib.items()):
            raise CredentialContentError(message)
        if _credential_name(node.tag) and (any(value.strip() for value in node.itertext())
                                           or any(value.strip() for value in node.attrib.values())):
            raise CredentialContentError(message)
        # Connection properties may encode the sensitive field name as data.
        selectors={'name','key','property','id'}
        if node.tag.split('}')[-1].lower() in {'property','connection-property','entry','attribute','option','parameter'}:
            if any(key.split('}')[-1].lower() in selectors and _credential_name(value)
                   for key,value in node.attrib.items()):
                if any(key.split('}')[-1].lower() not in selectors and value.strip()
                       for key,value in node.attrib.items()) or any(value.strip() for value in node.itertext()):
                    raise CredentialContentError(message)


def _sha(data):return hashlib.sha256(data).hexdigest()
def _node(node):
    return {'tag':node.tag,'attributes':dict(node.attrib),'text':(node.text or '').strip(),'children':[_node(c) for c in node]}
def _xml(data):
    if len(data)>MAX_XML_BYTES:raise ValueError('XML exceeds size limit')
    if b'\x00' in data:raise ValueError('Only UTF-8 XML is supported')
    upper=data.upper()
    if b'<!DOCTYPE' in upper or b'<!ENTITY' in upper:raise ValueError('DTD/entity declarations are forbidden')
    root=ET.fromstring(data)
    _reject_credentials(root)
    return root
def _bare(ref):return ref[1:-1] if ref.startswith('[') and ref.endswith(']') else ref

def _qualified(ref,default):
    parts=re.findall(r'\[([^\]]+)\]',ref or '')
    if len(parts)==2:return parts[0],'['+parts[1]+']'
    if len(parts)==1:return default,'['+parts[0]+']'
    raise ValueError('Unsupported or missing Tableau field reference: '+str(ref))

def _sql(source):
    import sqlglot
    from sqlglot import exp
    from sqlglot.errors import ErrorLevel
    trees=sqlglot.parse(source,read='snowflake',error_level=ErrorLevel.RAISE)
    if len(trees)!=1 or not isinstance(trees[0],exp.Query):raise ValueError('Only one read-only custom SQL query is supported')
    t=trees[0];ctes={c.alias.lower() for c in t.find_all(exp.CTE)}
    return {'physical_refs':sorted({'.'.join(p.sql() for p in x.parts) for x in t.find_all(exp.Table) if x.db or x.catalog or x.name.lower() not in ctes}),
            'joins':[x.sql() for x in t.find_all(exp.Join)],'filters':[x.sql() for x in t.find_all(exp.Where)],
            'ctes':[{'name':x.alias,'sql':x.sql()} for x in t.find_all(exp.CTE)],
            'projections':[{'name':x.alias_or_name,'sql':x.sql()} for x in t.expressions]}

def validate_official_schema(path):
    """Report actual XSD attempt separately from XML/static/native validation."""
    data=Path(path).read_bytes();_xml(data)
    if _sha(SCHEMA_PATH.read_bytes())!=SCHEMA_SHA256:raise ValueError('Pinned Tableau XSD hash mismatch')
    result={'xsd_sha256':SCHEMA_SHA256,'native_application_opened':False,'validated':False}
    try:
        from lxml import etree
    except ImportError:
        return {**result,'status':'unavailable_optional_lxml','reason':'lxml is not installed'}
    try:
        parser=etree.XMLParser(no_network=True,resolve_entities=False,load_dtd=False)
        schema=etree.XMLSchema(etree.parse(str(SCHEMA_PATH),parser))
    except etree.XMLSchemaParseError as error:
        return {**result,'status':'unavailable_publisher_schema_dependency','reason':str(error)}
    tree=etree.fromstring(data,parser)
    valid=schema.validate(tree)
    return {**result,'validated':valid,'status':'valid' if valid else 'invalid','errors':[str(e) for e in schema.error_log]}

def inspect_package(path, repo=None):
    """Inspect ZIP bytes in memory; never extracts members or executes content."""
    path=Path(path);result={'path':str(path),'sha256':None,'members':[],'errors':[],'gaps':[],'safe':False,'matches_repo':False,'extracted':False}
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_PACKAGE_BYTES:raise ValueError('Invalid/oversized package file')
        result['sha256']=_sha(path.read_bytes())
        with zipfile.ZipFile(path) as archive:
            entries=archive.infolist()
            if len(entries)>MAX_MEMBERS:raise ValueError('Too many archive entries')
            names=set();total=0
            for entry in entries:
                name=entry.filename;parts=PurePosixPath(name).parts
                if not name or '\\' in name or ':' in name or name.startswith('/') or '..' in parts or '.' in name.split('/') or '\x00' in name:
                    raise ValueError('Unsafe archive member path: '+name)
                normalized=unicodedata.normalize('NFC',name.rstrip('/')).casefold()
                if normalized in names:raise ValueError('Duplicate/colliding archive member: '+name)
                names.add(normalized)
                mode=entry.external_attr>>16
                if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0,stat.S_IFREG,stat.S_IFDIR)):raise ValueError('Symlink/special archive member forbidden')
                if entry.flag_bits&1:raise ValueError('Encrypted archive member unsupported')
                if entry.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED):raise ValueError('Compression method unsupported')
                if entry.is_dir():continue
                if entry.file_size>MAX_XML_BYTES or entry.file_size>max(entry.compress_size,1)*100:raise ValueError('Oversized/high-ratio archive member')
                total+=entry.file_size
                if total>MAX_PACKAGE_BYTES:raise ValueError('Archive expanded size limit exceeded')
                with archive.open(entry) as stream:data=stream.read(MAX_XML_BYTES+1)
                if len(data)!=entry.file_size or len(data)>MAX_XML_BYTES:raise ValueError('Archive member size mismatch')
                suffix=PurePosixPath(name).suffix.lower()
                if suffix in ('.twb','.tds'):_xml(data)
                elif suffix in ('.hyper','.tde','.tfl','.tflx'):result['gaps'].append('Extract/Prep content requires another specialist: '+name)
                member={'path':name,'bytes':len(data),'sha256':_sha(data)}
                if repo is not None:
                    root=Path(repo).resolve();target=root/name
                    if target.is_symlink() or not target.is_file() or not target.resolve().is_relative_to(root) or target.read_bytes()!=data:
                        raise ValueError('Package member differs from repository authority: '+name)
                    member['matches_repo']=True
                result['members'].append(member)
        if sum(m['path'].lower().endswith('.twb') for m in result['members'])!=1:raise ValueError('Package requires exactly one workbook authority')
        result['safe']=True;result['matches_repo']=repo is not None
    except (OSError,ValueError,zipfile.BadZipFile,RuntimeError,ET.ParseError) as error:result['errors'].append(str(error))
    return result

def inspect_repo(repo):
    """Parse present files; compare a separate expected inventory for whole-file loss."""
    root=Path(repo).resolve()
    r={'schema_version':1,'kind':'tableau_source_inventory','repo':str(root),'assets':[],'workbooks':[],
       'datasources':[],'fields':[],'parameters':[],'worksheets':[],'dashboards':[],'mirrors':[],'edges':[],'gaps':[]}
    def gap(kind,message,path=None,identity=None,severity='error'):
        r['gaps'].append({'kind':kind,'severity':severity,'message':message,'path':path,'id':identity})
    files={};mirrors=[]
    for path in sorted(root.rglob('*')):
        if path.is_symlink():gap('symlink','Symlink source is unsupported',str(path.relative_to(root)));continue
        if not path.is_file():continue
        rel=str(path.relative_to(root))
        if path.stat().st_size>MAX_XML_BYTES:gap('oversized_asset','Asset exceeds bounded size limit',rel);continue
        data=path.read_bytes();r['assets'].append({'path':rel,'sha256':_sha(data),'bytes':len(data)})
        if path.suffix.lower() in ('.twb','.tds'):
            try:
                tree=_xml(data)
                if tree.tag!=('workbook' if path.suffix.lower()=='.twb' else 'datasource'):raise ValueError('Root element does not match file type')
                if path.suffix.lower()=='.twb':files[rel]=tree
                else:mirrors.append((rel,tree))
            except CredentialContentError as e:gap('credential_content',str(e),rel)
            except (ET.ParseError,ValueError) as e:gap('xml_invalid',str(e),rel)
        elif path.suffix.lower() in ('.twbx','.tdsx','.hyper','.tde','.tfl','.tflx'):
            gap('separate_profile','Package/extract/Prep requires explicit separate inventory; not counted as a workbook',rel)
    for path,tree in files.items():
        location=tree.find('repository-location'); native_id=location.get('id') if location is not None else None
        wid=path+'#'+(native_id or 'unbound-workbook')
        w={'id':wid,'path':path,'native_id':native_id,'attributes':dict(tree.attrib),'datasource_ids':[],'worksheet_ids':[],'dashboard_ids':[]}
        r['workbooks'].append(w)
        if not native_id:gap('missing_workbook_identity','No native repository identity; path-scoped placeholder only',path,wid,'review')
        schema=validate_official_schema(root/path);w['official_schema_validation']=schema
        if schema['status']!='valid':gap('official_schema_unvalidated',schema.get('reason',str(schema.get('errors'))),path,wid,'review' if schema['status'].startswith('unavailable') else 'error')
        ds_map={};field_map={};instance_map={}
        for ds in tree.findall('./datasources/datasource'):
            name=ds.get('name');did=wid+'/datasource:'+str(name)
            if not name or name in ds_map:gap('duplicate_or_missing_datasource','Datasource names must be unique within workbook',path,did);continue
            isparam=name=='Parameters';d={'id':did,'name':name,'caption':ds.get('caption'),'path':path,'workbook_id':wid,'is_parameters':isparam,
                'fields':[],'filters':[],'connections':[],'custom_sql':None,'sql_analysis':None,'native_attributes':dict(ds.attrib),'mirror_paths':[]}
            ds_map[name]=d;field_map[name]={};w['datasource_ids'].append(did)
            if not isparam:r['datasources'].append(d)
            for conn in ds.findall('./connection/named-connections/named-connection'):
                detail=conn.find('connection');values=dict(detail.attrib) if detail is not None else {}
                d['connections'].append({'id':conn.get('name'),'name':conn.get('name'),'caption':conn.get('caption'),'attributes':values,
                   'platform_instance':values.get('server'),'catalog':values.get('dbname'),'schema':values.get('schema'),'native_class':values.get('class')})
            if not isparam and len(d['connections'])!=1:gap('unsupported_connection','Exactly one named embedded connection is supported',path,did)
            if not isparam and any(c['native_class']!='snowflake' for c in d['connections']):
                gap('unsupported_connection_class','Only the Snowflake custom SQL connection subset is analyzed',path,did)
            if d['connections']:d['connection']=d['connections'][0]
            sqls=ds.findall('./connection/relation')
            if not isparam:
                if len(sqls)!=1 or sqls[0].get('type')!='text':gap('unsupported_relation','Embedded custom SQL relation required; logical/physical relationship semantics not inferred',path,did)
                else:
                    relation=sqls[0];source=relation.text or '';d['custom_sql']=source;d['relation_attributes']=dict(relation.attrib)
                    try:
                        d['sql_analysis']=_sql(source)
                        if not source.strip():raise ValueError('Custom SQL is empty')
                        for physical in d['sql_analysis']['physical_refs']:
                            r['edges'].append({'from':'warehouse:'+physical,'to':did,'kind':'warehouse_read','evidence':physical,'connection_id':relation.get('connection')})
                        if relation.get('connection') not in {x['id'] for x in d['connections']}:gap('unbound_connection','Custom SQL connection reference is missing',path,did)
                    except Exception as e:gap('sql_invalid',str(e),path,did)
            mapping={}
            for record in ds.findall('./connection/metadata-records/metadata-record'):
                if record.get('class')!='column':continue
                local,remote=record.findtext('local-name'),record.findtext('remote-name')
                if not local or not remote or local in mapping:gap('ambiguous_raw_mapping','Native local/remote column mapping is missing or duplicated',path,did)
                mapping[local]=remote
            for column in ds.findall('column'):
                namef=column.get('name');fid=did+'/field:'+str(namef);calc=column.find('calculation')
                if not namef or namef in field_map[name]:gap('duplicate_or_missing_field','Field identifiers must be unique within datasource',path,fid);continue
                f={'id':fid,'name':namef,'caption':column.get('caption',_bare(namef)),'datasource_id':did,'datasource_name':name,'workbook_id':wid,'path':path,
                   'datatype':column.get('datatype'),'role':column.get('role'),'type':column.get('type'),'formula':calc.get('formula') if calc is not None else None,
                   'raw_column':mapping.get(namef),'attributes':dict(column.attrib),'calculation_attributes':dict(calc.attrib) if calc is not None else None,
                   'table_calc':[_node(t) for t in column.findall('./calculation/table-calc')]}
                field_map[name][namef]=f;d['fields'].append(f);r['fields'].append(f)
                if isparam:
                    value=column.get('value');default=value
                    if value is not None:
                        if value.startswith('"') and value.endswith('"'):default=value[1:-1]
                        elif value.startswith('#') and value.endswith('#'):default=value[1:-1]
                        elif f['datatype'] in ('real','integer'):
                            try:default=float(value) if f['datatype']=='real' else int(value)
                            except ValueError:gap('parameter_default','Malformed numeric parameter default',path,fid)
                    r['parameters'].append({**f,'default':default,'native_value':value,'domain_type':column.get('param-domain-type'),'members':[x.get('value') for x in column.findall('./members/member')],'range':_node(column.find('range')) if column.find('range') is not None else None})
                elif calc is None and not f['raw_column']:gap('unbound_physical_field','No native metadata mapping for raw field',path,fid)
                elif calc is not None and calc.get('class')!='tableau':gap('unsupported_calculation','Calculation language not supported',path,fid)
            d['_native_node']=ds
            for unsupported in ('extract','object-graph','object-model','repository-location'):
                node=ds.find(unsupported)
                if node is not None and (unsupported!='repository-location' or node.get('path')):gap('unresolved_native_dependency','Published/extract/relationship metadata requires separate evidence: '+unsupported,path,did)
        def resolve(reference,default,instances=None):
            dsname,field=_qualified(reference,default)
            if instances and (dsname,field) in instances:field=instances[(dsname,field)]['column']
            if field not in field_map.get(dsname,{}):
                # Datasource filter level may encode its native column-instance without
                # duplicating that instance at datasource level.
                match=re.fullmatch(r'\[(?:none|usr|sum|min):(.+):(?:nk|qk|ok)\]',field)
                if match and '['+match.group(1)+']' in field_map.get(dsname,{}):field='['+match.group(1)+']'
            found=field_map.get(dsname,{}).get(field)
            if not found:raise ValueError('Unresolved field reference '+reference)
            return found
        def filters(nodes,default,owner,stage,instances=None):
            out=[]
            for index,node in enumerate(nodes):
                item={'id':owner+'/filter:'+str(index),'column':node.get('column'),'attributes':dict(node.attrib),'native':_node(node),'stage':stage,'context':node.get('context') in ('true','1')}
                if node.get('context') not in (None,'true','false','1','0'):
                    gap('invalid_context_flag','Native context attribute is not a Boolean value',path,item['id'])
                try:
                    f=resolve(item['column'],default,instances);item.update(field_id=f['id'],field_name=f['name'],caption=f['caption'],formula=f['formula'])
                    if stage!='datasource':item['stage']='context' if item['context'] else 'dimension'
                    members=node.findall('groupfilter')
                    if node.get('class')!='categorical' or len(members)!=1 or members[0].get('function')!='member' or members[0].get('member') not in ('true','false'):
                        gap('unsupported_filter','Only categorical Boolean member filters are analyzed',path,item['id'])
                    else:
                        item['member']=members[0].get('member')=='true'
                        member_field=resolve(members[0].get('level'),default,instances)
                        if member_field['id']!=f['id']:
                            gap('filter_level_mismatch','Native member level differs from filter column',path,item['id'])
                    r['edges'].append({'from':f['id'],'to':owner,'kind':item['stage']+'_filter','evidence':item['native']})
                except ValueError as e:gap('unresolved_filter',str(e),path,item['id'])
                out.append(item)
            return out
        for d in ds_map.values():
            d['filters']=filters(d['_native_node'].findall('filter'),d['name'],d['id'],'datasource')
            if d['is_parameters']:continue
            for f in d['fields']:
                for reference in REF.findall(f['formula'] or ''):
                    try:
                        parent=resolve(reference,d['name']);r['edges'].append({'from':parent['id'],'to':f['id'],'kind':'calculation_reference','evidence':reference})
                    except ValueError as e:gap('unresolved_calculation',str(e),path,f['id'])
                if re.search(r'\b(SCRIPT_|MODEL_EXTENSION_|RAWSQL_|INCLUDE|EXCLUDE|RUNNING_|LOOKUP\s*\()',f['formula'] or ''):
                    gap('unsupported_calculation','Formula requires behavior outside bounded replay',path,f['id'])
        names=set()
        for sheet in tree.findall('./worksheets/worksheet'):
            name=sheet.get('name');sid=wid+'/worksheet:'+str(name)
            if not name or name in names:gap('duplicate_or_missing_worksheet','Worksheet name missing/repeated',path,sid);continue
            names.add(name);w['worksheet_ids'].append(sid)
            refs=[d.get('name') for d in sheet.findall('./table/view/datasources/datasource')]
            physical=[x for x in refs if x!='Parameters']
            s={'id':sid,'name':name,'path':path,'workbook_id':wid,'native_id':sheet.find('simple-id').get('uuid') if sheet.find('simple-id') is not None else None,
               'datasource_names':refs,'datasource_ids':[ds_map[x]['id'] for x in refs if x in ds_map],'fields':[],'instances':[],'grouping':[],'selected_fields':[],
               'filters':[],'datasource_filters':[],'table_calculations':[],'shelves':{'rows':sheet.findtext('./table/rows') or '','cols':sheet.findtext('./table/cols') or ''}}
            r['worksheets'].append(s)
            if len(physical)!=1 or physical[0] not in ds_map:gap('unresolved_worksheet_datasource','Worksheet requires one resolved embedded datasource',path,sid);continue
            default=physical[0];s['datasource_id']=ds_map[default]['id'];s['datasource_filters']=ds_map[default]['filters'];instances={}
            for deps in sheet.findall('./table/view/datasource-dependencies'):
                dep=deps.get('datasource')
                for c in deps.findall('column'):
                    try:
                        f=resolve(c.get('name'),dep);calc=c.find('calculation');formula=calc.get('formula') if calc is not None else None
                        if formula!=f['formula'] or any(c.get(a)!=f.get(a) for a in ('datatype','role','type')):gap('dependency_definition_drift','Worksheet copy differs from authoritative datasource field',path,sid)
                    except ValueError as e:gap('unresolved_dependency',str(e),path,sid)
                for ci in deps.findall('column-instance'):
                    key=(dep,ci.get('name'))
                    if key in instances:gap('duplicate_instance','Duplicate worksheet column-instance',path,sid)
                    item={'datasource_name':dep,**ci.attrib,'table_calc':[_node(t) for t in ci.findall('table-calc')]};instances[key]=item;s['instances'].append(item)
            def use(reference,group=False):
                try:
                    f=resolve(reference,default,instances);entry={'reference':reference,'field_id':f['id'],'name':f['name'],'caption':f['caption'],'formula':f['formula'],'raw_column':f['raw_column']}
                    if entry['field_id'] not in {x['field_id'] for x in s['fields']}:s['fields'].append(entry)
                    dest=s['grouping'] if group else s['selected_fields']
                    if entry['field_id'] not in {x['field_id'] for x in dest}:dest.append(entry)
                    r['edges'].append({'from':f['id'],'to':sid,'kind':'view_grouping' if group else 'view_measure','evidence':reference})
                except ValueError as e:gap('unresolved_view_field',str(e),path,sid)
            for text in s['shelves'].values():
                for reference in REF.findall(text):
                    try:use(reference,resolve(reference,default,instances)['role']=='dimension')
                    except ValueError as e:gap('unresolved_shelf',str(e),path,sid)
            for encoding in sheet.findall('./table/panes/pane/encodings/*'):
                if encoding.get('column'):use(encoding.get('column'),False)
            s['filters']=filters(sheet.findall('./table/view/filter'),default,sid,'worksheet',instances)
            for item in s['instances']:
                for tc in item['table_calc']:
                    orders=[x['attributes'].get('field') for x in tc['children'] if x['tag']=='order']
                    if not orders and tc['attributes'].get('ordering-field'):orders=[tc['attributes']['ordering-field']]
                    evidence={'column':item['column'],'native':tc,'addressing':[],'partitioning':[],'partition_basis':'Remaining selected view dimensions after explicit addressing; inferred, not an authored partition XML field.'}
                    try:
                        if tc['attributes'].get('ordering-type')!='Field' or not orders:raise ValueError('Only explicit Field addressing is resolved')
                        evidence['addressing']=[resolve(x,default)['name'] for x in orders]
                        dimensions=[x['name'] for x in s['grouping']]
                        if not set(evidence['addressing'])<=set(dimensions):raise ValueError('Addressing fields are outside view grouping')
                        evidence['partitioning']=[x for x in dimensions if x not in evidence['addressing']]
                    except ValueError as e:gap('unresolved_table_calculation',str(e),path,sid)
                    s['table_calculations'].append(evidence)
            for measure in s['selected_fields']:
                if 'WINDOW_' in (measure['formula'] or '') and not any(t['column']==measure['name'] for t in s['table_calculations']):gap('missing_table_calculation_scope','Selected table calculation has no explicit worksheet addressing metadata',path,sid)
        dashboard_names=set()
        for dashboard in tree.findall('./dashboards/dashboard'):
            name=dashboard.get('name');did=wid+'/dashboard:'+str(name);zones=[dict(z.attrib) for z in dashboard.findall('.//zone')]
            if not name or name in dashboard_names:gap('duplicate_or_missing_dashboard','Dashboard name missing/repeated',path,did)
            dashboard_names.add(name)
            sheets=[z['name'] for z in zones if z.get('name') and z.get('type-v2')=='viz']
            d={'id':did,'name':name,'path':path,'workbook_id':wid,'worksheets':sheets,'zones':zones,'attributes':dict(dashboard.attrib)};r['dashboards'].append(d);w['dashboard_ids'].append(did)
            for sh in sheets:
                if sh not in names:gap('unresolved_dashboard_sheet','Dashboard references unknown worksheet: '+sh,path,did)
                else:r['edges'].append({'from':wid+'/worksheet:'+sh,'to':did,'kind':'dashboard_sheet','evidence':sh})
        if not names:gap('missing_worksheets','No worksheets supplied',path,wid)
        for tag in ('actions','stories','shared-views'):
            if tree.find(tag) is not None:gap('unsupported_workbook_behavior','Native '+tag+' preserved in source but requires another semantic pass',path,wid)
        for mirror_path,mirror in mirrors:
            name=mirror.get('name');d=ds_map.get(name)
            if d and not d['is_parameters']:
                match=_node(mirror)==_node(d['_native_node'])
                r['mirrors'].append({'path':mirror_path,'datasource_id':d['id'],'matches_embedded':match,'authority':'consistency_mirror_only'})
                d['mirror_paths'].append(mirror_path)
                if not match:gap('tds_mirror_drift','TDS differs from embedded datasource including SQL/fields/filters/connections',mirror_path,d['id'])
        for d in ds_map.values():d.pop('_native_node',None)
        gap('native_runtime_unverified','No Tableau opening, rendering, connection authentication, server permissions, refresh, densification or dashboard-action validation occurred',path,wid,'review')
    matched={m['path'] for m in r['mirrors']}
    for path,_ in mirrors:
        if path not in matched:gap('unbound_tds','TDS has no matching embedded workbook datasource; not an independent authority',path)
    if not r['workbooks']:gap('no_workbooks','No safely parsed workbook found')
    native_ids=[w['native_id'] for w in r['workbooks'] if w['native_id']]
    if len(native_ids)!=len(set(native_ids)):gap('duplicate_workbook_identity','Multiple workbook exports claim the same native repository identity; no authority was selected')
    r['counts']={'assets':len(r['assets']),'workbooks':len(r['workbooks']),'datasources':len(r['datasources']),'fields':len(r['fields']),
        'calculations':sum(f['formula'] is not None and f['datasource_name']!='Parameters' for f in r['fields']),
        'parameters':len(r['parameters']),'worksheets':len(r['worksheets']),'dashboards':len(r['dashboards']),'edges':len(r['edges']),
        'errors':sum(g['severity']=='error' for g in r['gaps']),'review_gaps':sum(g['severity']=='review' for g in r['gaps'])}
    r['static_coverage_complete']=r['counts']['errors']==0;r['native_runtime_validated']=False
    return r
