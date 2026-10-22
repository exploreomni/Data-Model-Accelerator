"""File-level delivery coverage, independent of validation or execution approval.

Bindings identify candidate files for each entity. They do not establish SQL
correctness, physical existence, business parity, or host execution.
"""
from pathlib import Path
import ast

from ae_common import load_json, require


def entity_artifacts(state, task):
    """Resolve warehouse coverage without counting Omni/config YAML as dbt code.

    Single-entity legacy tasks retain their filenames. Multi-entity tasks may
    use uniquely matching model basenames, or supply explicit entity_outputs.
    """
    entities = {e['id']: e for e in state['workflow']['design']['entities']}
    outputs = task['outputs']
    explicit = task.get('entity_outputs')
    if explicit is not None:
        require(type(explicit) is dict and set(explicit) == set(task['entity_ids']),
                'entity_outputs must cover exactly the task entities')
        require(all(type(paths) is list and paths and len(set(paths)) == len(paths)
                    and all(type(p) is str and p in outputs for p in paths) for paths in explicit.values()),
                'entity_outputs must bind nonempty declared output lists')
    framework = state['answers'].get('framework')
    result = {}
    for key in task['entity_ids']:
        entity = entities[key]
        suffixes = ({'.json', '.yaml', '.yml'} if framework == 'coalesce'
                    else {'.sql', '.py'} if framework == 'dbt' else {'.sql', '.sqlx', '.py'})
        if framework == 'dbt' and entity.get('object_kind') == 'source':
            suffixes |= {'.yml', '.yaml'}
        if entity['disposition'] == 'reuse':
            suffixes |= {'.json'}
        candidates = [p for p in outputs if Path(p).suffix.lower() in suffixes]
        if explicit is not None:
            candidates = [p for p in candidates if p in explicit[key]]
        elif len(task['entity_ids']) > 1:
            names = {key, key.rsplit('.', 1)[-1], entity['name'], entity['name'].rsplit('.', 1)[-1]}
            candidates = [p for p in candidates if Path(p).stem in names]
        if framework == 'dbt':
            candidates = [p for p in candidates if not set(Path(p).parts) & {'tests', 'macros', 'analyses'}]
        require(candidates, 'Implementation tasks require native code artifacts or explicit reuse bindings for '
                + key + '; bind each model using entity_outputs. Omni/config YAML does not fulfill dbt models.')
        result[key] = candidates
    if framework == 'dbt':
        owners = {}
        for key, paths in result.items():
            for path in paths:
                if Path(path).suffix.lower() in {'.sql', '.py', '.json'}:
                    require(path not in owners, 'A dbt model or reuse binding cannot satisfy multiple entities: ' + path)
                    owners[path] = key
    return result


def verify_entity_files(state, task, root):
    from deployment_workflow import _stable_bytes
    mapping = entity_artifacts(state, task)
    entities = {e['id']: e for e in state['workflow']['design']['entities']}
    existing = {e['id']: e for e in state['workflow']['design'].get('existing_models', [])}
    for key, paths in mapping.items():
        entity = entities[key]
        for relative in paths:
            body = _stable_bytes(Path(root) / relative)
            require(body.strip(), 'Native code artifact is empty: ' + relative)
            if state['answers'].get('framework') == 'dbt' and Path(relative).suffix.lower() == '.py':
                try:
                    tree = ast.parse(body.decode('utf-8'))
                except (SyntaxError, UnicodeError, RecursionError, ValueError):
                    raise ValueError('dbt Python artifact must be parseable Python; source content is not printed') from None
                require(any(isinstance(node, ast.FunctionDef) and node.name == 'model'
                            and [a.arg for a in node.args.args] == ['dbt', 'session'] for node in tree.body),
                        'dbt Python artifact requires a top-level model(dbt, session) function; it is not executed by this check')
            if state['answers'].get('framework') == 'dbt' and Path(relative).suffix.lower() in {'.yml', '.yaml'}:
                try:
                    import yaml
                    value = yaml.safe_load(body.decode('utf-8'))
                except ImportError:
                    raise ValueError('Install the pinned YAML dependency to qualify dbt source declarations; incomplete checkpoint export remains available') from None
                except (yaml.YAMLError, UnicodeError, RecursionError, ValueError):
                    raise ValueError('Invalid dbt source declaration; source content is not printed') from None
                source_rows = value.get('sources') if type(value) is dict else None
                require(type(source_rows) is list, 'dbt source YAML must contain actual sources and tables, not Omni/config YAML')
                names = {entity['name'].rsplit('.', 1)[-1].casefold(), key.rsplit('.', 1)[-1].casefold()}
                tables = [table for source in source_rows if type(source) is dict and source.get('name')
                          and type(source.get('tables')) is list for table in source['tables'] if type(table) is dict]
                require(any(type(table.get('name')) is str and table['name'] and any(type(table.get(field)) is str
                            and table[field].casefold() in names for field in ('name', 'identifier')) for table in tables),
                        'dbt source declaration does not cover entity ' + key + '; preserve a matching table name or identifier')
            if Path(relative).suffix.lower() == '.json' and entity['disposition'] == 'reuse':
                binding = load_json(Path(root) / relative)
                target = (entity.get('reuse') or {}).get('existing_id')
                require(type(binding) is dict and binding.get('schema_version') == 1
                        and binding.get('kind') == 'existing_model_binding'
                        and binding.get('entity_id') == key and target in existing
                        and binding.get('existing_id') == target
                        and type(binding.get('evidence_refs')) is list and binding['evidence_refs']
                        and set(binding['evidence_refs']) <= set(existing[target]['evidence_refs']),
                        'Existing-model binding must identify the entity, inventoried model and retained evidence')
    return mapping


def required_stages(state):
    selected = set(state['answers'].get('deliverables', []))
    stages = ['implementation'] if 'implementation' in selected else []
    if stages and state['answers'].get('semantic_target') not in (None, 'none', 'retain_existing') \
            and state['answers'].get('migration_scope') != 'model_only':
        stages.append('semantic')
    if stages or 'validation' in selected:
        stages.append('validation')
    return stages


def check_packaged_code(state, manifest):
    """Check selected file coverage; never upgrade a package to validated code."""
    rows = [r for r in manifest['files'] if r.get('category') == 'implementation' and r.get('bytes', 0) > 0]
    framework = state['answers'].get('framework')
    suffixes = ({'.sql', '.py', '.json'} if framework == 'dbt'
                else {'.json', '.yaml', '.yml'} if framework == 'coalesce' else {'.sql', '.sqlx', '.py'})
    wf = state.get('workflow') or {}
    if not wf.get('design') or not wf.get('tasks'):
        # Older standalone review documents have no entity task ledger. Retain
        # their export path, but never let semantic-only files count as dbt SQL.
        require(any(Path(r['path']).suffix.lower() in suffixes - {'.json'} if framework == 'dbt'
                    else Path(r['path']).suffix.lower() in suffixes for r in rows),
                'Selected warehouse implementation is missing native model code; Omni files alone do not fulfill it')
        require(not wf.get('design'), 'Register per-entity implementation tasks before finalizing code; an incomplete checkpoint remains available')
        return
    from engagement_stages import closure
    from domain_workflow import ledger, scope
    doc = wf['design']
    expected = (scope(state) if ledger(state) and ledger(state)['active_domain_id']
                else {e['id'] for e in doc['entities']})
    expected -= {e['id'] for e in doc['entities'] if e.get('object_kind') == 'interface'}
    packaged = {r['path']: r for r in rows}
    plan = {t['id']: t for t in (wf.get('last_plan') or {}).get('tasks', [])}
    graph = {e['id']: e['depends_on'] for e in doc['entities']}
    for stage in [s for s in required_stages(state) if s in {'implementation', 'semantic'}] or ['implementation']:
        covered = set()
        for task in wf['tasks']:
            current = plan.get(task['id'], {})
            if task['stage'] != stage or current.get('action') != 'reuse':
                continue
            from engagement_stages import _code_artifacts
            paths = _code_artifacts(state, task)
            if not all('02_Implementation/' + p in packaged
                       and packaged['02_Implementation/' + p].get('sha256') == (current.get('outputs') or {}).get(p)
                       for p in paths):
                continue
            covered.update(task['entity_ids'] if stage == 'implementation' else closure(graph, task['entity_ids']))
        require(expected <= covered, 'Selected ' + stage + ' code is incomplete for: ' + ', '.join(sorted(expected - covered))
                + '. Keep the stage pending or export an explicitly incomplete checkpoint.')
