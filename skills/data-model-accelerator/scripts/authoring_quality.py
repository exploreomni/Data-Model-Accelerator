"""Automatic, bounded authoring checks and independently refreshed observations.

No warehouse calls, macros, agents, approval writes or candidate mutations.
"""
import argparse
from collections import OrderedDict
import copy
from pathlib import Path
import json
import sys
from importlib import metadata

from ae_common import _path, hash_file, hash_json, load_json, require, write_json
from authoring_evidence import capture, finding, make_receipt, validate_contract, fields

CHECKER_FILES = ('authoring_evidence.py', 'authoring_provenance.py', 'dbt_references.py',
                 'authoring_conformance.py', 'authoring_quality.py', 'artifact_syntax.py', 'source_adapters/base.py',
                 'naming_governance.py', 'naming_artifacts.py', 'sql_contracts.py')

# Process-local optimization only; exact candidate/source bytes are rechecked.
_OBSERVATION_CACHE = OrderedDict()
MAX_CACHED_OBSERVATIONS = 16


def checker_version():
    root = Path(__file__).parent
    versions = {}
    for package in ('sqlglot', 'PyYAML'):
        try: versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError: versions[package] = 'unavailable'
    return hash_json({'files': {name: hash_file(root / name) for name in CHECKER_FILES},
                      'dependencies': versions, 'python': list(sys.version_info[:3])})


def target_dialect(state):
    warehouse = state['answers'].get('warehouse')
    return {'motherduck': 'duckdb', 'fabric': 'tsql'}.get(warehouse, warehouse)


def evaluate(root, source_root, contract, paths, dialect):
    from authoring_conformance import check_conformance
    from authoring_provenance import check_provenance, MAX_FILES
    root, source_root = _path(root), _path(source_root)
    require(root != source_root and root not in source_root.parents and source_root not in root.parents,
            'Authoring source and candidate roots must be separate')
    contract = validate_contract(contract)
    before = capture(root, paths)
    version = checker_version()
    cache_key = hash_json([str(root), str(source_root), contract, before, dialect, version])
    cached = _OBSERVATION_CACHE.get(cache_key)
    if cached is not None:
        try:
            if capture(source_root, list(cached['source_evidence'])) == cached['source_evidence']:
                _OBSERVATION_CACHE.move_to_end(cache_key)
                return copy.deepcopy(cached)
        except (OSError, ValueError):
            pass
        _OBSERVATION_CACHE.pop(cache_key, None)
    if len(paths) > MAX_FILES:
        findings, evidence = [finding('authoring_batch_bound_exceeded', 'unsupported')], {}
    else:
        findings, evidence = check_provenance(root, source_root, contract, paths, dialect)
        findings += check_conformance(root, contract, paths, dialect)
        from artifact_syntax import check_structured_artifacts
        findings += check_structured_artifacts(root, paths)
        if contract.get('sql_rules'):
            from sql_contracts import run as check_sql_rules
            rules = contract['sql_rules']
            sql_paths = [p for p in paths if Path(p).suffix.lower() == '.sql']
            report = check_sql_rules([root, source_root], rules['contract'],
                scope=[Path(p).stem for p in sql_paths], dialect=dialect,
                candidate_paths=sql_paths, upstream_paths=rules['upstream_paths'])
            require(all(before.get(p) == digest for p, digest in report['candidate_evidence'].items()),
                    'SQL contract candidate bytes changed')
            for path, digest in report['source_evidence'].items():
                require(path not in evidence or evidence[path] == digest, 'SQL source evidence changed')
                evidence[path] = digest
            models = {Path(m['path']).stem: m for m in contract['models'] if m.get('path')}
            for row in report['findings']:
                model = models.get(row.get('model'), {})
                status = 'failed' if row['severity'] == 'error' else 'unsupported' if row.get('status') == 'unsupported' else 'not_run'
                findings.append(finding('sql_contract:' + row['code'], status,
                    model_id=model.get('id'), path=model.get('path'), field=row.get('column')))
            findings.append(finding('sql_contract_scope', 'passed' if report['status'] == 'passed'
                            else 'failed' if report['status'] == 'failed'
                            else 'unsupported' if report['status'] == 'unsupported' else 'not_run'))
    mapped = {row['path'] for row in contract['models']}
    for path in paths:
        if Path(path).suffix.lower() == '.sql' and path not in mapped:
            findings.append(finding('unmapped_sql_output', 'not_run', path=path))
    require(capture(root, paths) == before, 'Candidate changed during authoring checks')
    result = make_receipt(contract, before, findings, checker_sha256=version, source_evidence=evidence)
    result['dialect'] = dialect
    # Do not reuse missing-input observations: a previously absent source may arrive.
    if all(f['status'] == 'passed' for f in result['findings']):
        _OBSERVATION_CACHE[cache_key] = copy.deepcopy(result)
        _OBSERVATION_CACHE.move_to_end(cache_key)
        while len(_OBSERVATION_CACHE) > MAX_CACHED_OBSERVATIONS:
            _OBSERVATION_CACHE.popitem(last=False)
    return result


def bindings(state):
    return {'source_sha256': state['inputs']['source']['fingerprint']['value'],
            'design_sha256': state['workflow']['design']['sha256'],
            'catalogue_sha256': (state['inputs'].get('catalogue') or {}).get('sha256')}


def default_contract(state, task, mode):
    import engagement_stages as stages
    entities = {row['id']: row for row in stages.design(state)['entities']}
    scope = stages.closure({key: row['depends_on'] for key, row in entities.items()}, task['entity_ids'])
    # File ownership does not establish a model-to-file mapping. Ask the worker
    # for that explicit association; do not guess from matching short names.
    return {'schema_version': 1, 'kind': 'authoring_contract', 'mode': mode,
            'bindings': bindings(state), 'models': [
                {'id': key, 'path': None, 'columns': [c['name'] for c in entities[key]['columns']],
                 'depends_on': None} for key in scope], 'assumptions': [
                {'id': 'catalogue', 'model_ids': scope, 'fields': [], 'category': 'physical',
                 'status': 'unresolved', 'required_check': 'Resolve catalogue bindings before physical validation.',
                 'evidence_refs': []}] if not state['inputs'].get('catalogue') else [], 'provenance': []}


def task_contract(state, task, mode, supplied=None):
    default = default_contract(state, task, mode)
    contract = validate_contract(supplied or default)
    require(contract['bindings'] == default['bindings'] and contract['mode'] == mode,
            'Authoring contract is stale or belongs to a different generation mode')
    known = {row['id']: row for row in default['models']}
    require({row['id'] for row in contract['models']} == set(known), 'Authoring model scope differs from task dependency closure')
    doc = {row['id']: row for row in state['workflow']['design']['entities']}
    for model in contract['models']:
        require(model['columns'] is None or model['columns'] == known[model['id']]['columns'],
                'Authoring output columns differ from the pinned design')
        if model['path'] is not None:
            require(any(model['id'] in owner['entity_ids'] and model['path'] in owner['outputs']
                        for owner in state['workflow']['tasks'] if owner['stage'] == task['stage']),
                    'Authoring model path is outside declared stage ownership')
        if model['depends_on'] is not None:
            internal = {key for key in model['depends_on'] if key in doc}
            require(internal == set(doc[model['id']]['depends_on']), 'Authoring dependencies differ from pinned design')
            require(all(key in doc or key.startswith(('source:', 'ref:', 'table:')) for key in model['depends_on']),
                    'External dependencies need an explicit reference kind')
    # A supplied contract cannot erase the known absence of a catalogue.
    if default['assumptions']:
        covered = {model for item in contract['assumptions'] if item['category'] == 'physical'
                   and item['status'] != 'resolved' for model in item['model_ids']}
        require(set(known) <= covered, 'Missing catalogue must remain unresolved for every scoped model')
    return contract


def observe_task(state, root, task, mode, *, observation_id, run_id=None, contract=None):
    import guided_workflow as guided
    import engagement_stages as stages
    stages.identifier(observation_id)
    require(not any(item['id'] == observation_id for item in state['workflow'].get('authoring_observations', [])),
            'Authoring observation ID already recorded')
    contract = task_contract(state, task, mode, contract)
    paths = sorted(set(task['outputs']) | {m['path'] for m in contract['models'] if m['path'] is not None})
    dialect = target_dialect(state)
    receipt = evaluate(root, state['inputs']['source']['path'], contract, paths, dialect)
    from naming_artifacts import observe_task as observe_naming
    naming_report = observe_naming(state, root, task, contract)
    if naming_report is not None:
        receipt['findings'].extend(naming_report['findings'])
        from authoring_evidence import summarize
        receipt.update(summarize(receipt['findings']))
        receipt['naming_scope_sha256'] = naming_report['scope_sha256']
    observation = {'schema_version': 1, 'id': observation_id, 'task_id': task['id'],
                   'run_id': run_id, 'recorded_at': guided._now(), 'contract': contract,
                   'task_sha256': hash_json(task), 'target_sha256': state['inputs']['target']['sha256'],
                   'dialect': dialect, 'receipt': receipt}
    state['workflow'].setdefault('authoring_observations', []).append(observation)
    return observation


def recheck_task(state, root, request):
    import engagement_stages as stages
    fields(request, ('schema_version', 'task_id', 'observation_id'), ('contract',))
    require(type(request['schema_version']) is int and request['schema_version'] == 1, 'Unsupported check-task version')
    task = next((t for t in state['workflow']['tasks'] if t['id'] == request['task_id']), None)
    require(task and task['stage'] in {'implementation', 'semantic'}, 'Authoring check needs an existing code task')
    runs = [run for run in state['workflow']['runs'] if run['task_id'] == task['id']]
    require(runs, 'Record task outputs before rechecking them')
    latest = runs[-1]
    require(capture(root, task['outputs']) == latest['outputs'], 'Recheck cannot impersonate changed authoring outputs')
    scope = stages.closure({e['id']: e['depends_on'] for e in stages.design(state)['entities']}, task['entity_ids'])
    reviewed = (state['readiness']['generation_ready']
                and set(scope) <= stages.approved_entities(state, stage=task['stage'])
                and not stages._design_gaps(state, scope, task['stage']))
    mode = 'reviewed_candidate' if reviewed else 'provisional'
    # Rechecks attach evidence; they never turn historical drafts into reviewed
    # authoring runs merely because approval arrived later.
    if latest.get('generation_mode') == 'provisional': mode = 'provisional'
    return observe_task(state, root, task, mode, observation_id=request['observation_id'],
                        run_id=latest['run_id'], contract=request.get('contract'))


def summaries(state):
    latest = {row['task_id']: row for row in state['workflow'].get('authoring_observations', [])}
    result = []
    root = state['workflow'].get('artifact_root')
    version = checker_version() if latest else None
    tasks = {t['id']: t for t in state['workflow']['tasks']}
    for task_id, item in latest.items():
        receipt = item['receipt']
        fresh = False
        try:
            task = tasks[task_id]
            fresh = (receipt['bindings'] == bindings(state) and receipt['checker_sha256'] == version
                     and item.get('task_sha256') == hash_json(task)
                     and item.get('target_sha256') == state['inputs']['target']['sha256']
                     and item['dialect'] == target_dialect(state)
                     and hash_json(item['contract']) == receipt['contract_sha256']
                     and capture(root, list(receipt['outputs'])) == receipt['outputs']
                     and capture(state['inputs']['source']['path'], list(receipt['source_evidence'])) == receipt['source_evidence'])
            if receipt.get('naming_scope_sha256'):
                from naming_artifacts import _pins
                from naming_governance import records
                wanted = {m['id'] for m in item['contract']['models'] if m.get('path') in task['outputs'] and Path(m['path']).suffix.lower() == '.sql'}
                fresh = fresh and receipt['naming_scope_sha256'] == _pins(state,
                    [r['id'] for r in records(state) if r['entity_id'] in wanted])
        except (OSError, ValueError, TypeError, KeyError, StopIteration): pass
        result.append({'task_id': task_id, 'observation_id': item['id'], 'run_id': item['run_id'],
                       'mode': receipt['mode'],
                       'status': receipt['status'] if fresh else 'stale', 'counts': receipt['counts'],
                       'model_ids': [m['id'] for m in item['contract']['models']],
                       'findings': copy.deepcopy(receipt['findings']),
                       'unresolved_assumptions': sum(a['status'] != 'resolved' for a in receipt['assumptions']),
                       'qualification': receipt['authority']})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--contract', type=Path, required=True)
    parser.add_argument('--paths', nargs='+', required=True)
    parser.add_argument('--dialect', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        # Reports may live beside candidates, but must never replace an input,
        # a symlink, or previously recorded evidence.
        require(not args.output.exists() and not args.output.is_symlink(), 'Evidence output must be new')
        destination = _path(args.output, must_exist=False)
        require(all(base != destination and base not in destination.parents
                    for base in (_path(args.root), _path(args.source_root))),
                'Evidence output must stay outside candidate and source roots')
        result = evaluate(args.root, args.source_root, load_json(args.contract), args.paths, args.dialect)
        write_json(args.output, result)
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(2, 'Authoring checks could not complete: ' + str(exc) + '\n')
    print(json.dumps({k: result[k] for k in ('status', 'counts', 'total')}))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__': raise SystemExit(main())
