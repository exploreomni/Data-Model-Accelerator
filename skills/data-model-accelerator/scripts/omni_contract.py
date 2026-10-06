"""Bounded Omni static checks, never a replacement for Omni native validation.

No SQL is executed. Diagnostics contain locations and codes, never source SQL,
literal values or parser exception text. Catalogue and inheritance observations
are supplied context, not authenticated warehouse access or security proof.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

try:
    import yaml
except ImportError:
    yaml = None
try:
    import sqlglot
    from sqlglot import exp
except ImportError:
    sqlglot = exp = None

CONTRACT_VERSION = 'omni-static-v2-2026-10-05'
MAX_FILES, MAX_BYTES, MAX_NODES, MAX_DEPTH = 256, 8 * 1024 * 1024, 100000, 40
NAME = re.compile(r'[A-Za-z][A-Za-z0-9_]*\Z')
SHA = re.compile(r'[0-9a-f]{64}\Z')
REF = re.compile(r'\$\{([^{}]+)\}')
FIELD = re.compile(r'(?:(?P<view>[A-Za-z][A-Za-z0-9_]*)\.)?(?P<field>[A-Za-z][A-Za-z0-9_]*)(?:\[(?P<time>[A-Za-z_]+)\])?\Z')
TIMEFRAMES = set('date day_of_month day_of_quarter day_of_week_name day_of_week_num day_of_year fiscal_quarter fiscal_year hour hour_of_day millisecond minute month month_name month_num quarter quarter_of_year raw second week year'.split())
WEEKDAYS = set('Monday Tuesday Wednesday Thursday Friday Saturday Sunday'.split())
AGGREGATES = set('sum count count_distinct average min max median list percentile sum_distinct_on average_distinct_on median_distinct_on percentile_distinct_on'.split())
DIALECTS = {'snowflake':'snowflake', 'bigquery':'bigquery', 'databricks':'databricks',
            'redshift':'redshift', 'clickhouse':'clickhouse', 'motherduck':'duckdb'}
NAMESPACE = {'snowflake':('database','schema','table'), 'redshift':('database','schema','table'),
             'motherduck':('database','schema','table'), 'databricks':('catalog','schema','table'),
             'bigquery':('project','dataset','table'), 'clickhouse':('database','table')}
TEXT = {'label','description','ai_context','group_label','view_label','schema_label','folder','base_view_label'}
BOOL = {'hidden','ignored','primary_key','convert_tz','template','auto_run'}
LIST = {'tags','synonyms','aliases','required_access_grants'}
COMMON = TEXT | {'hidden','ignored','tags','required_access_grants','display_order'}
DIM = COMMON | {'sql','primary_key','convert_tz','timeframes','week_start_day','format','aliases','synonyms','order_by_field'}
MEASURE = COMMON | {'sql','aggregate_type','format','aliases','synonyms','filters','percentile','custom_primary_key_sql'}
VIEW = COMMON | {'name','catalog','schema','table_name','extends','dimensions','measures','query','sql'}
TOPIC = COMMON | {'base_view','joins','relationships','fields','ai_fields','access_filters','week_start_day','default_row_limit','views','extends','default_filters','always_where_filters'}
MODEL = {'week_start_day','label','description','ai_context','fiscal_month_offset','default_timeframes'}
RELATION = {'join_from_view','join_to_view','join_type','on_sql','relationship_type','reversible'}


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _text(value):
    return type(value) is str and bool(value.strip())


def _sha(value):
    return type(value) is str and bool(SHA.fullmatch(value))


def _names(value):
    return type(value) is list and all(type(x) is str and NAME.fullmatch(x) for x in value) and len(set(value)) == len(value)


def _bounded(value):
    pending, count, size = [(value, 0, frozenset())], 0, 0
    while pending:
        item, depth, seen = pending.pop(); count += 1
        if depth > MAX_DEPTH or count > MAX_NODES:
            raise ValueError('input.structure_limit')
        if type(item) is str:
            size += len(item.encode('utf-8'))
            if size > MAX_BYTES: raise ValueError('input.byte_limit')
            continue
        if item is None or type(item) in (int, bool):
            continue
        if type(item) is float:
            if item != item or abs(item) == float('inf'):
                raise ValueError('input.nonfinite')
            continue
        if type(item) not in (list, dict) or id(item) in seen:
            raise ValueError('input.non_json_or_cyclic')
        children = list(item.values()) if type(item) is dict else item
        if type(item) is dict and not all(type(k) is str for k in item):
            raise ValueError('input.non_string_key')
        if count + len(children) > MAX_NODES: raise ValueError('input.structure_limit')
        pending.extend((child, depth + 1, seen | {id(item)}) for child in children)


def _load(text):
    class Strict(yaml.SafeLoader):
        pass
    def mapping(loader, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if type(key) is not str or key in result:
                raise ValueError('yaml.duplicate_or_non_string_key')
            result[key] = loader.construct_object(value_node, deep=deep)
        return result
    Strict.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    if any(isinstance(t, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken)) for t in yaml.scan(text)):
        raise ValueError('yaml.anchors_unsupported')
    result = yaml.load(text, Loader=Strict)
    _bounded(result)
    return result


def _merge(base, override):
    result = copy.deepcopy(base)
    for key, value in override.items():
        if type(value) is dict and type(result.get(key)) is dict:
            result[key] = _merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def check_model(files, context=None, *, _scoped=False):
    """Check the documented bounded subset; unknown behavior is unsupported.

    files is the exact complete native candidate, keyed by relative model paths.
    See references/omni-static-contract.md for context v1 and qualification limits.
    """
    findings = []
    report = {'schema_version':1, 'kind':'omni_static_check', 'status':'passed',
              'contract_version':CONTRACT_VERSION, 'candidate_sha256':None, 'context_sha256':None,
              'native_verified':False, 'security_verified':False, 'findings':findings, 'topic_scopes':{},
              'limitations':['Static subset only; SQL lint, native compilation, cardinality, access and business parity require separate evidence.',
                             'Context evidence and reviewed declarations are not authenticated observations.',
                             'Implicit whitelist dependency eligibility requires native qualification; direct field exclusions and explicit negative dependencies are checked.']}
    def issue(code, path='context', location='/', unsupported=False):
        item = {'path':path, 'location':location, 'code':code,
                'severity':'unsupported' if unsupported else 'error'}
        if item not in findings:
            findings.append(item)
    def finish():
        report['status'] = 'failed' if any(f['severity']=='error' for f in findings) else 'unsupported' if findings else 'passed'
        return report
    if (type(files) is not dict or not 0 < len(files) <= MAX_FILES
            or not all(type(k) is str and type(v) is str for k,v in files.items())):
        issue('input.files'); return finish()
    try:
        if sum(len(k.encode())+len(v.encode()) for k,v in files.items()) > MAX_BYTES:
            issue('input.byte_limit'); return finish()
        report['candidate_sha256'] = canonical_hash(files)
    except (ValueError, UnicodeError, OverflowError):
        issue('input.encoding'); return finish()
    if yaml is None:
        issue('runtime.yaml_unavailable', unsupported=True); return finish()
    definitions, paths, topics, model, global_relations = {}, {}, {}, {}, []
    models_seen, rel_seen, all_names = False, False, set()
    for index, (path, text) in enumerate(sorted(files.items())):
        relative = PurePosixPath(path)
        if (not re.fullmatch(r'[A-Za-z0-9_./-]+', path) or relative.is_absolute()
                or '..' in relative.parts or str(relative) != path):
            issue('input.path', 'artifact['+str(index)+']'); continue
        name = relative.name
        if name.endswith(('.yaml','.yml')):
            name = name.rsplit('.',1)[0]
        kind = 'view' if name.endswith('.view') else 'topic' if name.endswith('.topic') else name
        identity = name[:-len('.query.view')] if name.endswith('.query.view') else name.rsplit('.',1)[0] if kind in ('view','topic') else name
        if kind not in ('view','topic','model','relationships'):
            issue('artifact.unsupported', path, unsupported=True); continue
        if (kind, identity) in all_names:
            issue('artifact.duplicate_identity', path); continue
        all_names.add((kind, identity))
        if kind in ('view','topic') and not NAME.fullmatch(identity):
            issue('artifact.name', path); continue
        try:
            obj = _load(text)
        except ValueError as error:
            code = str(error) if str(error).startswith(('yaml.','input.')) else 'yaml.invalid'
            issue(code, path, unsupported=code=='yaml.anchors_unsupported'); continue
        except (yaml.YAMLError, RecursionError, TypeError, UnicodeError):
            issue('yaml.invalid', path); continue
        if kind == 'relationships':
            global_relations = obj; rel_seen = True
        elif type(obj) is not dict:
            issue('object.mapping_required', path)
        elif kind == 'view':
            definitions[identity], paths[identity] = obj, path
        elif kind == 'topic':
            topics[identity] = (obj,path)
        else:
            model, model_path, models_seen = obj, path, True

    valid_context = True
    if context is None:
        context = {}; valid_context = False; issue('context.required', unsupported=True)
    else:
        try:
            _bounded(context)
            report['context_sha256'] = canonical_hash(context)
        except (ValueError, TypeError, OverflowError, RecursionError):
            valid_context = False; issue('context.invalid'); context = {}
    required = {'schema_version','kind','warehouse','environment','catalogue_sha256','bindings','inherited_views','default_catalog','user_attributes','access_grants'}
    if valid_context and (type(context) is not dict or set(context) != required
            or type(context.get('schema_version')) is not int or context['schema_version'] != 1
            or context.get('kind') != 'omni_model_context' or type(context.get('warehouse')) is not str or context['warehouse'] not in DIALECTS
            or not _text(context.get('environment')) or not _sha(context.get('catalogue_sha256'))
            or type(context.get('bindings')) is not dict or type(context.get('inherited_views')) is not dict
            or not _names(context.get('user_attributes')) or not _names(context.get('access_grants'))):
        issue('context.invalid'); valid_context = False
    if not valid_context:
        context = {'bindings':{},'inherited_views':{},'default_catalog':None,'user_attributes':[],'access_grants':[]}
    warehouse = context.get('warehouse')
    bindings = context['bindings']; inherited = context['inherited_views']
    default = context['default_catalog']
    if default is not None and (type(default) is not dict or set(default) != {'value','verified','evidence_sha256'}
            or not _text(default.get('value')) or default.get('verified') is not True or not _sha(default.get('evidence_sha256'))):
        issue('context.default_catalog_unverified'); default = None
    for name, item in list(bindings.items()):
        valid = (type(name) is str and NAME.fullmatch(name) and type(item) is dict
                 and set(item)=={'namespace','columns','evidence_sha256'} and _sha(item.get('evidence_sha256'))
                 and type(item.get('namespace')) is dict and set(item['namespace'])==set(NAMESPACE.get(warehouse,()))
                 and all(_text(v) for v in item['namespace'].values()) and type(item.get('columns')) is dict
                 and all(_text(k) and type(v) is str and v in ('string','number','date','timestamp','boolean','unknown') for k,v in item['columns'].items()))
        if not valid:
            issue('context.binding_invalid'); valid_context = False
    if not valid_context:
        bindings = {}
    for name, item in inherited.items():
        if (type(name) is not str or not NAME.fullmatch(name) or type(item) is not dict
                or set(item) != {'definition','sha256'} or type(item['definition']) is not dict
                or not _sha(item['sha256']) or canonical_hash(item['definition']) != item['sha256']):
            issue('context.inherited_invalid'); continue
        definitions[name] = _merge(item['definition'], definitions.get(name, {}))
        paths.setdefault(name, 'context')

    def keys(obj, allowed, path, loc):
        for key in obj:
            if key not in allowed:
                issue('parameter.unsupported', path, loc, unsupported=True)
        for key in TEXT & set(obj):
            if type(obj[key]) is not str: issue('parameter.string_required',path,loc+'/'+key)
        for key in BOOL & set(obj):
            if type(obj[key]) is not bool: issue('parameter.boolean_required',path,loc+'/'+key)
        for key in LIST & set(obj):
            if type(obj[key]) is not list or not all(type(v) is str for v in obj[key]):
                issue('parameter.string_list_required',path,loc+'/'+key)
        if 'week_start_day' in obj and (type(obj['week_start_day']) is not str or obj['week_start_day'] not in WEEKDAYS):
            issue('parameter.week_start_day',path,loc+'/week_start_day')
        if 'display_order' in obj and type(obj['display_order']) not in (int,float):
            issue('parameter.display_order',path,loc+'/display_order')
        if 'format' in obj:
            if type(obj['format']) is dict:
                issue('format.conditional_unqualified',path,loc+'/format',True)
            elif not _text(obj['format']): issue('format.string_required',path,loc+'/format')
            elif '{{' in obj['format']: issue('format.template_unqualified',path,loc+'/format',True)
        if 'required_access_grants' in obj and type(obj['required_access_grants']) is list:
            if any(type(g) is not str or g not in context['access_grants'] for g in obj['required_access_grants']):
                issue('access.grant_unresolved',path,loc+'/required_access_grants')
    if models_seen:
        keys(model, MODEL, model_path, '')
        if 'fiscal_month_offset' in model and type(model['fiscal_month_offset']) is not int:
            issue('calendar.fiscal_offset_unqualified',model_path,'/fiscal_month_offset',True)
        if 'default_timeframes' in model and (type(model['default_timeframes']) is not list or
                any(type(v) is not str or v.lower() not in TIMEFRAMES for v in model['default_timeframes'])):
            issue('calendar.default_timeframes',model_path,'/default_timeframes')

    resolved_topics={}; topic_visiting=set()
    def resolve_topic(name):
        if name in resolved_topics:return resolved_topics[name]
        if name in topic_visiting or len(topic_visiting)>MAX_DEPTH:
            issue('topic.inheritance_cycle',topics[name][1]);return {}
        obj,path=topics[name]; topic_visiting.add(name); combined={}
        if 'extends' in obj:
            parents=obj['extends']
            if not _names(parents):issue('topic.inheritance_shape',path,'/extends')
            elif len(parents)!=1:issue('topic.multiple_inheritance_unqualified',path,'/extends',True)
            elif parents[0] not in topics:issue('topic.inheritance_unresolved',path,'/extends')
            else:combined=resolve_topic(parents[0])
        combined=_merge(combined,obj);combined.pop('extends',None)
        topic_visiting.remove(name);resolved_topics[name]=combined;return combined
    for name in topics:resolve_topic(name)

    bindings=copy.deepcopy(bindings)
    resolved, visiting = {}, set()
    def resolve_view(name):
        if name in resolved: return resolved[name]
        if name in visiting:
            issue('inheritance.cycle', paths.get(name,'context')); return {}
        if len(visiting)>MAX_DEPTH:
            issue('inheritance.depth',paths.get(name,'context'),unsupported=True); return {}
        obj = definitions.get(name)
        if obj is None:
            issue('inheritance.unresolved', unsupported=True); return {}
        visiting.add(name); combined = {}
        if 'extends' in obj:
            if not _names(obj['extends']): issue('inheritance.invalid', paths[name], '/extends')
            elif len(obj['extends']) > 1: issue('inheritance.multiple_unqualified', paths[name], '/extends',True)
            else:
                for base in obj['extends']:
                    combined = _merge(combined,resolve_view(base))
                    if name not in bindings and base in bindings:bindings[name]=copy.deepcopy(bindings[base])
        combined = _merge(combined,obj); visiting.remove(name); resolved[name] = combined
        return combined
    for name in definitions: resolve_view(name)
    derived_columns={}
    if any('query' in obj or 'sql' in obj for obj in resolved.values()):
        from omni_query_views import analyze_query_views
        query_report=analyze_query_views(files,context)
        report['query_views']=query_report['descriptors']
        for finding in query_report['findings']:
            issue(finding['code'],finding['path'],finding['location'],finding['severity']=='unsupported')
        for name,descriptor in query_report['descriptors'].items():
            derived_columns[name]={o['sql_identifier']:o['datatype'] for o in descriptor['outputs'].values()}
    def column_set(view):
        return derived_columns.get(view,bindings.get(view,{}).get('columns',{}))
    fields, field_paths, edges, temporal = {}, {}, {}, {}
    for view, obj in resolved.items():
        path = paths.get(view,'context'); keys(obj,VIEW,path,'')
        if 'name' in obj and obj['name'] != view: issue('view.name_mismatch',path,'/name')
        binding = bindings.get(view)
        derived='query' in obj or 'sql' in obj
        if derived:
            if binding is not None:issue('query.physical_binding_forbidden',path)
        elif binding is None:
            issue('binding.view_unresolved',path,unsupported=not valid_context)
        else:
            ns = binding['namespace']; catalog = ns.get('database',ns.get('catalog',ns.get('project')))
            schema = ns.get('schema',ns.get('dataset'))
            for prop, expected in (('catalog',catalog),('schema',schema),('table_name',ns['table'])):
                actual = obj.get(prop)
                if prop=='catalog' and actual is None and default is not None: actual=default['value']
                if expected is None:
                    if actual is not None: issue('binding.namespace_mismatch',path,'/'+prop)
                elif actual is None: issue('binding.namespace_unresolved',path,'/'+prop)
                elif actual != expected: issue('binding.namespace_mismatch',path,'/'+prop)
        for category, allowed in (('dimensions',DIM),('measures',MEASURE)):
            declared = obj.get(category,{})
            if type(declared) is not dict: issue('field.mapping_required',path,'/'+category); continue
            for name, definition in declared.items():
                loc = '/'+category+'/'+(name if NAME.fullmatch(name) else '?')
                if not NAME.fullmatch(name): issue('field.name',path,loc); continue
                if type(definition) is not dict: issue('field.object_required',path,loc); continue
                qualified = view+'.'+name
                if qualified in fields: issue('field.duplicate_identity',path,loc); continue
                fields[qualified] = (category,definition,view); field_paths[qualified]=(path,loc); edges[qualified]=set()
                keys(definition,allowed,path,loc)
                if 'type' in definition or 'aggregate_type' in definition and category=='dimensions':
                    issue('field.parameter_placement',path,loc)
                if 'timeframes' in definition:
                    values=definition['timeframes']
                    if type(values) is not list or any(type(v) is not str or v.lower() not in TIMEFRAMES for v in values):
                        issue('field.timeframe',path,loc+'/timeframes')
                    elif any(v.lower() in ('fiscal_quarter','fiscal_year') for v in values) and type(model.get('fiscal_month_offset')) is not int:
                        issue('calendar.fiscal_offset_required',path,loc+'/timeframes')
                if category=='measures':
                    agg=definition.get('aggregate_type')
                    if agg is not None and (type(agg) is not str or agg not in AGGREGATES): issue('measure.aggregate_type',path,loc+'/aggregate_type')
                    if type(agg) is str and 'percentile' in agg and (type(definition.get('percentile')) not in (int,float) or not 0<=definition['percentile']<=100):
                        issue('measure.percentile',path,loc+'/percentile')
                    if type(agg) is str and agg.endswith('_distinct_on') and not _text(definition.get('custom_primary_key_sql')):
                        issue('measure.deduplication_key_required',path,loc)
                if 'sql' not in definition and category=='dimensions':
                    columns=column_set(view)
                    matches=[c for c in columns if c==name or warehouse=='snowflake' and c==name.upper()]
                    if len(matches)!=1: issue('field.definition_unresolved',path,loc,True)
                    elif columns[matches[0]] in ('date','timestamp'): temporal[qualified]=True
                elif category=='measures' and not _text(definition.get('sql')) and definition.get('aggregate_type')!='count':
                    issue('field.definition_unresolved',path,loc,True)

    def reference(text, current, path, loc, scope=None):
        match=FIELD.fullmatch(text) if type(text) is str else None
        if not match: issue('reference.invalid',path,loc); return None
        view=match['view'] or current; target=(view or '')+'.'+match['field']
        if target not in fields: issue('reference.unresolved',path,loc); return None
        if scope is not None and view not in scope: issue('reference.view_outside_topic',path,loc)
        if match['time']:
            if match['time'].lower() not in TIMEFRAMES: issue('reference.timeframe',path,loc)
            if match['time'].lower() in ('fiscal_year','fiscal_quarter') and type(model.get('fiscal_month_offset')) is not int:
                issue('calendar.fiscal_offset_required',path,loc)
            if fields[target][0]!='dimensions': issue('reference.timeframe_on_measure',path,loc)
            elif target not in temporal: issue('reference.temporal_type_unresolved',path,loc,True)
        if fields[target][1].get('ignored') is True: issue('reference.ignored_field',path,loc)
        return target

    def sql_check(value, current, path, loc, field_id=None, scope=None, aggregate=None):
        if not _text(value): issue('sql.string_required',path,loc); return
        if '__dma_ref_' in value:
            issue('sql.reserved_marker',path,loc,True); return
        refs=[]
        def replace(match):
            target=reference(match[1],current,path,loc,scope)
            refs.append(target)
            if field_id and target: edges[field_id].add(target)
            return '__dma_ref_'+str(len(refs)-1)
        cooked=REF.sub(replace,value)
        if '${' in cooked: issue('reference.invalid',path,loc); return
        if '{{' in cooked or '{%' in cooked: issue('sql.template_unqualified',path,loc,True); return
        if sqlglot is None or warehouse is None: issue('sql.runtime_or_dialect_unavailable',path,loc,True); return
        try:
            trees=sqlglot.parse(cooked,read=DIALECTS[warehouse],error_message_context=0)
        except Exception:
            issue('sql.invalid_expression',path,loc); return
        if len(trees)!=1 or trees[0] is None: issue('sql.single_expression_required',path,loc); return
        tree=trees[0]
        if any(isinstance(n,(exp.Query,exp.DDL,exp.DML,exp.Command,exp.Subquery)) for n in tree.walk()):
            issue('sql.statement_unqualified',path,loc,True); return
        if aggregate is not None and any(isinstance(n,exp.AggFunc) for n in tree.walk()): issue('measure.nested_aggregate',path,loc)
        if any(isinstance(n,exp.Anonymous) for n in tree.walk()): issue('sql.function_unqualified',path,loc,True)
        for target in refs:
            if target and fields[target][0]=='measures' and aggregate is not None:
                issue('measure.nested_aggregate_reference',path,loc)
        for node in tree.find_all(exp.Column):
            if node.name.startswith('__dma_ref_') and not node.table:
                target=refs[int(node.name[len('__dma_ref_'):])]
                if target and fields[target][0]=='measures' and node.find_ancestor(exp.AggFunc):
                    issue('measure.nested_aggregate_reference',path,loc)
                continue
            columns=column_set(current)
            if node.table or node.db or node.catalog: issue('sql.physical_qualification_unqualified',path,loc,True); continue
            quoted=bool(node.this.args.get('quoted'))
            name=node.name.upper() if warehouse=='snowflake' and not quoted else node.name
            if name not in columns: issue('sql.physical_column_unresolved',path,loc)
            elif field_id and columns[name] in ('date','timestamp'): temporal[field_id]=True
        if field_id and fields[field_id][0]=='dimensions' and any(isinstance(n,exp.AggFunc) for n in tree.walk()):
            issue('dimension.aggregate_unqualified',path,loc,True)
        if field_id and fields[field_id][0]=='dimensions' and type(tree) is exp.Column and not refs:
            columns=column_set(current)
            physical=tree.name.upper() if warehouse=='snowflake' and not tree.this.args.get('quoted') else tree.name
            if (fields[field_id][1].get('timeframes') or 'week_start_day' in fields[field_id][1]) and columns.get(physical) not in ('date','timestamp','unknown',None):
                issue('field.timeframe_non_temporal',path,loc)
    def filters_check(value,current,path,loc,field_id=None,scope=None):
        if type(value) is not dict:
            issue('filter.mapping_required',path,loc);return
        for ref,condition in value.items():
            target=reference(ref,current,path,loc,scope)
            if target:
                if field_id:edges[field_id].add(target)
                if fields[target][0]!='dimensions':issue('filter.dimension_required',path,loc)
            if type(condition) is not dict or len(condition)!=1:
                issue('filter.condition_unqualified',path,loc,True);continue
            operator,operand=next(iter(condition.items()))
            if operator in ('is','not'):
                values=operand if type(operand) is list else [operand]
                if not all(v is None or type(v) in (str,int,float,bool) for v in values):issue('filter.value_shape',path,loc)
                if any(type(v) is str and ('{{' in v or '${' in v) for v in values):issue('filter.dynamic_unqualified',path,loc,True)
            elif operator in ('greater_than','greater_than_or_equal_to','less_than','less_than_or_equal_to'):
                if type(operand) not in (int,float):issue('filter.numeric_required',path,loc)
            elif operator in ('contains','not_contains','starts_with','not_starts_with','ends_with','not_ends_with'):
                if type(operand) is not str:issue('filter.string_required',path,loc)
                elif '{{' in operand or '${' in operand:issue('filter.dynamic_unqualified',path,loc,True)
            else:issue('filter.operator_unqualified',path,loc,True)

    # First validate physical SQLs to establish temporal catalogue types before
    # resolving references to their bracket timeframes.
    for qualified,(category,definition,view) in fields.items():
        value=definition.get('sql'); path,loc=field_paths[qualified]
        if value is not None and type(value) is str and not REF.search(value):
            sql_check(value,view,path,loc+'/sql',qualified,aggregate=definition.get('aggregate_type'))
    for qualified,(category,definition,view) in fields.items():
        path,loc=field_paths[qualified]; value=definition.get('sql')
        if value is not None and (type(value) is not str or REF.search(value)):
            sql_check(value,view,path,loc+'/sql',qualified,aggregate=definition.get('aggregate_type'))
        if 'custom_primary_key_sql' in definition:
            sql_check(definition['custom_primary_key_sql'],view,path,loc+'/custom_primary_key_sql',qualified)
        if 'order_by_field' in definition: reference(definition['order_by_field'],view,path,loc+'/order_by_field')
        if 'filters' in definition: filters_check(definition['filters'],view,path,loc+'/filters',qualified)
    def cycles(graph, code):
        pending={k:set(v) for k,v in graph.items()}; ready=[k for k,v in pending.items() if not v]; dependents={}
        for child,parents in pending.items():
            for parent in parents: dependents.setdefault(parent,set()).add(child)
        while ready:
            node=ready.pop(); pending.pop(node,None)
            for key in dependents.get(node,()):
                if key in pending:
                    pending[key].discard(node)
                    if not pending[key]: ready.append(key)
        for key in pending:
            path,loc=field_paths[key]; issue(code,path,loc)
    cycles(edges,'reference.cycle')

    def relationships(value,path,loc):
        links=set()
        if type(value) is not list: issue('relationship.list_required',path,loc); return links
        for index,item in enumerate(value):
            at=loc+'/'+str(index)
            if type(item) is not dict: issue('relationship.object_required',path,at); continue
            keys(item,RELATION,path,at)
            left,right=item.get('join_from_view'),item.get('join_to_view')
            if type(left) is not str or left not in resolved or type(right) is not str or right not in resolved:
                issue('relationship.view_unresolved',path,at); continue
            if (left,right) in links: issue('relationship.ambiguous',path,at)
            links.add((left,right))
            if item.get('reversible') is True: links.add((right,left))
            if 'reversible' in item and type(item['reversible']) is not bool: issue('parameter.boolean_required',path,at+'/reversible')
            if item.get('join_type') not in ('left','inner','full_outer','always_left','always_inner'):
                issue('relationship.join_type_unqualified',path,at+'/join_type',True)
            if item.get('relationship_type') not in ('many_to_one','one_to_many','one_to_one','many_to_many','assumed_many_to_one'):
                issue('relationship.cardinality',path,at+'/relationship_type')
            sql_check(item.get('on_sql'),left,path,at+'/on_sql',scope={left,right})
        return links
    global_links=relationships(global_relations,'relationships','') if rel_seen else set()
    for topic_name,(_,path) in topics.items():
        topic=resolved_topics[topic_name]
        if 'views' in topic:
            overrides=topic['views']
            if _scoped or type(overrides) is not dict:
                issue('topic.views_shape',path,'/views');continue
            scoped_files={p:t for p,t in files.items() if not p.removesuffix('.yaml').removesuffix('.yml').endswith('.topic')}
            scoped_context=copy.deepcopy(context);scoped_context['bindings']=copy.deepcopy(bindings)
            for alias,definition in overrides.items():
                if not NAME.fullmatch(alias) or type(definition) is not dict:
                    issue('topic.view_shape',path,'/views');continue
                existing=resolved.get(alias,{})
                scoped_definition=_merge(existing,definition)
                existing_path=paths.get(alias)
                if existing_path in scoped_files:scoped_files.pop(existing_path)
                scoped_files[alias+'.view']=yaml.safe_dump(scoped_definition,sort_keys=True)
            flat=copy.deepcopy(topic);flat.pop('views')
            scoped_files[path]=yaml.safe_dump(flat,sort_keys=True)
            scoped=check_model(scoped_files,scoped_context,_scoped=True)
            for finding in scoped['findings']:
                issue(finding['code'],path,'/views'+finding['location'],finding['severity']=='unsupported')
            report['topic_scopes'][topic_name]=scoped['topic_scopes'].get(topic_name,{})
            continue
        keys(topic,TOPIC,path,''); base=topic.get('base_view')
        if type(base) is not str or base not in resolved:
            issue('topic.base_view_unresolved',path,'/base_view'); continue
        links=global_links|relationships(topic.get('relationships',[]),path,'/relationships'); included={base}
        if 'joins' not in topic and links: issue('topic.implicit_joins_unqualified',path,'/joins',True)
        def joins(tree,parent,trail,loc):
            if type(tree) is not dict: issue('topic.joins_mapping_required',path,loc); return
            for child,nested in tree.items():
                at=loc+'/'+(child if NAME.fullmatch(child) else '?')
                if child not in resolved: issue('topic.join_view_unresolved',path,at); continue
                if child in trail: issue('topic.join_cycle',path,at); continue
                if child in included: issue('topic.join_ambiguous',path,at)
                included.add(child)
                if (parent,child) not in links: issue('topic.relationship_unresolved',path,at)
                joins(nested,child,trail|{child},at)
        joins(topic.get('joins',{}),base,{base},'/joins')
        selections={}
        for key in ('fields','ai_fields'):
            if key in topic:
                if type(topic[key]) is not list: issue('topic.field_list_required',path,'/'+key)
                else:
                    ordered=[];selected=set();excluded=set()
                    for index,value in enumerate(topic[key]):
                        loc='/'+key+'/'+str(index)
                        if type(value) is not str:issue('topic.selector_shape',path,loc);continue
                        negative=value.startswith('-');selector=value[1:] if negative else value
                        matches=set();rank=5
                        if selector=='all_views.*':rank=1;matches={f for f in fields if fields[f][2] in included}
                        elif selector.endswith('.*'):
                            rank=2;view=selector[:-2]
                            if view not in included:issue('reference.view_outside_topic',path,loc)
                            matches={f for f in fields if fields[f][2]==view}
                        elif ':tag:' in selector or selector.startswith('tag:'):
                            rank=4 if ':tag:' in selector else 3
                            view,tag=selector.split(':tag:',1) if rank==4 else (None,selector[4:])
                            if not tag or view is not None and view not in included:issue('topic.selector_unresolved',path,loc)
                            matches={f for f,(_,d,v) in fields.items() if v in included and (view is None or v==view) and
                                     (tag in d.get('tags',[]) or tag in resolved[v].get('tags',[]))}
                        else:
                            target=reference(selector,base,path,loc,included)
                            if target:matches={target}
                        ordered.append((rank,index,negative,matches))
                    for _,_,negative,matches in sorted(ordered):
                        if negative:selected-=matches;excluded|=matches
                        else:selected|=matches;excluded-=matches
                    for field in selected:
                        todo=list(edges[field]);seen=set()
                        while todo:
                            dependency=todo.pop()
                            if dependency in seen:continue
                            seen.add(dependency);todo.extend(edges.get(dependency,()))
                        if key=='fields' and seen & excluded:issue('topic.excluded_dependency',path,'/'+key)
                    selections[key]=sorted(selected)
        all_reachable={f for f,(_,definition,v) in fields.items() if v in included and not definition.get('ignored')}
        selections.setdefault('fields',sorted(all_reachable))
        selections.setdefault('ai_fields',list(selections['fields']))
        for selected in selections['fields']:
            if any(fields[d][2] not in included for d in edges.get(selected,()) if d in fields):
                issue('topic.dependency_view_unreachable',path,'/fields')
        report['topic_scopes'][topic_name]={'views':sorted(included),'selections':selections,
                 'selection_origins':{key:'explicit' if key in topic else 'default' for key in ('fields','ai_fields')},
                 'ai_fields_is_access_control':False}
        for key in ('default_filters','always_where_filters'):
            if key in topic:filters_check(topic[key],base,path,'/'+key,scope=included)
        if 'default_row_limit' in topic and (type(topic['default_row_limit']) is not int or topic['default_row_limit']<=0):
            issue('topic.row_limit',path,'/default_row_limit')
        access=topic.get('access_filters',[])
        if type(access) is not list: issue('access.list_required',path,'/access_filters'); continue
        for index,item in enumerate(access):
            at='/access_filters/'+str(index)
            if type(item) is not dict: issue('access.object_required',path,at); continue
            keys(item,{'field','user_attribute','values_for_unfiltered','enable_sql_like_wildcards'},path,at)
            target=reference(item.get('field'),base,path,at+'/field',included)
            if target and fields[target][0]!='dimensions': issue('access.dimension_required',path,at)
            if type(item.get('user_attribute')) is not str or item['user_attribute'] not in context['user_attributes']:
                issue('access.user_attribute_unresolved',path,at+'/user_attribute')
            if 'values_for_unfiltered' in item and (type(item['values_for_unfiltered']) is not list or not all(type(v) is str for v in item['values_for_unfiltered'])):
                issue('access.string_list_required',path,at)
            if 'enable_sql_like_wildcards' in item and type(item['enable_sql_like_wildcards']) is not bool: issue('access.boolean_required',path,at)
    return finish()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--files',type=Path,required=True,help='JSON map of native relative paths to exact text')
    parser.add_argument('--context',type=Path)
    args=parser.parse_args(argv)
    try:
        from ae_common import load_json
        result=check_model(load_json(args.files),load_json(args.context) if args.context else None)
    except (ValueError,OSError,TypeError,RecursionError):
        result={'status':'failed','findings':[{'code':'input.unavailable','path':'input','location':'/'}],'native_verified':False}
    print(json.dumps(result,sort_keys=True))
    return 0 if result['status']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
