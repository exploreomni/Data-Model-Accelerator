"""Lossless private Omni inventory and explicit authored patch proposals.

Never fetches, executes SQL, follows embedded instructions, writes native state,
or authenticates inventory provenance. Raw bytes and parsed definitions are
private source data: callers must apply disclosure controls before sharing.
"""
import argparse
import base64
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from omni_contract import _bounded, _load, canonical_hash, yaml, DIM, MEASURE

VERSION = 'omni-inventory-v1'
MAX_FILES, MAX_BYTES = 512, 8 * 1024 * 1024
NAME = re.compile(r'[A-Za-z][A-Za-z0-9_]*\Z')
SHA = re.compile(r'[a-f0-9]{64}\Z')
REFERENCE = re.compile(r'\$\{([^{}]+)\}')
VIEW_KEYS = {'catalog', 'schema', 'table_name', 'dimensions', 'measures', 'extends', 'query', 'sql',
             'label', 'description', 'ai_context', 'hidden', 'ignored', 'tags', 'required_access_grants',
             'name', 'view_label', 'schema_label', 'folder'}
TOPIC_KEYS = {'base_view', 'joins', 'relationships', 'views', 'topics', 'extends', 'fields', 'ai_fields',
              'label', 'description', 'ai_context', 'hidden', 'group_label', 'base_view_label', 'tags',
              'required_access_grants', 'access_filters', 'default_filters', 'always_where_sql',
              'default_row_limit', 'week_start_day', 'sample_queries', 'shared_dimensions', 'shared_measures',
              'unrelated_dimension_handling', 'always_join_all_topics'}
MODEL_KEYS = {'label', 'description', 'ai_context', 'week_start_day', 'access_grants', 'constants',
              'extends', 'included_schemas', 'included_views', 'ignored_schemas', 'ignored_views',
              'topics', 'ai_chat_topics', 'cache_policies', 'default_cache_policy', 'default_timeframes',
              'default_topic_access_filters', 'default_topic_required_access_grants', 'dynamic_schemas',
              'sql_preamble', 'custom_calendars', 'fiscal_month_offset', 'ai_settings', 'sample_queries'}


class InventoryError(ValueError):
    """Only stable value-free codes cross the public error boundary."""


def _need(ok, code):
    if not ok:
        raise InventoryError(code)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _path(path):
    _need(type(path) is str and bool(path) and len(path) <= 1024 and
          re.fullmatch(r'[A-Za-z0-9_ ./-]+', path) is not None, 'inventory.path')
    relative = PurePosixPath(path)
    _need(not relative.is_absolute() and str(relative) == path and
          all(part not in ('.', '..') for part in relative.parts), 'inventory.path')
    return relative


def _files(files):
    _need(type(files) is dict and len(files) <= MAX_FILES, 'inventory.files')
    result, size = {}, 0
    for path, content in files.items():
        _path(path)
        _need(type(content) in (str, bytes), 'inventory.content')
        try:
            data = content.encode('utf-8') if type(content) is str else content
        except UnicodeError:
            raise InventoryError('inventory.encoding') from None
        size += len(path.encode('utf-8')) + len(data)
        _need(size <= MAX_BYTES, 'inventory.byte_limit')
        result[path] = data
    return dict(sorted(result.items()))


def encode_files(files):
    """JSON-safe raw-byte records; unchanged comments/line endings survive."""
    return {path:{'sha256':_sha(data), 'byte_length':len(data),
                  'base64':base64.b64encode(data).decode('ascii')} for path,data in _files(files).items()}


def decode_files(records):
    """Restore exact bytes from an inventory/candidate after verifying hashes."""
    try:
        _need(type(records) is dict and len(records) <= MAX_FILES, 'inventory.records')
        output = {}; total = 0
        for path, record in records.items():
            _path(path)
            _need(type(record) is dict and set(record) == {'sha256','byte_length','base64'} and
                  type(record['base64']) is str and len(record['base64']) <= MAX_BYTES * 2,
                  'inventory.record')
            data = base64.b64decode(record['base64'], validate=True)
            total += len(data)
            _need(total <= MAX_BYTES, 'inventory.byte_limit')
            _need(type(record['byte_length']) is int and record['byte_length'] == len(data) and
                  record['sha256'] == _sha(data), 'inventory.record_changed')
            output[path] = data
        return _files(output)
    except InventoryError:
        raise
    except (ValueError, TypeError, UnicodeError):
        raise InventoryError('inventory.record') from None


def native_identity(path):
    """Filename identity only, not vendor detection or semantic validation."""
    name = _path(path).name
    if name.endswith(('.yaml', '.yml')):
        name = name.rsplit('.', 1)[0]
    if name in ('model', 'relationships'):
        return name, name
    for suffix, kind in (('.query.view','query_view'), ('.view','view'), ('.topic','topic')):
        if name.endswith(suffix):
            identity = name[:-len(suffix)]
            return (kind, identity) if NAME.fullmatch(identity) else None
    return None


def is_omni_file(path, content, *, corroborated=False):
    """Conservative routing: own filename AND structure, never sibling identity.

    Without optional YAML, recognized top-level signatures still route for later
    inspection. This makes no parse/coverage/validity assertion.
    """
    try:
        identity = native_identity(path)
        if identity is None or type(content) not in (str, bytes):
            return False
        text = content.decode('utf-8') if type(content) is bytes else content
        if len(text.encode('utf-8')) > MAX_BYTES:
            return False
        kind, _ = identity
        patterns = {'view':r'(?m)^(?:dimensions|measures|extends|table_name|query|sql)\s*:',
                    'query_view':r'(?m)^(?:query|sql)\s*:',
                    'topic':r'(?m)^(?:base_view|topics|relationships|joins|views)\s*:',
                    'model':r'(?m)^(?:week_start_day|access_grants|included_schemas|included_views|ignored_schemas|ignored_views|ai_context|ai_chat_topics|cache_policies|default_timeframes|default_topic_access_filters|constants|dynamic_schemas)\s*:',
                    'relationships':r'(?m)^\s*-\s*join_from_view\s*:'}
        strong=bool(re.search(patterns[kind], text))
        if not strong:
            if not corroborated or kind not in ('model','relationships'):
                return False
            # Weak support-file forms need separately verified native context.
            # A sibling filename alone must never set corroborated=True.
            meaningful='\n'.join(line for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#'))
            if kind=='relationships':
                return meaningful.strip()=='[]'
            if yaml is None:
                return bool(meaningful) and all(re.fullmatch(r'(?:label|description):\s+[^\n]+',line) for line in meaningful.splitlines())
            value=_load(text)
            return type(value) is dict and bool(value) and set(value)<={'label','description'} and all(type(v) is str for v in value.values())
        if yaml is None:
            return True
        value = _load(text)
        if kind == 'relationships':
            return type(value) is list and bool(value) and all(type(r) is dict and
                all(type(r.get(k)) is str for k in ('join_from_view','join_to_view','on_sql')) for r in value)
        if type(value) is not dict:
            return False
        if kind == 'model':
            return bool(set(value) & (MODEL_KEYS - {'label','description','extends','topics'}))
        if kind == 'query_view':
            return type(value.get('query')) is dict or type(value.get('sql')) is str
        if kind == 'topic':
            return type(value.get('base_view')) is str or type(value.get('topics')) in (dict,list)
        return any(type(value.get(k)) is dict for k in ('dimensions','measures','query')) or \
            type(value.get('extends')) is list or type(value.get('table_name')) is str or type(value.get('sql')) is str
    except Exception:
        return False


def _context(context):
    if context is None:
        return {'scope':{'model_id':None,'layer':'unknown','branch_id':None,'workbook_id':None},
                'capture_reference':None}
    _bounded(context)
    _need(type(context) is dict and set(context) <= {'scope','capture_reference','catalogue_sha256'}, 'inventory.context')
    value = copy.deepcopy(context)
    scope = value.setdefault('scope', {'model_id':None,'layer':'unknown','branch_id':None,'workbook_id':None})
    _need(type(scope) is dict and set(scope) == {'model_id','layer','branch_id','workbook_id'} and
          scope['layer'] in ('unknown','schema','shared','branch','workbook'), 'inventory.scope')
    for key in ('model_id','branch_id','workbook_id'):
        _need(scope[key] is None or type(scope[key]) is str and 0 < len(scope[key]) <= 256, 'inventory.scope')
    value.setdefault('capture_reference', None)
    _need(value['capture_reference'] is None or type(value['capture_reference']) is str, 'inventory.capture')
    if 'catalogue_sha256' in value:
        _need(type(value['catalogue_sha256']) is str and SHA.fullmatch(value['catalogue_sha256']), 'inventory.catalogue_pin')
    return value


def _coverage(files, expected, context):
    result = {'status':'unverified', 'expected_files':None, 'observed_files':len(files),
              'missing':[], 'unexpected':[], 'changed':[], 'provenance':None,
              'independence_authenticated':False, 'native_verified':False}
    if expected is None:
        return result
    _bounded(expected)
    _need(type(expected) is dict and set(expected) == {'schema_version','kind','scope_sha256',
          'provenance','reference','complete','pagination_complete','files'}, 'inventory.expected_shape')
    _need(type(expected['schema_version']) is int and expected['schema_version'] == 1 and
          expected['kind'] == 'omni_expected_inventory' and expected['scope_sha256'] == canonical_hash(context['scope']) and
          expected['provenance'] in ('independently_observed','operator_declared','synthetic') and
          type(expected['reference']) is str and bool(expected['reference']) and
          type(expected['complete']) is bool and type(expected['pagination_complete']) is bool and
          type(expected['files']) is dict, 'inventory.expected_contract')
    for path, digest in expected['files'].items():
        _path(path)
        _need(type(digest) is str and SHA.fullmatch(digest), 'inventory.expected_pin')
    result.update(expected_files=len(expected['files']), provenance=expected['provenance'],
                  reference_sha256=_sha(expected['reference'].encode('utf-8')),
                  missing=sorted(set(expected['files'])-set(files)), unexpected=sorted(set(files)-set(expected['files'])),
                  changed=sorted(p for p in files if p in expected['files'] and _sha(files[p]) != expected['files'][p]))
    if result['missing'] or result['unexpected'] or result['changed']:
        result['status'] = 'mismatch'
    elif not expected['complete'] or not expected['pagination_complete']:
        result['status'] = 'partial_capture'
    elif expected['reference'] == context['capture_reference']:
        result['status'] = 'same_capture_not_independent'
    else:
        result['status'] = 'matched_declared_inventory'
    return result


def _inspect(files, context=None, expected_inventory=None, *, effective_files=None):
    authored = _files(files); effective = _files({} if effective_files is None else effective_files)
    _need(bool(authored or effective), 'inventory.empty')
    _need(sum(len(x) for x in authored.values()) + sum(len(x) for x in effective.values()) <= MAX_BYTES,
          'inventory.byte_limit')
    context = _context(context)
    findings, objects, fields, pending = [], [], [], []
    indexes, field_indexes, local_views = {}, {}, {}
    def issue(code, origin, index, severity='gap', location='/'):
        value = {'code':code,'origin':origin,'artifact_index':index,'location':location,'severity':severity}
        if value not in findings:
            findings.append(value)
    def dependency(owner, ref, kind, origin, index, source_field=None):
        if type(ref) is str and ref:
            _need(len(pending)<50000,'inventory.dependency_limit')
            pending.append((owner,ref,kind,origin,index,source_field))
        else:
            issue('dependency.shape',origin,index,'error')
    def references(value, owner, origin, index, source_field=None):
        stack = [value]
        while stack:
            item = stack.pop()
            if type(item) is dict:
                stack.extend(item.values())
            elif type(item) is list:
                stack.extend(item)
            elif type(item) is str:
                for ref in REFERENCE.findall(item):
                    dependency(owner,ref,'sql_reference',origin,index,source_field)
                if '{{' in item or '{%' in item:
                    issue('template.preserved_unqualified',origin,index)
    def add_object(kind, name, definition, path, origin, index, *, parent=None, subtype=None):
        _need(len(objects)+len(fields)<20000,'inventory.node_limit')
        family = 'view' if kind in ('view','query_view') else kind
        identity = (parent + '/view:' + name) if parent else origin + ':' + family + ':' + name
        obj = {'id':identity,'kind':kind,'name':name,'subtype':subtype or kind,'origin':origin,'path':path,
               'raw_sha256':_sha((authored if origin=='authored' else effective)[path]),
               'definition':definition, 'definition_sha256':canonical_hash(definition),
               'parent_id':parent,'outputs':[],'unsupported_keys':[]}
        objects.append(obj)
        key=(origin,family,name,parent)
        indexes.setdefault(key,[]).append(identity)
        if len(indexes[key])>1:
            issue('object.duplicate_identity',origin,index,'error')
        if parent:
            local_views[(parent,name)] = identity
        if type(definition) is not dict:
            return obj
        known = VIEW_KEYS if family=='view' else TOPIC_KEYS if family=='topic' else MODEL_KEYS if family=='model' else set(definition)
        obj['unsupported_keys'] = sorted(set(definition)-known)
        if obj['unsupported_keys']:
            issue('parameter.opaque_preserved',origin,index)
        if 'extends' in definition:
            if type(definition['extends']) is list:
                for ref in definition['extends']:
                    dependency(identity,ref,'extends',origin,index)
            else:
                issue('extends.shape',origin,index,'error')
        for section in ('dimensions','measures'):
            values = definition.get(section,{})
            if type(values) is not dict:
                issue('fields.shape',origin,index,'error', '/' + section); continue
            for field_name, field_def in values.items():
                if not NAME.fullmatch(field_name) or type(field_def) is not dict:
                    issue('field.shape',origin,index,'error','/' + section); continue
                field_id = identity + '/field:' + field_name
                _need(len(objects)+len(fields)<20000,'inventory.node_limit')
                field = {'id':field_id,'object_id':identity,'name':field_name,'kind':section[:-1],
                         'origin':origin,'definition':field_def,'definition_sha256':canonical_hash(field_def)}
                field['unsupported_keys']=sorted(set(field_def)-(DIM if section=='dimensions' else MEASURE))
                if field['unsupported_keys']:
                    issue('field.parameter_opaque_preserved',origin,index)
                fields.append(field)
                field_indexes.setdefault((identity,field_name),[]).append(field_id)
                if len(field_indexes[(identity,field_name)])>1:
                    issue('field.duplicate_identity',origin,index,'error')
                references(field_def,identity,origin,index,field_id)
                filters=field_def.get('filters')
                if filters is not None:
                    if type(filters) is dict:
                        for source in filters:
                            dependency(identity,source,'measure_filter',origin,index,field_id)
                    else:
                        issue('measure.filters_unqualified',origin,index)
        if family=='view':
            if 'query' in definition and 'sql' in definition:
                issue('view.multiple_sources',origin,index,'error')
            query=definition.get('query')
            if query is not None:
                if type(query) is not dict:
                    issue('query.shape',origin,index,'error')
                else:
                    dependency(identity,query.get('base_view'),'query_base',origin,index)
                    if 'topic' in query:
                        dependency(identity,query['topic'],'query_topic',origin,index)
                    query_fields=query.get('fields')
                    entries=list(query_fields.items()) if type(query_fields) is dict else [(v,None) for v in query_fields] if type(query_fields) is list else []
                    if not entries:
                        issue('query.outputs_unresolved',origin,index)
                    for source,alias in entries:
                        if type(source) is dict and len(source)==1 and alias is None:
                            source,alias=next(iter(source.items()))
                        if type(source) is not str or alias is not None and type(alias) is not str:
                            issue('query.field_shape',origin,index,'error'); continue
                        output=alias or source.replace('.','__')
                        obj['outputs'].append({'name':output,'source_field':source,'origin':'query_projection'})
                        dependency(identity,source,'query_field',origin,index)
                    filters=query.get('filters',{})
                    if type(filters) is dict:
                        for source in filters:
                            dependency(identity,source,'query_filter',origin,index)
                    else:
                        issue('query.filters_unqualified',origin,index)
                    if any(k not in ('base_view','topic','fields','filters','sorts','limit') for k in query):
                        issue('query.parameter_preserved_unqualified',origin,index)
                    output_names={o['name'] for o in obj['outputs']}
                    for dimension,field_def in definition.get('dimensions',{}).items() if type(definition.get('dimensions',{})) is dict else []:
                        if type(field_def) is dict and 'sql' not in field_def and dimension not in output_names:
                            issue('query.dimension_output_unresolved',origin,index)
            if 'sql' in definition:
                if type(definition['sql']) is not str:
                    issue('sql.shape',origin,index,'error')
                else:
                    references(definition['sql'],identity,origin,index)
                    issue('sql.output_shape_unqualified',origin,index)
            if len({o['name'] for o in obj['outputs']}) != len(obj['outputs']):
                issue('query.output_collision',origin,index,'error')
        if family=='topic':
            if 'base_view' in definition:
                dependency(identity,definition['base_view'],'topic_base',origin,index)
            topic_views=definition.get('views',{})
            if type(topic_views) is dict:
                for alias, alias_def in topic_views.items():
                    if NAME.fullmatch(alias) and type(alias_def) is dict:
                        add_object('view',alias,alias_def,path,origin,index,parent=identity,subtype='topic_override')
                    else:
                        issue('topic.view_shape',origin,index,'error')
            else:
                issue('topic.views_shape',origin,index,'error')
            joins=definition.get('joins',{})
            stack=[joins]
            while stack:
                item=stack.pop()
                if type(item) is not dict:
                    issue('topic.joins_unqualified',origin,index); continue
                for name,children in item.items():
                    dependency(identity,name,'join',origin,index)
                    if children is not None:
                        stack.append(children)
            for section in ('fields','ai_fields'):
                selected=definition.get(section,[])
                if type(selected) is not list:
                    issue('topic.selector_unqualified',origin,index); continue
                for ref in selected:
                    if type(ref) is str and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*\.[A-Za-z][A-Za-z0-9_]*(?:\[[A-Za-z_]+\])?',ref):
                        dependency(identity,ref,'topic_field',origin,index)
                    else:
                        issue('topic.selector_preserved_unqualified',origin,index)
            if 'topics' in definition:
                members=definition['topics']
                if type(members) is dict:
                    members=list(members)
                if type(members) is list:
                    for name in members:
                        dependency(identity,name,'composite_topic',origin,index)
                else:
                    issue('composite.members_unqualified',origin,index)
                issue('composite.semantics_unqualified',origin,index)
        relationships=definition.get('relationships')
        if relationships is not None:
            add_relationships(relationships,identity,origin,index)
        return obj
    def add_relationships(values,owner,origin,index):
        if type(values) is not list:
            issue('relationships.shape',origin,index,'error'); return
        for relation in values:
            if type(relation) is not dict:
                issue('relationship.shape',origin,index,'error'); continue
            for key in ('join_from_view','join_to_view'):
                dependency(owner,relation.get(key),'relationship_view',origin,index)
            alias=relation.get('join_to_view_as')
            target=relation.get('join_to_view')
            if alias is not None:
                if type(alias) is str and NAME.fullmatch(alias) and type(target) is str:
                    local_views[(owner,alias)] = (origin,'view',target,None)
                else:
                    issue('relationship.alias_shape',origin,index,'error')
            references(relation.get('on_sql'),owner,origin,index)
            references(relation.get('where_sql'),owner,origin,index)
    for origin,items in (('authored',authored),('effective',effective)):
        for index,(path,data) in enumerate(items.items()):
            identity=native_identity(path)
            if identity is None:
                issue('artifact.opaque_preserved',origin,index); continue
            kind,name=identity
            if yaml is None:
                issue('runtime.yaml_unavailable',origin,index); continue
            try:
                definition=_load(data.decode('utf-8'))
            except Exception as error:
                code = str(error) if type(error) is ValueError and str(error) in ('yaml.duplicate_or_non_string_key','yaml.anchors_unsupported') else 'yaml.invalid'
                issue(code,origin,index,'gap' if code=='yaml.anchors_unsupported' else 'error'); continue
            if kind=='relationships':
                obj=add_object(kind,name,definition,path,origin,index)
                add_relationships(definition,obj['id'],origin,index); continue
            if type(definition) is not dict:
                issue('object.shape',origin,index,'error'); continue
            subtype=('modeled_query_view' if 'query' in definition else 'sql_view' if 'sql' in definition else
                     'inherited_view' if 'extends' in definition else 'physical_view' if 'table_name' in definition else 'view_override') if kind in ('view','query_view') else ('composite_topic' if kind=='topic' and 'topics' in definition else kind)
            add_object(kind,name,definition,path,origin,index,subtype=subtype)
    object_map={o['id']:o for o in objects}
    ambiguous_objects={identity for values in indexes.values() if len(values)>1 for identity in values}
    def resolve_view(owner,name,origin,family='view'):
        local=local_views.get((owner,name))
        parent=object_map.get(owner,{}).get('parent_id')
        if local is None and parent:
            local=local_views.get((parent,name))
        if local is not None:
            return indexes.get(local,[]) if type(local) is tuple else [local]
        # Authored references use the separately supplied effective namespace when
        # present; never copy its definitions into the authored byte map.
        if origin=='authored' and effective:
            found=indexes.get(('effective',family,name,None),[])
            if found:return found
        return indexes.get((origin,family,name,None),[])
    def resolve_field(view_id,field_name,seen=None):
        seen=set() if seen is None else seen
        if view_id in seen:return []
        seen=seen|{view_id}
        found=field_indexes.get((view_id,field_name),[])
        if found:return found
        obj=object_map.get(view_id,{})
        definition=obj.get('definition',{})
        parents=definition.get('extends',[]) if type(definition) is dict else []
        inherited=[]
        if type(parents) is list:
            for parent in parents:
                if type(parent) is str:
                    for target in resolve_view(view_id,parent,obj.get('origin')):
                        inherited.extend(resolve_field(target,field_name,seen))
        return sorted(set(inherited))
    edges=[];edge_keys=set()
    for owner,ref,kind,origin,index,source_field in pending:
        base_ref=re.sub(r'\[[A-Za-z_]+\]$','',ref)
        family='topic' if kind in ('query_topic','composite_topic') else 'model' if kind=='extends' and object_map[owner]['kind']=='model' else 'topic' if kind=='extends' and object_map[owner]['kind']=='topic' else 'view'
        if '.' in base_ref:
            view_name,field_name=base_ref.split('.',1)
            targets=[]
            for view_id in resolve_view(owner,view_name,origin):
                targets.extend(resolve_field(view_id,field_name))
        elif kind in ('sql_reference','measure_filter') and source_field:
            targets=resolve_field(owner,base_ref)
        else:
            targets=resolve_view(owner,base_ref,origin,family)
        targets=sorted(set(targets))
        ambiguous=any(t in ambiguous_objects or t.rsplit('/field:',1)[0] in ambiguous_objects for t in targets)
        status='ambiguous' if ambiguous or len(targets)>1 else 'resolved' if targets else 'unresolved'
        edge={'from':source_field or owner,'to':targets[0] if status=='resolved' else None,
              'candidates':targets,'reference':ref,'kind':kind,'status':status}
        edge_key=(edge['from'],edge['to'],tuple(targets),ref,kind,status)
        if edge_key not in edge_keys:
            edges.append(edge);edge_keys.add(edge_key)
        if status!='resolved':issue('dependency.'+status,origin,index)
    adjacency={node['id']:set() for node in objects+fields}
    for field in fields:
        owner=object_map[field['object_id']]
        if owner['subtype'] in ('modeled_query_view','sql_view'):
            adjacency[field['id']].add(owner['id'])
    for edge in edges:
        if edge['status']=='resolved' and edge['kind'] in ('extends','query_base','query_field','sql_reference','composite_topic'):
            target=edge['to'];source=edge['from']
            adjacency.setdefault(source,set()).add(target)
    colors={};cycles=[]
    for start in sorted(adjacency):
        if colors.get(start):continue
        colors[start]=1;stack=[(start,iter(sorted(adjacency[start])))]
        while stack:
            node,children=stack[-1]
            child=next(children,None)
            if child is None:
                colors[node]=2;stack.pop()
            elif colors.get(child)==1:
                cycles.append({'from':node,'to':child})
            elif not colors.get(child):
                colors[child]=1;stack.append((child,iter(sorted(adjacency.get(child,())))))
    if cycles:issue('dependency.cycle','graph',None,'error')
    coverage=_coverage(authored,expected_inventory,context)
    if coverage['status'] in ('mismatch','partial_capture','same_capture_not_independent'):
        issue('coverage.'+coverage['status'],'authored',None)
    result={'schema_version':1,'kind':'omni_inventory','version':VERSION,'context':context,
            'authored_files':encode_files(authored),'effective_files':encode_files(effective),
            'objects':sorted(objects,key=lambda o:(o['id'],o['path'])),
            'fields':sorted(fields,key=lambda f:f['id']),
            'dependencies':sorted(edges,key=lambda e:(e['from'],e['kind'],e['reference'])),
            'cycles':cycles,'coverage':coverage,'findings':findings,
            'status':'invalid' if any(f['severity']=='error' for f in findings) else 'partial' if findings else 'inspected',
            'source_sha256':canonical_hash(encode_files(authored)),
            'effective_sha256':canonical_hash(encode_files(effective)),
            'native_verified':False,'semantics_validated':False,'deployment_authorized':False,'private_only':True}
    result['inventory_sha256']=canonical_hash(result)
    return result


def inspect_model(files, context=None, expected_inventory=None, *, effective_files=None):
    try:
        return _inspect(files,context,expected_inventory,effective_files=effective_files)
    except InventoryError:
        raise
    except (ValueError,TypeError,KeyError,AttributeError,UnicodeError,RecursionError,OverflowError):
        raise InventoryError('inventory.invalid_input') from None


def _pointer(pointer):
    _need(type(pointer) is str and pointer.startswith('/') and pointer != '/' and
          not re.search(r'~(?![01])',pointer), 'patch.pointer')
    parts=[p.replace('~1','/').replace('~0','~') for p in pointer[1:].split('/')]
    _need(all(p and len(p)<=256 for p in parts) and len(parts)<=20, 'patch.pointer')
    return parts


def _lookup(value,parts):
    for part in parts:
        if type(value) is not dict or part not in value:
            return False,None
        value=value[part]
    return True,value


def _editable(parts,value,kind):
    """Leaf-only edits cannot erase opaque descendants through a parent set."""
    if parts[0]=='views':
        _need(kind=='topic' and len(parts)>=3 and NAME.fullmatch(parts[1]),'patch.unsupported_path')
        return _editable(parts[2:],value,'view')
    if parts[0] in ('dimensions','measures'):
        allowed=DIM if parts[0]=='dimensions' else MEASURE
        _need(kind in ('view','query_view') and len(parts)==3 and NAME.fullmatch(parts[1])
              and parts[2] in allowed,'patch.unsupported_path')
    else:
        allowed=VIEW_KEYS if kind in ('view','query_view') else TOPIC_KEYS if kind=='topic' else MODEL_KEYS if kind=='model' else set()
        _need(len(parts)==1 and parts[0] in allowed,'patch.unsupported_path')
    _need(type(value) not in (dict,list) or type(value) is list and
          all(type(item) in (str,bool,int,float) or item is None for item in value),'patch.parent_replacement_refused')


def _set_text(text,parts,value):
    """Replace one node or append a minimal mapping; preserve unrelated bytes."""
    parsed=_load(text) if text.strip() else {}
    _need(type(parsed) is dict,'patch.mapping_required')
    found,previous=_lookup(parsed,parts)
    if found and canonical_hash(previous)==canonical_hash(value):return text
    if not text.strip():
        fragment=value
        for part in reversed(parts):fragment={part:fragment}
        return json.dumps(fragment,ensure_ascii=False)+'\n'
    node=yaml.compose(text,Loader=yaml.SafeLoader);current=parsed
    for depth,part in enumerate(parts):
        _need(isinstance(node,yaml.MappingNode),'patch.mapping_required')
        pair=next(((key,child) for key,child in node.value if key.value==part),None)
        if pair is None:
            fragment=value
            for descendant in reversed(parts[depth+1:]):fragment={descendant:fragment}
            if node.flow_style:
                merged=copy.deepcopy(current);merged[part]=fragment
                return text[:node.start_mark.index]+json.dumps(merged,ensure_ascii=False)+text[node.end_mark.index:]
            end=node.end_mark.index
            prefix='' if end==0 or text[end-1]=='\n' else '\n'
            newline='\r\n' if '\r\n' in text else '\n'
            addition=' '*node.start_mark.column+json.dumps(part,ensure_ascii=False)+': '+json.dumps(fragment,ensure_ascii=False)+newline
            return text[:end]+prefix+addition+text[end:]
        node=pair[1];current=current[part]
        if depth==len(parts)-1:
            replacement=json.dumps(value,ensure_ascii=False)
            previous=text[node.start_mark.index:node.end_mark.index]
            if previous.endswith('\n'):
                replacement += '\r\n' if previous.endswith('\r\n') else '\n'
            return text[:node.start_mark.index]+replacement+text[node.end_mark.index:]
    raise InventoryError('patch.pointer')


def _propose(authored,effective,edits,explicit_deletions):
    original=_files(authored);resolved=_files({} if effective is None else effective)
    _need(type(edits) is list and len(edits)<=1000 and type(explicit_deletions) in (list,tuple), 'patch.edits')
    _bounded(edits);_bounded(list(explicit_deletions))
    candidates=dict(original);diff=[];seen={}
    for edit in edits:
        _need(type(edit) is dict and set(edit)=={'path','pointer','value','expected_sha256'},'patch.edit_shape')
        path=edit['path'];_path(path)
        native=native_identity(path)
        _need(native is not None,'patch.native_path')
        parts=_pointer(edit['pointer'])
        known=VIEW_KEYS if native[0] in ('view','query_view') else TOPIC_KEYS if native[0]=='topic' else MODEL_KEYS if native[0]=='model' else set()
        _need(parts[0] in known,'patch.opaque_parameter')
        _editable(parts,edit['value'],native[0])
        for previous in seen.setdefault(path,[]):
            _need(parts[:len(previous)]!=previous and previous[:len(parts)]!=parts,'patch.overlapping_edits')
        seen[path].append(parts)
        expected=_sha(original[path]) if path in original else None
        _need(edit['expected_sha256']==expected,'patch.authored_changed')
        if yaml is None:raise InventoryError('patch.yaml_unavailable')
        text=candidates.get(path,b'').decode('utf-8')
        # Effective-only no-op remains inherited and creates no authored file.
        authored_value=_load(text) if text.strip() else {}
        prior_found,prior_value=_lookup(authored_value,parts)
        _need(not prior_found or type(prior_value) not in (dict,list) or type(prior_value) is list and
              all(type(item) in (str,bool,int,float) or item is None for item in prior_value),
              'patch.parent_replacement_refused')
        authored_has,_=_lookup(authored_value,parts)
        if not authored_has and path in resolved:
            matched,prior=_lookup(_load(resolved[path].decode('utf-8')),parts)
            if matched and canonical_hash(prior)==canonical_hash(edit['value']):continue
        changed=_set_text(text,parts,edit['value'])
        _load(changed)  # Detect malformed insertion before emitting a candidate.
        if changed != text:
            candidates[path]=changed.encode('utf-8')
            diff.append({'path':path,'operation':'set','pointer':edit['pointer'],
                         'origin':'authored' if path in original else 'new_authored_override' if path in resolved else 'new_authored',
                         'old_sha256':expected,'new_value_sha256':canonical_hash(edit['value'])})
    deleted=set()
    for deletion in explicit_deletions:
        _need(type(deletion) is dict and set(deletion)=={'path','expected_sha256'},'patch.deletion_shape')
        path=deletion['path'];_path(path)
        _need(path in original and path not in seen and path not in deleted,'patch.deletion_scope')
        _need(deletion['expected_sha256']==_sha(original[path]),'patch.authored_changed')
        deleted.add(path);del candidates[path]
        diff.append({'path':path,'operation':'propose_remove_authored_file','old_sha256':_sha(original[path]),
                     'effective_definition_may_remain':path in resolved})
    # Partial editing never imports any untouched resolved/effective definition.
    result={'schema_version':1,'kind':'omni_patch_proposal','version':VERSION,
            'authored_sha256':canonical_hash(encode_files(original)),
            'effective_sha256':canonical_hash(encode_files(resolved)),
            'candidate_files':encode_files(candidates),'candidate_sha256':canonical_hash(encode_files(candidates)),
            'diff':diff,'explicit_deletions':sorted(deleted),'changed_files':sorted({d['path'] for d in diff}),
            'status':'proposed' if diff else 'no_op','applied':False,'deletion_authorized':False,
            'deployment_authorized':False,'native_verified':False,'private_only':True}
    result['proposal_sha256']=canonical_hash(result)
    return result


def propose_patch(authored,effective,edits,*,explicit_deletions=()):
    """Pure proposal: hash-bound JSON-pointer sets + explicit file removals.

    Only mapping paths are editable. Arrays can be explicitly replaced at their
    mapping key; array-index patches and whole-document replacement are refused.
    Returned candidate_files are byte records; decode_files restores exact bytes.
    Even explicit deletions are only proposed, never applied or authorized.
    """
    try:
        return _propose(authored,effective,edits,explicit_deletions)
    except InventoryError:
        raise
    except Exception:
        raise InventoryError('patch.invalid_or_unsupported') from None


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('inspect','propose'))
    parser.add_argument('--request',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        _need(args.request.is_file() and not args.request.is_symlink() and not any(p.is_symlink() for p in args.request.parents)
              and args.request.stat().st_size<=MAX_BYTES,'inventory.request')
        from verify_specialist_results import read_json
        request=read_json(args.request)
        if args.operation=='inspect':
            _need(type(request) is dict and set(request)<= {'files','context','expected_inventory','effective_files'} and 'files' in request,'inventory.request')
            result=inspect_model(**request)
        else:
            _need(type(request) is dict and set(request)<={'authored','effective','edits','explicit_deletions'} and {'authored','effective','edits'}<=set(request),'inventory.request')
            result=propose_patch(**request)
        _need(not args.output.is_symlink() and not any(p.is_symlink() for p in args.output.parents),'inventory.output')
        import os
        fd=os.open(args.output,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as handle:json.dump(result,handle,sort_keys=True,indent=2)
        print(json.dumps({'status':result['status'],'kind':result['kind'],'native_verified':False,'private_only':True}));return 0
    except Exception:
        print(json.dumps({'status':'blocked','code':'inventory.request_or_proposal_failed'}));return 2


if __name__=='__main__':
    raise SystemExit(main())
