"""Private, bounded derived-view lineage. No execution or invented table bindings.

The descriptor includes population dependencies, not only projected columns.
It is structural evidence tied to exact files/context, never native qualification.
"""
import copy
import re
from pathlib import PurePosixPath

from omni_contract import (_load, _merge, _bounded, canonical_hash, yaml, sqlglot, exp,
                           NAME, FIELD, REF, DIALECTS, NAMESPACE, DIM, MEASURE, TIMEFRAMES, _sha, MAX_FILES, MAX_BYTES, MAX_DEPTH)

VERSION = 'omni-derived-lineage-v1-2026-10-05'


class QueryViewError(ValueError):
    pass


def _need(ok, code):
    if not ok:raise QueryViewError(code)


def _identity(path):
    name=PurePosixPath(path).name
    if name.endswith(('.yaml','.yml')):name=name.rsplit('.',1)[0]
    for suffix,kind in (('.query.view','view'),('.view','view'),('.topic','topic')):
        if name.endswith(suffix):return kind,name[:-len(suffix)]
    return name,name


def analyze_query_views(files,context,topic=None):
    """Resolve private definitions and derived outputs from supplied exact inputs.

    Return status/findings/descriptors/effective_views/binding_origins and pins.
    `topic` selects one topic namespace; aliases never enter other namespaces.
    Every physical column carries its real source view and namespace. Unsupported
    SQL, scope, operators, or unresolved dependencies block qualification.
    """
    result={'schema_version':1,'kind':'omni_derived_lineage','version':VERSION,
            'status':'passed','candidate_sha256':None,'context_sha256':None,'topic':topic,
            'descriptors':{},'effective_views':{},'binding_origins':{},'topic_definition':None,
            'field_lineage':{},'findings':[],'native_verified':False,'private_only':True,
            'limitations':['Structural lineage only; native query/access and business-result qualification are separate.',
                          'Implicit whitelist dependency eligibility requires native qualification.']}
    def issue(code,path='context',location='/',unsupported=False):
        finding={'code':code,'path':path,'location':location,'severity':'unsupported' if unsupported else 'error'}
        if finding not in result['findings']:result['findings'].append(finding)
    def finish():
        result['status']='failed' if any(f['severity']=='error' for f in result['findings']) else 'unsupported' if result['findings'] else 'passed'
        return result
    try:
        _bounded(files);_bounded(context)
        _need(type(files) is dict and 0<len(files)<=MAX_FILES and all(type(v) is str for v in files.values()),'query.input')
        _need(sum(len(k.encode())+len(v.encode()) for k,v in files.items())<=MAX_BYTES,'query.byte_limit')
        result['candidate_sha256']=canonical_hash(files);result['context_sha256']=canonical_hash(context)
        _need(type(context) is dict and context.get('warehouse') in DIALECTS and
              type(context.get('bindings')) is dict and type(context.get('inherited_views')) is dict,'query.context')
        _need(set(context)=={'schema_version','kind','warehouse','environment','catalogue_sha256','bindings',
                             'inherited_views','default_catalog','user_attributes','access_grants'} and
              type(context['schema_version']) is int and context['schema_version']==1 and context['kind']=='omni_model_context'
              and _sha(context['catalogue_sha256']) and type(context['environment']) is str,'query.context')
        for name,binding in context['bindings'].items():
            _need(NAME.fullmatch(name) and type(binding) is dict and set(binding)=={'namespace','columns','evidence_sha256'}
                  and _sha(binding['evidence_sha256']) and type(binding['namespace']) is dict
                  and set(binding['namespace'])==set(NAMESPACE[context['warehouse']])
                  and all(type(v) is str and v.strip() for v in binding['namespace'].values())
                  and type(binding['columns']) is dict and all(type(k) is str and k and type(v) is str
                  and v in ('string','number','date','timestamp','boolean','unknown') for k,v in binding['columns'].items()),'query.context_binding')
        _need(topic is None or type(topic) is str and NAME.fullmatch(topic),'query.topic')
        if yaml is None or sqlglot is None:
            issue('query.runtime_unavailable',unsupported=True);return finish()
        warehouse=context['warehouse'];dialect=DIALECTS[warehouse]
        definitions={};paths={};topics={};global_relations=[];model={}
        for path,text in sorted(files.items()):
            relative=PurePosixPath(path)
            _need(re.fullmatch(r'[A-Za-z0-9_./-]+',path) and not relative.is_absolute() and
                  '..' not in relative.parts and str(relative)==path,'query.path')
            kind,name=_identity(path)
            if kind not in ('view','topic','relationships','model'):continue
            obj=_load(text)
            if kind=='model':model=obj;continue
            if kind=='relationships':global_relations=obj;continue
            _need(NAME.fullmatch(name) and type(obj) is dict,'query.object')
            dest=definitions if kind=='view' else topics
            _need(name not in dest,'query.duplicate_identity');dest[name]=obj
            if kind=='view':paths[name]=path
        for name,item in context['inherited_views'].items():
            _need(type(item) is dict and type(item.get('definition')) is dict and
                  item.get('sha256')==canonical_hash(item['definition']),'query.inherited_changed')
            definitions[name]=_merge(item['definition'],definitions.get(name,{}));paths.setdefault(name,'context')
        def topic_definition(name,trail=()):
            _need(name in topics and name not in trail and len(trail)<MAX_DEPTH,'query.topic_inheritance')
            obj=topics[name];parents=obj.get('extends',[]);base={}
            _need(type(parents) is list and len(parents)<=1 and all(type(p) is str for p in parents),'query.topic_inheritance')
            if parents:base=topic_definition(parents[0],trail+(name,))
            output=_merge(base,obj);output.pop('extends',None);return output
        if topic is not None:
            scoped=topic_definition(topic);result['topic_definition']=scoped
            overrides=scoped.get('views',{})
            _need(type(overrides) is dict,'query.topic_views')
            for alias,value in overrides.items():
                _need(NAME.fullmatch(alias) and type(value) is dict,'query.topic_views')
                definitions[alias]=_merge(definitions.get(alias,{}),value);paths.setdefault(alias,topic+'.topic')
        bindings=context['bindings'];resolved={};origins={}
        def resolve(name,trail=()):
            if name in resolved:return resolved[name]
            _need(name in definitions and name not in trail and len(trail)<MAX_DEPTH,'query.view_inheritance')
            obj=definitions[name];parents=obj.get('extends',[]);base={}
            _need(type(parents) is list and len(parents)<=1 and all(type(p) is str for p in parents),'query.view_inheritance')
            origin=name if name in bindings else None
            if parents:
                base=resolve(parents[0],trail+(name,));origin=origin or origins.get(parents[0])
            resolved[name]=_merge(base,obj);origins[name]=origin;return resolved[name]
        for name in definitions:resolve(name)
        result['effective_views']=copy.deepcopy(resolved);result['binding_origins']=copy.deepcopy(origins)
        descriptors={};active=set();field_active=set();field_cache={}
        def physical(view,column):
            origin=origins.get(view);binding=bindings.get(origin,{})
            _need(type(binding.get('columns')) is dict and column in binding['columns'],'query.physical_column_unresolved')
            return {'view':origin,'namespace':copy.deepcopy(binding['namespace']),
                    'column':column,'datatype':binding['columns'][column]}
        def unique_columns(values):
            return [v for _,v in sorted({canonical_hash(v):v for v in values}.items())]
        def source_column(view,name,quoted=False):
            obj=resolved.get(view,{})
            if 'query' in obj or 'sql' in obj:
                desc=describe(view)
                lookup=name.upper() if warehouse=='snowflake' and not quoted else name
                matches=[o for o in desc['outputs'].values() if o['sql_identifier']==lookup]
                _need(len(matches)==1,'query.output_column_unresolved')
                return matches[0]['physical_columns'],matches[0]['semantic_fields'],matches[0]['datatype']
            normalized=name.upper() if warehouse=='snowflake' and not quoted else name
            col=physical(view,normalized);return [col],[],col['datatype']
        def expression(value,view):
            _need(type(value) is str and value.strip() and '__dma_' not in value,'query.expression')
            refs=[]
            def replace(match):refs.append(match[1]);return '__dma_f_'+str(len(refs)-1)
            cooked=REF.sub(replace,value)
            _need('${' not in cooked and '{{' not in cooked and '{%' not in cooked,'query.template_unqualified')
            trees=sqlglot.parse(cooked,read=dialect,error_message_context=0)
            _need(len(trees)==1,'query.single_expression_required');tree=trees[0]
            _need(tree is not None and not any(isinstance(n,(exp.Query,exp.DDL,exp.DML,exp.Command,exp.Subquery,exp.Anonymous)) for n in tree.walk()),'query.expression_unqualified')
            columns=[];semantic=[];types=[]
            for node in tree.find_all(exp.Column):
                if node.name.startswith('__dma_f_') and not node.table:
                    reference=refs[int(node.name[8:])];dep=field(view,reference)
                    columns+=dep['physical_columns'];semantic+=dep['semantic_fields'];types.append(dep['datatype'])
                else:
                    _need(not node.table and not node.db and not node.catalog,'query.expression_qualification')
                    cols,sem,kind=source_column(view,node.name,bool(node.this.args.get('quoted')))
                    columns+=cols;semantic+=sem;types.append(kind)
            return unique_columns(columns),sorted(set(semantic)),types[0] if type(tree) is exp.Column and len(types)==1 else 'unknown'
        def filter_refs(value,view):
            _need(type(value) is dict,'query.filters_shape')
            refs=[];columns=[]
            for ref,condition in value.items():
                dep=field(view,ref);refs+=dep['semantic_fields'];columns+=dep['physical_columns']
                _need(type(condition) is dict and len(condition)==1,'query.filter_unqualified')
                op,operand=next(iter(condition.items()))
                _need(op in ('is','not','greater_than','greater_than_or_equal_to','less_than','less_than_or_equal_to','contains','not_contains','starts_with','ends_with'),'query.filter_unqualified')
                values=operand if type(operand) is list else [operand]
                _need(all(v is None or type(v) in (str,int,float,bool) for v in values),'query.filter_shape')
                if op.startswith(('greater_','less_')):_need(type(operand) in (int,float),'query.filter_numeric_required')
                if op in ('contains','not_contains','starts_with','ends_with'):_need(type(operand) is str,'query.filter_string_required')
                _need(not any(type(v) is str and ('{{' in v or '${' in v) for v in values),'query.filter_dynamic_unqualified')
            return refs,columns
        def _field(current,reference):
            match=FIELD.fullmatch(reference) if type(reference) is str else None
            _need(match is not None,'query.field_reference')
            view=match['view'] or current;name=match['field'];key=view+'.'+name
            if key in field_cache:return field_cache[key]
            _need(key not in field_active and len(field_active)<MAX_DEPTH,'query.dependency_cycle')
            _need(view in resolved,'query.view_unresolved');obj=resolved[view]
            category='dimensions' if name in obj.get('dimensions',{}) else 'measures'
            definition=obj.get(category,{}).get(name)
            _need(type(definition) is dict,'query.field_unresolved');field_active.add(key)
            try:
                _need(set(definition)<=(DIM if category=='dimensions' else MEASURE),'query.field_parameter_unqualified')
                columns=[];semantic=[key];datatype='unknown'
                if 'sql' in definition:
                    cols,refs,datatype=expression(definition['sql'],view);columns+=cols;semantic+=refs
                elif category=='dimensions':
                    # Native omitted SQL references its matching output/physical name.
                    if 'query' in obj or 'sql' in obj:
                        desc=describe(view);matches=[o for o in desc['outputs'].values() if o['name']==name or o['sql_identifier']==name.upper()]
                        _need(len(matches)==1,'query.dimension_output_unresolved')
                        columns+=matches[0]['physical_columns'];semantic+=matches[0]['semantic_fields'];datatype=matches[0]['datatype']
                    else:
                        origin=origins.get(view);available=bindings.get(origin,{}).get('columns',{})
                        matches=[c for c in available if c==name or warehouse=='snowflake' and c==name.upper()]
                        _need(len(matches)==1,'query.physical_column_unresolved')
                        col=physical(view,matches[0]);columns.append(col);datatype=col['datatype']
                elif definition.get('aggregate_type')=='count':
                    if 'query' in obj or 'sql' in obj:
                        for output in describe(view)['outputs'].values():columns+=output['physical_columns'];semantic+=output['semantic_fields']
                    else:
                        columns += [physical(view,c) for c in bindings.get(origins.get(view),{}).get('columns',{})]
                        _need(bool(columns),'query.count_population_unresolved')
                else:raise QueryViewError('query.field_definition_unresolved')
                if category=='measures':datatype='number'
                if 'filters' in definition:
                    refs,cols=filter_refs(definition['filters'],view);semantic+=refs;columns+=cols
                if 'custom_primary_key_sql' in definition:
                    cols,refs,_=expression(definition['custom_primary_key_sql'],view);columns+=cols;semantic+=refs
                if 'order_by_field' in definition:
                    dep=field(view,definition['order_by_field']);columns+=dep['physical_columns'];semantic+=dep['semantic_fields']
                output={'semantic_fields':sorted(set(semantic)),'physical_columns':unique_columns(columns),'datatype':datatype}
                field_cache[key]=output;return output
            finally:field_active.remove(key)
        def field(current,reference):
            match=FIELD.fullmatch(reference) if type(reference) is str else None
            _need(match is not None,'query.field_reference')
            result=_field(current,reference)
            if match['time']:
                timeframe=match['time'].lower();_need(timeframe in TIMEFRAMES,'query.timeframe_invalid')
                view=match['view'] or current
                _need(match['field'] in resolved[view].get('dimensions',{}),'query.timeframe_on_measure')
                if result['datatype']=='unknown':raise QueryViewError('query.timeframe_type_unqualified')
                _need(result['datatype'] in ('date','timestamp'),'query.timeframe_non_temporal')
                if timeframe in ('fiscal_year','fiscal_quarter'):
                    _need(type(model) is dict and type(model.get('fiscal_month_offset')) is int,'query.fiscal_offset_required')
                result=copy.deepcopy(result)
                if timeframe not in ('raw','date'):result['datatype']='unknown'
                elif timeframe=='date':result['datatype']='date'
            return result
        def population(base,query_topic):
            refs=[];columns=[];reachable={base}
            if query_topic is None:return refs,columns,reachable
            scoped=topic_definition(query_topic)
            _need(scoped.get('base_view')==base,'query.topic_base_mismatch')
            # Different local aliases require a separately selected namespace.
            _need(not scoped.get('views') or topic==query_topic,'query.topic_scope_required')
            relations=global_relations+scoped.get('relationships',[])
            _need(type(relations) is list,'query.relationships')
            def walk(tree,parent):
                _need(type(tree) is dict,'query.joins_shape')
                for child,nested in tree.items():
                    _need(child in resolved and child not in reachable,'query.join_ambiguous')
                    matches=[r for r in relations if type(r) is dict and r.get('join_from_view')==parent and r.get('join_to_view')==child]
                    _need(len(matches)==1,'query.relationship_unresolved')
                    reachable.add(child)
                    sql=matches[0].get('on_sql');_need(type(sql) is str,'query.relationship_sql')
                    for reference in REF.findall(sql):
                        dep=field(parent,reference);refs.extend(dep['semantic_fields']);columns.extend(dep['physical_columns'])
                    walk(nested,child)
            walk(scoped.get('joins',{}),base)
            for key in ('default_filters','always_where_filters'):
                r,c=filter_refs(scoped.get(key,{}),base);refs+=r;columns+=c
            for access in scoped.get('access_filters',[]):
                _need(type(access) is dict,'query.access_filter');dep=field(base,access.get('field'))
                refs+=dep['semantic_fields'];columns+=dep['physical_columns']
            return refs,columns,reachable
        def topic_selection(query_topic,reachable):
            available={v+'.'+name for v in reachable for section in ('dimensions','measures') for name in resolved[v].get(section,{})}
            if query_topic is None:return available,set()
            topic_obj=topic_definition(query_topic);selectors=topic_obj.get('fields')
            if selectors is None:return available,set()
            _need(type(selectors) is list,'query.topic_selectors_shape')
            ranked=[];selected=set();excluded=set()
            for index,value in enumerate(selectors):
                _need(type(value) is str,'query.topic_selector_shape')
                negative=value.startswith('-');selector=value[1:] if negative else value;rank=5;matches=set()
                if selector=='all_views.*':rank=1;matches=set(available)
                elif selector.endswith('.*'):
                    rank=2;view=selector[:-2];_need(view in reachable,'query.selector_view_unreachable')
                    matches={f for f in available if f.split('.')[0]==view}
                elif selector.startswith('tag:') or ':tag:' in selector:
                    rank=4 if ':tag:' in selector else 3
                    view,tag=selector.split(':tag:',1) if rank==4 else (None,selector[4:])
                    for key in available:
                        v,f=key.split('.');definition=resolved[v].get('dimensions',{}).get(f,resolved[v].get('measures',{}).get(f,{}))
                        if (view is None or view==v) and (tag in resolved[v].get('tags',[]) or tag in definition.get('tags',[])):matches.add(key)
                else:
                    match=FIELD.fullmatch(selector);_need(match is not None,'query.selector_unqualified')
                    key=(match['view'] or topic_definition(query_topic)['base_view'])+'.'+match['field']
                    _need(key in available,'query.selector_unresolved');matches={key}
                ranked.append((rank,index,negative,matches))
            for _,_,negative,matches in sorted(ranked):
                if negative:selected-=matches;excluded|=matches
                else:selected|=matches;excluded-=matches
            return selected,excluded
        def describe(view):
            if view in descriptors:return descriptors[view]
            _need(view not in active and len(active)<MAX_DEPTH,'query.dependency_cycle');active.add(view)
            obj=resolved[view];out={};population_refs=[];population_columns=[];limited=False;whitelist_operands=set()
            _need(('query' in obj)^('sql' in obj),'query.exclusive_source')
            _need(view not in bindings and 'table_name' not in obj,'query.physical_binding_forbidden')
            try:
                if 'query' in obj:
                    query=obj['query'];_need(type(query) is dict,'query.shape')
                    _need(set(query)<={'fields','base_view','topic','filters','sorts','limit'},'query.parameter_unqualified')
                    base=query.get('base_view');_need(type(base) is str and base in resolved,'query.base_unresolved')
                    qtopic=query.get('topic');_need(qtopic is None or type(qtopic) is str and qtopic in topics,'query.topic_unresolved')
                    population_refs,population_columns,reachable=population(base,qtopic)
                    selected,excluded=topic_selection(qtopic,reachable)
                    refs,cols=filter_refs(query.get('filters',{}),base);population_refs+=refs;population_columns+=cols
                    for reference in query.get('filters',{}):
                        match=FIELD.fullmatch(reference);target=(match['view'] or base)+'.'+match['field']
                        _need(target in selected,'query.topic_filter_excluded')
                    entries=query.get('fields');pairs=[]
                    if type(entries) is dict:pairs=list(entries.items())
                    elif type(entries) is list:
                        for entry in entries:
                            if type(entry) is str:pairs.append((entry,None))
                            elif type(entry) is dict and len(entry)==1:pairs.append(next(iter(entry.items())))
                            else:raise QueryViewError('query.fields_shape')
                    else:raise QueryViewError('query.fields_shape')
                    _need(bool(pairs),'query.outputs_empty')
                    for reference,alias in pairs:
                        _need(type(reference) is str and FIELD.fullmatch(reference),'query.field_reference')
                        _need(alias is None or type(alias) is str and NAME.fullmatch(alias),'query.alias_shape')
                        alias=alias or reference.replace('.','__').replace('[','__').replace(']','')
                        _need(type(alias) is str and NAME.fullmatch(alias) and alias not in out,'query.output_collision')
                        dep=field(base,reference)
                        match=FIELD.fullmatch(reference);source_view=match['view'] or base
                        source_key=source_view+'.'+match['field']
                        _need(source_key in selected and not set(dep['semantic_fields'])&excluded,'query.topic_field_excluded')
                        whitelist_operands.update(set(dep['semantic_fields'])-selected)
                        _need(all(r.split('.')[0] in reachable for r in dep['semantic_fields']),'query.field_unreachable')
                        out[alias]={'name':alias,'sql_identifier':alias.upper() if warehouse=='snowflake' else alias,'source_field':reference,**copy.deepcopy(dep)}
                        if match['field'] in resolved[source_view].get('dimensions',{}):
                            population_refs+=dep['semantic_fields'];population_columns+=dep['physical_columns']
                    sorts=query.get('sorts',[]);_need(type(sorts) is list,'query.sorts_shape')
                    if 'sorts' in query or 'limit' in query:
                        issue('query.sort_limit_native_contract_unqualified',paths[view],'/query',True)
                    for sort in sorts:
                        _need(type(sort) is dict and set(sort)=={'field','desc'} and type(sort['desc']) is bool,'query.sorts_shape')
                        dep=field(base,sort['field']);population_refs+=dep['semantic_fields'];population_columns+=dep['physical_columns']
                        match=FIELD.fullmatch(sort['field']);target=(match['view'] or base)+'.'+match['field']
                        _need(target in selected,'query.topic_sort_excluded')
                    if 'limit' in query:
                        _need(type(query['limit']) is int and query['limit']>0,'query.limit_shape')
                        _need(bool(sorts),'query.limit_order_unqualified')
                        limited=True
                    for ref in population_refs:_need(ref.split('.')[0] in reachable,'query.population_unreachable')
                    _need(not set(population_refs)&excluded,'query.topic_population_excluded')
                    whitelist_operands.update(set(population_refs)-selected)
                    kind='modeled_query'
                else:
                    sql=obj['sql'];_need(type(sql) is str and sql.strip() and '__dma_' not in sql,'query.sql_shape')
                    refs=[]
                    def replace(match):refs.append(match[1]);return '__dma_relation_'+str(len(refs)-1)
                    cooked=REF.sub(replace,sql)
                    _need('${' not in cooked and '{{' not in cooked and '{%' not in cooked,'query.sql_template_unqualified')
                    trees=sqlglot.parse(cooked,read=dialect,error_message_context=0)
                    _need(len(trees)==1 and type(trees[0]) is exp.Select,'query.read_only_select_required')
                    tree=trees[0]
                    _need(not any(isinstance(n,(exp.DDL,exp.DML,exp.Command,exp.Subquery,exp.CTE,exp.Into,exp.Window,exp.Anonymous,exp.Lock)) for n in tree.walk()),'query.sql_construct_unqualified')
                    aliases={}
                    for table in tree.find_all(exp.Table):
                        _need(table.name.startswith('__dma_relation_') and not table.db and not table.catalog,'query.raw_relation_unqualified')
                        source=refs[int(table.name[len('__dma_relation_'):])]
                        _need(NAME.fullmatch(source) and source in resolved,'query.relation_unresolved')
                        alias=table.alias_or_name;_need(alias not in aliases,'query.relation_alias_collision');aliases[alias]=source
                    _need(bool(aliases),'query.source_population_unresolved')
                    def sql_dependencies(node):
                        columns=[];semantic=[]
                        for col in node.find_all(exp.Column):
                            _need(not col.is_star,'query.wildcard_unqualified')
                            if col.table:_need(col.table in aliases,'query.table_alias_unresolved');source=aliases[col.table]
                            else:_need(len(aliases)==1,'query.column_ambiguous');source=next(iter(aliases.values()))
                            c,s,_=source_column(source,col.name,bool(col.this.args.get('quoted')));columns+=c;semantic+=s
                        return unique_columns(columns),sorted(set(semantic))
                    # All columns used by predicates, joins, grouping and ordering
                    # are conservatively included in each output's population.
                    population_columns,population_refs=sql_dependencies(tree)
                    if any(isinstance(n,exp.Count) and n.find(exp.Star) for n in tree.walk()):
                        for source in aliases.values():
                            if 'query' in resolved[source] or 'sql' in resolved[source]:
                                for item in describe(source)['outputs'].values():population_columns+=item['physical_columns'];population_refs+=item['semantic_fields']
                            else:population_columns += [physical(source,c) for c in bindings.get(origins.get(source),{}).get('columns',{})]
                    for selection in tree.expressions:
                        _need(type(selection) is exp.Alias and NAME.fullmatch(selection.alias),'query.explicit_output_alias_required')
                        alias=selection.alias;identifier=selection.args['alias'];quoted=bool(identifier.args.get('quoted'))
                        native=alias.upper() if warehouse=='snowflake' and not quoted else alias
                        _need(alias not in out and native not in [o['sql_identifier'] for o in out.values()],'query.output_collision')
                        cols,sem=sql_dependencies(selection)
                        out[alias]={'name':alias,'sql_identifier':native,'source_field':None,'physical_columns':cols,'semantic_fields':sem,'datatype':'unknown'}
                    if tree.args.get('limit') is not None:
                        _need(tree.args.get('order') is not None,'query.limit_order_unqualified');limited=True
                    kind='sql_query'
                for output in out.values():
                    output['physical_columns']=unique_columns(output['physical_columns']+population_columns)
                    output['semantic_fields']=sorted(set(output['semantic_fields']+population_refs))
                descriptor={'view':view,'kind':kind,'definition_sha256':canonical_hash(obj),
                            'outputs':out,'population_fields':sorted(set(population_refs)),
                            'population_columns':unique_columns(population_columns),'native_verified':False}
                descriptor['complete_population']=not limited
                descriptor['truncation']='limited' if limited else 'no_declared_limit'
                descriptor['runtime_eligibility']='native_qualification_required'
                descriptor['implicit_whitelist_dependencies']=sorted(whitelist_operands)
                descriptor['query_controls']=copy.deepcopy({key:obj['query'][key] for key in ('sorts','limit') if key in obj.get('query',{})}) if 'query' in obj else {}
                descriptor['output_shape_sha256']=canonical_hash(out);descriptors[view]=descriptor;return descriptor
            finally:active.remove(view)
        for view,obj in resolved.items():
            if 'query' in obj or 'sql' in obj:
                try:describe(view)
                except QueryViewError as error:issue(str(error),paths[view],unsupported=str(error).endswith('_unqualified') or str(error)=='query.topic_scope_required')
        # Eager lineage for all modeled fields gives consumers a single reusable
        # dependency API, including local filters and non-projected dependencies.
        for view,obj in resolved.items():
            for category in ('dimensions','measures'):
                values=obj.get(category,{})
                if type(values) is not dict:issue('query.field_shape',paths[view]);continue
                for name in values:
                    try:result['field_lineage'][view+'.'+name]=field(view,name)
                    except QueryViewError as error:issue(str(error),paths[view],unsupported=str(error).endswith('_unqualified'))
        result['descriptors']=descriptors
    except QueryViewError as error:issue(str(error),unsupported=str(error).endswith('_unqualified'))
    except Exception:issue('query.malformed_or_unqualified_input')
    return finish()
