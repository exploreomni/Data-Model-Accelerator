"""Associate refactor ownership, independent roles and current validation evidence.

Run records are self-attested. A trusted host must preserve agent identities and
pins. This verifier cannot authenticate agents or approve/deploy a data model.
"""
import argparse
from pathlib import Path
import sys

from ae_common import hash_file, hash_json, load_json, require, safe_relative, snapshot, write_json
from benchmark_results import compare
from freeze_benchmark import _bound_json, _export_path, _fields, _sha, _text, verify_baseline
from plan_refactor import make_plan
from repair_events import verify_events
from verify_dbt_evidence import instant, verify as verify_native

ASSOCIATIONS = ('plan', 'specification', 'baseline', 'actual', 'benchmark', 'native', 'events')


def _association(value, base, read=True):
    _fields(value, ('path', 'sha256'))
    path = _export_path(value['path'], base)
    require(hash_file(path) == _sha(value['sha256']), 'Changed run association: ' + str(path))
    return path, _bound_json(path, value['sha256'])[0] if read else None


def _actor(value, task=False):
    fields = ('host', 'agent_id', 'run_id', 'started_at', 'finished_at')
    _fields(value, fields + (('task_id', 'files') if task else ()))
    for name in ('host', 'agent_id', 'run_id'):
        _text(value[name], name)
    start, finish = instant(value['started_at'], 'agent start'), instant(value['finished_at'], 'agent finish')
    require(start <= finish, 'Agent execution chronology is reversed')
    return start, finish


def _verify(record_path):
    record_path = Path(record_path).absolute()
    record, record_hash = _bound_json(record_path)
    _fields(record, ('schema_version', 'execution_mode', 'candidate_project', 'tasks', 'analyst',
                     'events_head', 'event_evidence') + ASSOCIATIONS)
    require(type(record['schema_version']) is int and record['schema_version'] == 1, 'Unsupported refactor run schema')
    require(record['execution_mode'] in ('host_subagent', 'fixture_replay'), 'Actual host delegation or explicitly labeled fixture replay required')
    require(Path(record['candidate_project']).is_absolute(), 'Candidate project path must be absolute')
    project = Path(record['candidate_project'])
    paths, documents = {}, {}
    for name in ASSOCIATIONS:
        paths[name], documents[name] = _association(record[name], record_path.parent, read=name != 'events')
    require(len(set(paths.values())) == len(paths), 'Run associations must be distinct')
    plan, specification = documents['plan'], documents['specification']
    fresh_plan = make_plan(plan['project_root'], specification)
    require(hash_json(plan) == hash_json(fresh_plan), 'Source/specification/plan drift')
    baseline = verify_baseline(paths['baseline'])
    contract = baseline['contract']
    require(contract['source_revision'] == plan['source_snapshot']['sha256'], 'Baseline must bind the original source snapshot')
    require(contract['catalogue_sha256'] == plan['catalogue_sha256'], 'Catalogue association mismatch')
    candidate = snapshot(project)
    analyst = record['analyst']
    analyst_start, analyst_finish = _actor(analyst)
    require(analyst['agent_id'] == contract['analyst_id'], 'Frozen analyst identity mismatch')
    frozen_at = instant(baseline['created_at'], 'baseline freeze')
    require(analyst_start <= frozen_at <= analyst_finish, 'Baseline freeze outside analyst execution')
    planned = {task['task_id']: task for task in plan['tasks']}
    require(type(record['tasks']) is list, 'Execution tasks must be a list')
    executed, runs = {}, {(analyst['host'], analyst['run_id'])}
    changes = {}
    original = {entry['path']: entry['sha256'] for entry in plan['source_snapshot']['files']}
    current = {entry['path']: entry['sha256'] for entry in candidate['files']}
    difference = {path for path in set(original) | set(current) if original.get(path) != current.get(path)}
    for task in record['tasks']:
        start, finish = _actor(task, task=True)
        task_id = _text(task['task_id'], 'task_id')
        require(task_id in planned and task_id not in executed, 'Duplicate or unplanned engineering task')
        require(task['agent_id'] != analyst['agent_id'], 'Engineer cannot independently validate own work')
        run_id = (task['host'], task['run_id'])
        require(run_id not in runs, 'Reused host execution run ID')
        runs.add(run_id)
        require(frozen_at <= start <= finish <= analyst_finish, 'Engineering must follow baseline freeze and precede final analyst finish')
        require(type(task['files']) is list, 'Task file changes must be a list')
        allowed = set(planned[task_id]['allowed_writes'])
        for entry in task['files']:
            _fields(entry, ('path', 'before_sha256', 'after_sha256'))
            path = safe_relative(entry['path'])
            require(path in allowed and path not in changes and path in difference, 'Unowned, duplicated or nonchanged task file: ' + path)
            require(entry['before_sha256'] == original.get(path) and entry['after_sha256'] == current.get(path), 'Task file hash differs from source/candidate')
            changes[path] = task_id
        executed[task_id] = task
    require(set(executed) == set(planned), 'Engineering task denominator incomplete')
    require(set(changes) == difference, 'Unreported or unowned candidate changes')
    for task_id, task in executed.items():
        for parent in planned[task_id]['depends_on']:
            require(instant(executed[parent]['finished_at'], 'dependency finish') <= instant(task['started_at'], 'dependent start'), 'Dependency wave executed out of order')
    native = verify_native(paths['native'], project_root=project)
    require(native['evidence_complete'], 'Native evidence incomplete: ' + '; '.join(native['errors']))
    require(native['project_snapshot_sha256'] == candidate['sha256'], 'Native evidence is stale for candidate')
    native_document = documents['native']
    manifest_path = paths['native'].parent / safe_relative(native_document['manifest']['path'])
    manifest = load_json(manifest_path, max_bytes=100 * 1024 * 1024)
    model_bindings = {}
    for model in plan['models']:
        matches = [node for node in manifest['nodes'].values()
                   if node.get('original_file_path') == model['path'] and node.get('resource_type') == 'model'
                   and node.get('config', {}).get('enabled', True) is not False]
        require(model['path'] in current and len(matches) == 1, 'Planned model missing from enabled native model inventory: ' + model['id'])
        model_bindings[model['id']] = matches[0]['unique_id']
    native_start = instant(native_document['execution']['started_at'], 'native start')
    native_finish = instant(native_document['execution']['finished_at'], 'native finish')
    require(all(instant(task['finished_at'], 'task finish') <= native_start for task in executed.values()), 'Native build must follow completed integration')
    require(native_finish <= analyst_finish, 'Analyst finished before native validation')
    benchmark = compare(paths['baseline'], paths['actual'], project)
    require(hash_json(benchmark) == hash_json(documents['benchmark']), 'Stored benchmark differs from recomputed evidence')
    require(benchmark['passed'], 'Accuracy benchmark failed')
    cases = {case['id'] for case in contract['cases']}
    events = verify_events(paths['events'], record['events_head'], cases, set(planned))
    require(events and events[-1]['kind'] == 'validation_passed', 'Run lacks a final passing validation event')
    require(events[-1]['candidate_sha256'] == candidate['sha256'] and events[-1]['evidence_sha256'] == record['benchmark']['sha256'], 'Final event is stale or references a different benchmark')
    require(type(record['event_evidence']) is list, 'Event evidence inventory required')
    evidence = {}
    for association in record['event_evidence']:
        path, document = _association(association, record_path.parent)
        require(association['sha256'] not in evidence, 'Duplicate event evidence')
        evidence[association['sha256']] = document
    require(set(evidence) == {event['evidence_sha256'] for event in events}, 'Event evidence denominator mismatch')
    for event in events:
        at = instant(event['at'], 'event')
        require(frozen_at <= at <= analyst_finish, 'Event outside validation window')
        document = evidence[event['evidence_sha256']]
        require(document.get('candidate_sha256') == event['candidate_sha256'], 'Event candidate association mismatch')
        if event['kind'] == 'repair_completed':
            task = executed[event['task_id']]
            require(event['actor_id'] == task['agent_id'], 'Repair actor differs from file owner')
            require(instant(task['started_at'], 'repair start') <= at <= instant(task['finished_at'], 'repair finish'), 'Repair outside engineering execution')
            require(document.get('kind') == 'repair_change' and document.get('task_id') == event['task_id'], 'Repair change evidence required')
            changed = document.get('changed_paths')
            require(type(changed) is list and changed and len(set(changed)) == len(changed) and set(changed) <= set(planned[event['task_id']]['allowed_writes']), 'Repair includes unowned paths')
        else:
            require(event['actor_id'] == analyst['agent_id'], 'Validation actor is not independent analyst')
            require(document.get('baseline_sha256') == baseline['baseline_sha256'] and document.get('analyst_id') == analyst['agent_id'], 'Historical validation belongs to a different baseline or analyst')
            require(document.get('kind') == 'accuracy_benchmark' and document.get('passed') is (event['kind'] == 'validation_passed'), 'Validation event status differs from evidence')
            failed = {case['id'] for case in document.get('cases', []) if case.get('passed') is False}
            require(set(event['case_ids']) == failed, 'Failed case association differs from benchmark')
    require(native_finish <= instant(events[-1]['at'], 'final validation'), 'Final validation predates native build')
    require(snapshot(project) == candidate and hash_file(record_path) == record_hash, 'Run changed during verification')
    return {'schema_version': 1, 'kind': 'refactor_run_verification', 'evidence_complete': True,
            'state': 'local_validated' if native['validation_scope'] == 'local' else 'target_validated',
            'execution_mode': record['execution_mode'], 'record_sha256': record_hash,
            'candidate_sha256': candidate['sha256'], 'baseline_sha256': baseline['baseline_sha256'],
            'model_bindings': model_bindings, 'tasks': len(executed), 'changed_files': len(changes), 'benchmark_coverage': benchmark['coverage'],
            'repair_count': sum(event['kind'] == 'repair_completed' for event in events), 'errors': [],
            'limitations': ['Identities and history are self-attested; trusted host records and protected pins establish their authority.',
                            'Final file differences do not reveal reverted intermediate writes; use host-enforced task workspaces.',
                            'This is evidence association, not human model approval, security certification or deployment. Existing catalogue/documentation review gates remain required.']}


def verify_run(record_path):
    try:
        return _verify(record_path)
    except (ValueError, OSError, TypeError, KeyError, AttributeError) as error:
        return {'schema_version': 1, 'kind': 'refactor_run_verification', 'evidence_complete': False,
                'state': 'incomplete', 'errors': [str(error)]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('record', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        record = load_json(args.record)
        require(Path(record['candidate_project']).resolve() not in args.output.absolute().parents, 'Verification output must stay outside candidate')
        result = verify_run(args.record)
        write_json(args.output, result)
        print(result['state'] + ': ' + '; '.join(result['errors']))
        return 0 if result['evidence_complete'] else 1
    except (ValueError, OSError, KeyError) as error:
        print('Verification refused: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
