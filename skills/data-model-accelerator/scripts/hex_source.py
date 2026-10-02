"""Static, bounded Hex v3 extraction. Never imports or executes notebook code."""
from __future__ import annotations
import ast
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

SCHEMA_SHA256 = 'e0a8d6f4261983194de2230821bcd86604d817301dc054a42665df4eb421bde0'
SCHEMA_PATH = Path(__file__).with_name('schemas') / 'hex-file-schema.v3.json'
MAX_BYTES = 2_000_000


def _load_yaml(text):
    import yaml
    # Alias expansion is outside this bounded parser's input policy.
    if any(isinstance(t, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)) for t in yaml.scan(text)):
        raise ValueError('YAML aliases/anchors are not accepted by this bounded reader')
    class Loader(yaml.SafeLoader):
        pass
    def mapping(loader, node, deep=False):
        out = {}
        for key, value in node.value:
            key = loader.construct_object(key, deep=deep)
            if not isinstance(key, str) or key in out:
                raise ValueError('YAML mapping keys must be unique strings')
            out[key] = loader.construct_object(value, deep=deep)
        return out
    Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    return yaml.load(text, Loader=Loader)


def _schema_validator():
    if not SCHEMA_PATH.is_file():
        raise ValueError('Run bootstrap_hex_schema.py explicitly before Hex validation; no schema is downloaded during analysis')
    from jsonschema import Draft7Validator, FormatChecker
    content = SCHEMA_PATH.read_bytes()
    if hashlib.sha256(content).hexdigest() != SCHEMA_SHA256:
        raise ValueError('Pinned Hex schema hash mismatch')
    schema = json.loads(content)
    return Draft7Validator(schema, format_checker=FormatChecker())


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _sql(source, dataframe):
    import sqlglot
    from sqlglot import exp
    from sqlglot.errors import ErrorLevel
    parameters = sorted(set(re.findall(r'\{\{\s*([A-Za-z_]\w*)\s*\}\}', source)))
    rendered = re.sub(r'\{\{\s*([A-Za-z_]\w*)\s*\}\}', r':\1', source)
    if '{{' in rendered or '{%' in rendered:
        raise ValueError('SQL contains unsupported dynamic template syntax')
    trees = sqlglot.parse(rendered, read='duckdb' if dataframe else 'snowflake', error_level=ErrorLevel.RAISE)
    if len(trees) != 1 or not isinstance(trees[0], exp.Query):
        raise ValueError('Only a single read-only query is analyzed; mutation/other SQL requires review')
    tree = trees[0]
    ctes = {c.alias.lower() for c in tree.find_all(exp.CTE)}
    tables = sorted({'.'.join(x.sql() for x in t.parts)
                     for t in tree.find_all(exp.Table) if t.db or t.catalog or t.name.lower() not in ctes})
    definitions = []
    for select in tree.find_all(exp.Select):
        for projection in select.expressions:
            if projection.alias:
                definitions.append({'name': projection.alias, 'expression': projection.this.sql(), 'expression_kind': 'sql_projection'})
    return {'parameters':parameters, 'table_reads':tables, 'ctes':sorted(ctes),
            'joins':[j.sql() for j in tree.find_all(exp.Join)],
            'filters':[w.sql() for w in tree.find_all(exp.Where)],
            'groupings':[g.sql() for g in tree.find_all(exp.Group)],
            'definitions':definitions, 'parsed_sql':tree.sql()}


def _python(source):
    tree = ast.parse(source)
    reads, writes, imports, files, merges, definitions, risks = set(), set(), {}, [], [], [], []
    allowed_calls = {'pd.read_csv', 'merge', 'fillna', 'astype', 'int'}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            (reads if isinstance(node.ctx, ast.Load) else writes).add(node.id)
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports[alias.asname or alias.name] = alias.name
                if alias.name != 'pandas' or alias.asname != 'pd':
                    risks.append('Only import pandas as pd is understood; imports are never executed')
        if isinstance(node, (ast.ImportFrom, ast.If, ast.For, ast.While, ast.Try, ast.With, ast.FunctionDef,
                             ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda, ast.ListComp, ast.DictComp,
                             ast.SetComp, ast.GeneratorExp, ast.Global, ast.Nonlocal, ast.Delete, ast.AugAssign)):
            risks.append('Stateful/dynamic Python construct: '+type(node).__name__)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                definitions.append({'name':ast.unparse(target), 'expression':ast.unparse(node.value), 'expression_kind':'python_assignment'})
                if isinstance(target, ast.Subscript):
                    # Column writes mutate an existing frame and also read its state.
                    if not isinstance(target.slice, ast.Constant) or not isinstance(target.slice.value,str):
                        risks.append('Dynamic dataframe column write')
        if isinstance(node, ast.Call):
            call = ast.unparse(node.func)
            terminal = node.func.attr if isinstance(node.func, ast.Attribute) else call
            if call not in allowed_calls and terminal not in allowed_calls:
                risks.append('Call outside the analyzed dataframe subset: '+call)
            if call == 'pd.read_csv':
                if node.args and isinstance(node.args[0],ast.Constant) and isinstance(node.args[0].value,str):
                    files.append(node.args[0].value)
                else:
                    risks.append('Dynamic file path cannot be resolved')
            if terminal == 'merge':
                options = {}
                for kw in node.keywords:
                    try: options[kw.arg] = ast.literal_eval(kw.value)
                    except (ValueError, TypeError): options[kw.arg] = {'expression':ast.unparse(kw.value)}
                merges.append({'expression':ast.unparse(node),'options':options})
    # Reads before the first assignment are external dependencies; subsequent in-cell
    # frame mutations must not hide them. Ignore only explicitly imported/builtin names.
    available = set(imports) | {'int'}
    external = set()
    for statement in tree.body:
        external.update(n.id for n in ast.walk(statement) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Load) and n.id not in available)
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Attribute):
                    risks.append('Attribute mutation is outside the analyzed dataframe subset')
                if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) and target.value.id not in available:
                    risks.append('Mutation of dataframe state produced by another cell: '+target.value.id)
        available.update(n.id for n in ast.walk(statement) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store))
    return {'reads':sorted(external), 'writes':sorted(writes-set(imports)), 'all_name_reads':sorted(reads),
            'imports':imports, 'files':files, 'merges':merges, 'definitions':definitions, 'risks':sorted(set(risks))}


def inspect_repo(repo):
    """Return source-bound static evidence; no account access, SQL or Python execution.

    No expected inventory is implied: callers must compare the returned asset hashes
    with their independently captured inventory to detect deleted whole exports.
    """
    root = Path(repo).resolve()
    validator = _schema_validator()
    result = {'schema_version':1,'kind':'hex_source_inventory','repo':str(root),
              'schema':{'url':'https://static.hex.site/hex-file-schema.json','sha256':SCHEMA_SHA256,'retrieved_on':'2026-10-02'},
              'projects':[],'cells':[],'edges':[],'gaps':[],'definitions':[],'assets':[]}
    def gap(kind, message, asset=None, cell=None, severity='error'):
        result['gaps'].append({'kind':kind,'severity':severity,'message':message,'asset':asset,'cell':cell})
    paths = sorted(root.rglob('*')) if root.is_dir() else []
    for p in paths:
        if p.is_symlink():
            gap('symlink','Symlink is not followed',str(p.relative_to(root)))
            continue
        if not p.is_file(): continue
        rel = str(p.relative_to(root))
        if p.stat().st_size > MAX_BYTES:
            gap('oversized_asset','Asset exceeds bounded reader size',rel)
            continue
        raw = p.read_bytes()
        result['assets'].append({'path':rel,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)})
        if not rel.endswith('.hex.yaml'):
            if p.suffix in ('.yaml','.yml','.ipynb'):
                gap('unclassified_export','Possible export requires explicit provenance/format review; not silently treated as Hex',rel)
            continue
        try:
            native = _load_yaml(raw.decode('utf-8'))
            errors = list(validator.iter_errors(native))
            if errors:
                gap('schema_invalid','; '.join('/'.join(map(str,e.absolute_path))+': '+e.message[:200] for e in errors[:6]),rel)
                continue
        except (ValueError, UnicodeError, TypeError, RecursionError) as exc:
            gap('yaml_invalid',str(exc),rel)
            continue
        except Exception as exc:
            # YAML parser exceptions vary by implementation; report without execution.
            gap('yaml_invalid',type(exc).__name__+': '+str(exc)[:250],rel)
            continue
        meta = native['meta']; pid = meta.get('projectId')
        if not pid:
            gap('missing_identity','Native schema permits absent projectId; stable identity is unavailable',rel)
            pid = 'unbound:'+rel
        project = {'id':pid,'project_id':meta.get('projectId'),'path':rel,'sha256':hashlib.sha256(raw).hexdigest(),
                   'title':meta['title'],'type':meta.get('hexType'),'source_version_id':meta.get('sourceVersionId'),
                   'meta':meta,'app_layout':native.get('appLayout'), 'data_app_cell_ids':native.get('dataAppCellIds'),
                   'shared_assets':native.get('sharedAssets',{}),'project_assets':native.get('projectAssets',{}),
                   'shared_filters':native.get('sharedFilters',[]),'cell_ids':[]}
        result['projects'].append(project)
        if meta.get('hexType') not in ('PROJECT','COMPONENT'):
            gap('unresolved_project_kind','Export kind is absent or outside the PROJECT/COMPONENT subset',rel)
        if not native.get('cells'): gap('missing_cells','No cells supplied; an omitted/empty list is not a complete project inventory',rel)
        for order, native_cell in enumerate(native.get('cells',[])):
            cid = native_cell.get('cellId')
            if not cid:
                gap('missing_identity','Native schema permits absent cellId; using an explicitly unbound positional identity',rel)
                cid = 'unbound:'+str(order)
            scoped = pid+'/'+cid
            config = native_cell['config']; kind = native_cell['cellType']
            cell = {'id':scoped,'cell_id':native_cell.get('cellId'),'project_id':pid,'path':rel,'order':order,
                    'cell_type':kind,'label':native_cell.get('cellLabel'),'config':config,'source':config.get('source'),
                    'reads':[],'writes':[],'analysis':{},'status':'parsed'}
            project['cell_ids'].append(scoped); result['cells'].append(cell)
            try:
                if kind == 'SQL':
                    analysis = _sql(config['source'],config.get('dataFrameCell',False)); cell['analysis']=analysis
                    cell['reads'] = analysis['parameters']+(analysis['table_reads'] if config.get('dataFrameCell',False) else [])
                    cell['writes']=[config.get('resultVariableName','query_result')]
                    cell['connection_id']=config.get('dataConnectionId')
                    if not config.get('dataFrameCell',False):
                        if not cell['connection_id']: gap('missing_connection','Warehouse SQL has no exported connection identity',rel,scoped)
                        declared={x.get('dataConnectionId') for assets in (native.get('sharedAssets',{}),native.get('projectAssets',{})) for x in assets.get('dataConnections',[])}
                        if cell['connection_id'] not in declared:
                            gap('undeclared_connection','SQL connection ID has no corresponding exported connection asset',rel,scoped)
                        for table in analysis['table_reads']:
                            result['edges'].append({'from':'connection:'+str(cell['connection_id'])+'/table:'+table,'to':scoped,'kind':'warehouse_read','evidence':table})
                            if len(table.split('.'))<3: gap('unqualified_table','Connection default database/schema needed for '+table,rel,scoped)
                elif kind == 'CODE':
                    if meta['codeLanguage']!='PYTHON': raise ValueError('Only Python CODE cells are analyzed')
                    analysis=_python(config['source']);cell['analysis']=analysis;cell['reads']=analysis['reads'];cell['writes']=analysis['writes']
                    for risk in analysis['risks']: gap('dynamic_python',risk,rel,scoped)
                    for name in analysis['files']:
                        file = (p.parent/name).resolve()
                        if not file.is_relative_to(root) or not file.is_file() or (p.parent/name).is_symlink():
                            gap('missing_file','File unavailable or outside repository: '+name,rel,scoped)
                        else:
                            result['edges'].append({'from':'file:'+str(file.relative_to(root)),'to':scoped,'kind':'file_read','evidence':name,'sha256':hashlib.sha256(file.read_bytes()).hexdigest()})
                elif kind == 'INPUT':
                    cell['writes']=[config['name']];cell['analysis']={'parameter':config}
                    if 'defaultValue' not in config: gap('missing_default','Input has no exported default',rel,scoped,'review')
                    if isinstance(config.get('defaultValue'),dict) or any('variableName' in x for x in _walk(config.get('options'))):
                        gap('dynamic_input','Input default/options require runtime dependency resolution',rel,scoped)
                elif kind == 'COMPONENT_IMPORT':
                    cell['analysis']={'component':config.get('component')}
                elif kind == 'CHARTV2':
                    cell['reads']=sorted({x['dataFrame'] for x in _walk(config) if isinstance(x.get('dataFrame'),str)})
                    if config.get('outputResult'): cell['writes']=[config.get('resultVariable','chart_result')]
                    cell['analysis']={'chart_spec':config.get('chartSpec'),'presentation_only':not config.get('outputResult',False)}
                    gap('native_chart_runtime','Chart settings preserved; native chart rendering and selection behavior unverified',rel,scoped,'review')
                elif kind in ('MARKDOWN','TEXT'):
                    cell['analysis']={'presentation':config}
                else:
                    cell['status']='partial';gap('unsupported_cell','Native type preserved but not semantically analyzed: '+kind,rel,scoped)
            except (ValueError,SyntaxError,TypeError) as exc:
                cell['status']='partial';gap('parse_error',str(exc),rel,scoped)
            except Exception as exc:
                cell['status']='partial';gap('parse_error',type(exc).__name__+': '+str(exc)[:250],rel,scoped)
            for definition in cell['analysis'].get('definitions',[]):
                result['definitions'].append({**definition,'cell_id':scoped,'project_id':pid,'source_path':rel})
        existing={c.get('cellId') for c in native.get('cells',[])}
        refs=[x['cellId'] for x in _walk(native.get('appLayout')) if x.get('cellId')]+native.get('dataAppCellIds',[])
        for ref in refs:
            if ref not in existing: gap('unresolved_layout_cell','App references missing cell '+ref,rel)
        for field in ('genAppFiles','sharedFilters'):
            if native.get(field): gap('unsupported_project_behavior',field+' preserved in source but not semantically interpreted',rel,severity='review')
        gap('runtime_context_unknown','Export excludes outputs; real connection namespace defaults, security assignments, environment and native execution remain unverified',rel,severity='review')
    ids=Counter(p['id'] for p in result['projects'])
    for pid,count in ids.items():
        if count>1: gap('duplicate_project_id','Multiple exports share project ID '+pid+'; no version silently selected')
    cells=Counter(c['id'] for c in result['cells'])
    for cid,count in cells.items():
        if count>1: gap('duplicate_cell_id','Repeated cell identity within project: '+cid,cell=cid)
    by_project=defaultdict(list)
    for cell in result['cells']: by_project[cell['project_id']].append(cell)
    unique_projects={p['id']:p for p in result['projects'] if ids[p['id']]==1}
    for cell in result['cells']:
        if cell['cell_type']!='COMPONENT_IMPORT':continue
        ref=cell['config'].get('component') or {}; target=unique_projects.get(ref.get('id'))
        if not target or target['type']!='COMPONENT':
            gap('missing_component','Component export is unavailable: '+str(ref),cell['path'],cell['id']);continue
        if not ref.get('version') or ref['version']!=target['source_version_id']:
            gap('component_version_mismatch','Requested component version does not match exported sourceVersionId',cell['path'],cell['id']);continue
        if any(c['cell_type']=='COMPONENT_IMPORT' for c in by_project[target['id']]):
            gap('nested_component','Nested component execution scope is outside bounded resolution',cell['path'],cell['id']);continue
        cell['writes']=sorted({w for c in by_project[target['id']] for w in c['writes']})
        cell['analysis']['resolved_component_id']=target['id']
        for c in by_project[target['id']]:
            result['edges'].append({'from':c['id'],'to':cell['id'],'kind':'component_import','evidence':ref})
    for pid,project_cells in by_project.items():
        producers=defaultdict(list)
        for c in project_cells:
            for variable in c['writes']:producers[variable].append(c)
        for variable,ps in producers.items():
            if len(ps)>1:gap('ambiguous_variable_writer','Multiple cells write '+variable+'; notebook order is not authoritative execution order',ps[0]['path'],ps[0]['id'])
        for c in project_cells:
            for name in c['reads']:
                ps=[p for p in producers.get(name,[]) if p['id']!=c['id']]
                if len(ps)!=1:
                    gap('unbound_variable','Read '+name+' has '+str(len(ps))+' distinct scoped producers',c['path'],c['id'])
                else:result['edges'].append({'from':ps[0]['id'],'to':c['id'],'kind':'variable_read','evidence':name})
    # A graph may resolve every name and still contain circular state dependencies.
    adjacency=defaultdict(set)
    for edge in result['edges']:
        if edge['from'] in cells and edge['to'] in cells:
            adjacency[edge['from']].add(edge['to'])
    visiting, visited = set(), set()
    def visit(node):
        if node in visiting: return True
        if node in visited: return False
        visiting.add(node)
        if any(visit(child) for child in adjacency[node]): return True
        visiting.remove(node); visited.add(node)
        return False
    if any(visit(node) for node in list(cells)):
        gap('dependency_cycle','Cell dependency graph contains a cycle; no execution order is inferred')
    if not result['projects']:gap('no_projects','No schema-valid native Hex exports found')
    result['counts']={'assets':len(result['assets']),'native_exports':sum(p.name.endswith('.hex.yaml') for p in paths if p.is_file()),
                      'projects':sum(p['type']=='PROJECT' for p in result['projects']),
                      'components':sum(p['type']=='COMPONENT' for p in result['projects']),
                      'cells':len(result['cells']),'edges':len(result['edges']),'definitions':len(result['definitions']),
                      'errors':sum(g['severity']=='error' for g in result['gaps']),'review_gaps':sum(g['severity']=='review' for g in result['gaps'])}
    result['static_coverage_complete']=not result['counts']['errors']
    result['native_runtime_validated']=False
    result['status']='partial' if result['gaps'] else 'parsed'
    return result
