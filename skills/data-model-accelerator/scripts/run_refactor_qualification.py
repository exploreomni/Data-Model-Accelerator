"""Replay only the bundled independent rental trial; never run a customer repo.

Fixture replay invokes no agents. The separately recorded authoring trial used
actual host agents; this replay checks its fixed artifacts with native DuckDB.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import shutil
import sys

from ae_common import _path, hash_file, hash_json, load_json, require, snapshot, write_json
from benchmark_results import compare
from export_results import serialize_rows
from freeze_benchmark import freeze
from plan_refactor import make_plan
from repair_events import append_event, ZERO_HEAD
from run_dbt_project import run_project
from verify_refactor_run import _actor, verify_run
from verify_dbt_evidence import instant

FIXTURE = Path(__file__).resolve().parents[1] / 'examples/dbt-rental-trial'


def now():
    return datetime.now(timezone.utc).isoformat()


def assoc(path):
    return {'path': str(Path(path).absolute()), 'sha256': hash_file(path)}


def fixture_inventory(scopes=('input', 'oracle', 'candidate')):
    files = {}
    for scope in scopes:
        root = FIXTURE / scope
        require(root.is_dir() and not root.is_symlink(), 'Missing or symlinked fixture scope')
        for path in sorted(root.rglob('*')):
            require(not path.is_symlink() and (path.is_file() or path.is_dir()), 'Unsupported fixture entry')
            if path.is_file():
                files[path.relative_to(FIXTURE).as_posix()] = hash_file(path)
    return files


def verify_fixture():
    pins = load_json(FIXTURE / 'fixture-pins.json')
    require(type(pins) is dict and set(pins) == {'schema_version', 'files'} and type(pins['schema_version']) is int and pins['schema_version'] == 1,
            'Invalid fixture pins')
    require(pins['files'] == fixture_inventory(), 'Fixture inventory/content differs from frozen pins')
    return pins['files']


def check_inputs(state):
    require(fixture_inventory(state['scopes']) == state['pins'], 'Trial inputs changed during execution')


def prepare(output, authoring=False):
    scopes = ('input', 'oracle') if authoring else ('input', 'oracle', 'candidate')
    pins = fixture_inventory(scopes) if authoring else verify_fixture()
    output = _path(output, must_exist=False)
    _path(output.parent)
    require(not output.exists() and FIXTURE not in output.parents, 'Use a new external qualification output')
    output.mkdir()
    source = output / 'source'
    shutil.copytree(FIXTURE / 'input/repo', source)
    specification = load_json(FIXTURE / 'input/model-spec.json')
    require(specification['catalogue_sha256'] == hash_file(FIXTURE / 'input/catalogue.json'), 'Fixture catalogue drift')
    write_json(output / 'specification.json', specification)
    plan = make_plan(source, specification)
    require(len(plan['tasks']) == 1, 'Bundled rental replay is a single-domain trial')
    write_json(output / 'plan.json', plan)
    contract = load_json(FIXTURE / 'oracle/contract-template.json')
    contract['source_revision'] = plan['source_snapshot']['sha256']
    for case in contract['cases']:
        path = Path(case['expected']['path'])
        if not path.is_absolute():
            path = (FIXTURE / 'oracle' / path).resolve()
        case['expected']['path'] = str(path)
    write_json(output / 'contract.json', contract)
    baseline = freeze(output / 'contract.json', output / 'baseline.json')
    return {'output': output, 'source': source, 'plan': plan, 'baseline': baseline, 'pins': pins, 'scopes': scopes}


def build(state, candidate_source, label, dbt_executable):
    check_inputs(state)
    import yaml
    output = state['output'] / label
    output.mkdir()
    candidate = output / 'candidate'
    shutil.copytree(candidate_source, candidate)
    candidate_hash = snapshot(candidate)['sha256']
    profiles = output / 'profiles'
    profiles.mkdir()
    database = output / (label + '.duckdb')
    profile = {'rental_trial': {'target': 'dev', 'outputs': {'dev': {
        'type': 'duckdb', 'path': str(database), 'schema': 'main', 'threads': 1}}}}
    (profiles / 'profiles.yml').write_text(yaml.safe_dump(profile), encoding='utf-8')
    request = {'schema_version': 1, 'project_sha256': candidate_hash, 'adapter_type': 'duckdb',
               'profile': 'rental_trial', 'target': 'dev', 'profiles_dir': str(profiles),
               'allowed_destinations': [{'database': label, 'schema': 'main'}],
               'expected_profile': {'path': str(database)}, 'timeout_seconds': 120}
    write_json(output / 'request.json', request)
    native = run_project(candidate, output / 'request.json', output / 'native', dbt_executable, execute=True)
    return output, candidate, database, native


def evaluate(state, candidate_source, label, dbt_executable):
    import duckdb
    output, candidate, database, native = build(state, candidate_source, label, dbt_executable)
    candidate_hash = snapshot(candidate)['sha256']
    queries = load_json(FIXTURE / 'oracle/queries.json')
    cases = state['baseline']['contract']['cases']
    require(set(queries) == {case['id'] for case in cases}, 'Acceptance query denominator differs from frozen cases')
    actual = {'schema_version': 1, 'baseline_sha256': state['baseline']['baseline_sha256'],
              'candidate_sha256': candidate_hash, 'analyst_id': state['baseline']['contract']['analyst_id'], 'cases': []}
    export_errors = []
    with duckdb.connect(str(database), read_only=True) as connection:
        for case in cases:
            query = queries[case['id']]
            require(type(query) is str, 'Acceptance SQL must be a string')
            cursor = connection.execute(query)
            try:
                rows = serialize_rows(cursor.description, iter(cursor.fetchone, None), case['columns'], case['keys'])
            except ValueError as error:
                # Preserve failed exports as missing cases in the full benchmark;
                # never coerce, truncate or publish invalid rows as passing data.
                export_errors.append({'case_id': case['id'], 'error': str(error)})
                continue
            result_path = output / ('result-' + case['id'] + '.json')
            write_json(result_path, {'rows': rows})
            # DuckDB has no remote service query ID; retain SQL bytes and local receipt identity explicitly.
            query_path = output / ('query-' + case['id'] + '.sql')
            query_path.write_text(query, encoding='utf-8')
            actual['cases'].append({'id': case['id'], 'context': case['context'],
                                   'result': dict(assoc(result_path), query_id='local-duckdb:' + hash_file(query_path))})
    write_json(output / 'actual.json', actual)
    write_json(output / 'export-errors.json', {'errors': export_errors})
    benchmark = compare(state['output'] / 'baseline.json', output / 'actual.json', candidate)
    check_inputs(state)
    write_json(output / 'benchmark.json', benchmark)
    print(label + ': native=' + str(native['evidence_complete']) + ', benchmark=' + str(benchmark['passed']), flush=True)
    return {'output': output, 'candidate': candidate, 'native': native, 'benchmark': benchmark}


def finish(state, result, actors, mode='fixture_replay'):
    require(result['native']['evidence_complete'] and result['benchmark']['passed'], 'Cannot finish failed candidate')
    output, plan, candidate = state['output'], state['plan'], result['candidate']
    before = {entry['path']: entry['sha256'] for entry in plan['source_snapshot']['files']}
    after = {entry['path']: entry['sha256'] for entry in snapshot(candidate)['files']}
    changed = {path for path in set(before) | set(after) if before.get(path) != after.get(path)}
    tasks = []
    for task in plan['tasks']:
        execution = dict(actors['tasks'][task['task_id']])
        execution.update(task_id=task['task_id'], files=[{'path': path, 'before_sha256': before.get(path), 'after_sha256': after.get(path)}
                                                       for path in sorted(changed & set(task['allowed_writes']))])
        tasks.append(execution)
    check_inputs(state)
    require(mode in ('fixture_replay', 'host_subagent'), 'Unknown trial execution mode')
    validation_at = now() if mode == 'fixture_replay' else actors['validation_at']
    analyst = dict(actors['analyst'])
    if mode == 'fixture_replay':
        analyst['finished_at'] = now()
    else:
        require('finished_at' in analyst, 'Observed analyst finish is required for host authoring')
    started, finished = _actor(analyst)
    require(started <= instant(validation_at, 'validation') <= finished, 'Validation is outside observed analyst window')
    event = append_event(output / 'events.jsonl', {'kind': 'validation_passed',
        'candidate_sha256': result['benchmark']['candidate_sha256'], 'evidence_sha256': hash_file(result['output'] / 'benchmark.json'),
        'at': validation_at, 'actor_id': actors['analyst']['agent_id'], 'task_id': None, 'case_ids': []},
        ZERO_HEAD, {case['id'] for case in state['baseline']['contract']['cases']}, {task['task_id'] for task in tasks})
    record = {'schema_version': 1, 'execution_mode': mode, 'candidate_project': str(candidate),
              'tasks': tasks, 'analyst': analyst, 'events_head': event['event_sha256'],
              'event_evidence': [assoc(result['output'] / 'benchmark.json')]}
    for name, path in [('plan', output / 'plan.json'), ('specification', output / 'specification.json'),
                       ('baseline', output / 'baseline.json'), ('actual', result['output'] / 'actual.json'),
                       ('benchmark', result['output'] / 'benchmark.json'), ('native', Path(result['native']['receipt_path'])),
                       ('events', output / 'events.jsonl')]:
        record[name] = assoc(path)
    write_json(output / 'run-record.json', record)
    verification = verify_run(output / 'run-record.json')
    write_json(output / 'run-verification.json', verification)
    require(verification['evidence_complete'], 'Integration gate failed: ' + '; '.join(verification['errors']))
    return verification


def documentation_check(state, result):
    import duckdb
    from capture_duckdb_schema import capture
    from verify_engagement import physical_denominator, qualified_relation
    from verify_physical_schema import reconcile
    candidate = result['candidate']
    from data_dictionary_v2 import migrate_dictionary
    # Normalize the historical rental shape explicitly in memory. Its pinned
    # fixture and prior receipts remain unchanged and gain no metadata approval.
    dictionary = migrate_dictionary(load_json(candidate / 'docs/data-dictionary.json'))
    models = dictionary['models']
    expected = {model['id'] for model in state['plan']['models']} | {'raw_rentals', 'raw_charges', 'raw_locations'}
    require(len(models) == len(expected) and {model['id'] for model in models} == expected, 'Dictionary model inventory incomplete')
    documents = {}
    for name in ('model-erd', 'data-dictionary', 'bronze', 'silver', 'gold'):
        text = (candidate / ('docs/' + name + '.md')).read_text(encoding='utf-8').strip()
        require(text, 'Empty model documentation: ' + name)
        documents[name] = text.lower()
    require((candidate / 'semantic/omni-contract.md').read_text().strip(), 'Missing semantic placement contract')
    database = result['output'] / (result['output'].name + '.duckdb')
    columns = 0
    with duckdb.connect(str(database), read_only=True) as connection:
        tables = {row[0] for row in connection.execute("select table_name from information_schema.tables where table_schema = 'main'").fetchall()}
        require(tables == expected, 'Physical relation inventory differs from documentation')
        for model in models:
            name, layer = model['id'], model['layer']
            require(layer in ('bronze', 'silver', 'gold') and all(name.lower() in documents[doc] for doc in (layer, 'model-erd', 'data-dictionary')),
                    'Model omitted from readable layer/ERD/dictionary: ' + name)
            require(model.get('grain') and model.get('keys') and model.get('history') and model.get('rule_ids') and 'depends_on' in model and 'tenant_relationships' in model,
                    'Incomplete dictionary contract: ' + name)
            physical = connection.execute("select column_name, data_type from information_schema.columns where table_schema = 'main' and table_name = ? order by ordinal_position", [name]).fetchall()
            declared = model['columns']
            require(len(declared) == len(physical) and {c['name'] for c in declared} == {c[0] for c in physical}, 'Column inventory mismatch: ' + name)
            actual_types = dict(physical)
            for column in declared:
                require(column.get('description') and type(column.get('nullable')) is bool, 'Incomplete column documentation')
                expected_type = column['type'].upper().replace(' ', '')
                actual_type = actual_types[column['name']].upper().replace(' ', '')
                require(expected_type == actual_type or expected_type in ('INTEGER', 'INT') and actual_type in ('INTEGER', 'BIGINT'), 'Column type mismatch: ' + name + '.' + column['name'])
                if not column['nullable']:
                    quote = lambda value: '"' + value.replace('"', '""') + '"'
                    nulls = connection.execute('select count(*) from ' + quote(name) + ' where ' + quote(column['name']) + ' is null').fetchone()[0]
                    require(nulls == 0, 'Observed null violates dictionary contract')
            columns += len(declared)
    report = {'passed': True, 'models': len(models), 'columns': columns,
              'scope': 'Bundled native relation/column/type and observed-null coverage; prose accuracy still requires review.'}
    observation = capture(database, result['native']['receipt_path'], candidate)
    receipt = load_json(result['native']['receipt_path'])
    manifest = load_json(Path(result['native']['receipt_path']).parent / receipt['manifest']['path'])
    inventory = {'schema_version': 1, 'kind': 'data_model_inventory', 'models': [
        {'model_id': model['id'], 'layer': model['layer'],
         'physical_name': qualified_relation(manifest['nodes'][model['dbt_id']]),
         'columns': [column['name'] for column in model['columns']]} for model in models]}
    require({row['physical_name'] for row in observation['relations']} == physical_denominator(manifest), 'Native metadata denominator differs')
    physical = reconcile(inventory, observation, snapshot(candidate)['sha256'])
    require(physical['passed'], 'Physical schema check failed: ' + '; '.join(physical['errors']))
    for name, document in [('physical-observation', observation), ('model-inventory', inventory), ('physical-verification', physical)]:
        write_json(result['output'] / (name + '.json'), document)
    write_json(result['output'] / 'documentation-check.json', report)
    return report


def legacy_check(state, dbt_executable):
    import duckdb
    output, candidate, database, native = build(state, state['source'], 'legacy', dbt_executable)
    require(native['evidence_complete'], 'Legacy fixture build failed')
    sql = load_json(FIXTURE / 'oracle/queries.json')['clean_compatibility'].replace('from fct_rental_revenue', 'from legacy_report')
    with duckdb.connect(str(database), read_only=True) as connection:
        cursor = connection.execute(sql)
        names = [column[0] for column in cursor.description]
        rows = [{name: str(value) if isinstance(value, Decimal) else value for name, value in zip(names, values)}
                for values in cursor.fetchall()]
    write_json(output / 'observed-compatibility.json', {'rows': rows})
    require(hash_json(rows) == hash_json(state['baseline']['expected_rows']['clean_compatibility']), 'Legacy compatibility slice differs from independent oracle')
    check_inputs(state)
    return {'passed': True, 'scope': 'Executed local legacy report clean slice only', 'receipt': native['receipt_path']}


def negative_controls(state, dbt_executable):
    results = []
    # Each mutation is an executed model defect, separate from the accepted candidate.
    for label, suffix in [('fanout', 'select * from original union all select * from original'),
                           ('missing_tenant', "select * from original where tenant_id = 'A'"),
                           ('wrong_amount', 'select * replace (net_revenue + cast(1 as decimal(18,2)) as net_revenue) from original')]:
        candidate = state['output'] / ('mutated_' + label)
        shutil.copytree(FIXTURE / 'candidate', candidate)
        gold = candidate / 'models/marts/fct_rental_revenue.sql'
        sql = gold.read_text().strip().rstrip(';')
        gold.write_text('with original as (\n' + sql + '\n)\n' + suffix + '\n')
        result = evaluate(state, candidate, 'negative_' + label, dbt_executable)
        require(not result['benchmark']['passed'], 'Negative model defect escaped: ' + label)
        results.append({'defect': label, 'detected': True, 'native_passed': result['native']['evidence_complete'],
                        'failed_cases': result['benchmark']['coverage']['failed_cases']})
    return results


def documentation_negative(state, result):
    candidate = state['output'] / 'mutated_dictionary'
    shutil.copytree(result['candidate'], candidate)
    path = candidate / 'docs/data-dictionary.json'
    dictionary = load_json(path)
    dictionary['models'][0]['columns'].pop()
    path.unlink()
    write_json(path, dictionary)
    altered = dict(result, candidate=candidate)
    try:
        documentation_check(state, altered)
    except ValueError as error:
        require('Column inventory mismatch' in str(error), 'Unexpected documentation failure: ' + str(error))
        return {'defect': 'missing_dictionary_column', 'detected': True}
    raise ValueError('Missing dictionary column escaped review')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--dbt', type=Path, default=Path(sys.executable).parent / 'dbt')
    args = parser.parse_args(argv)
    try:
        analyst_start = now()
        state = prepare(args.output)
        engineer_start = now()
        # This replay copies archived candidate bytes; it does not dispatch an engineer.
        replay_candidate = state['output'] / 'replay_candidate'
        shutil.copytree(FIXTURE / 'candidate', replay_candidate)
        engineer_finish = now()
        legacy = legacy_check(state, args.dbt)
        result = evaluate(state, replay_candidate, 'accepted', args.dbt)
        actors = {'analyst': {'host': 'fixture-replay', 'agent_id': state['baseline']['contract']['analyst_id'],
                             'run_id': 'replay-validation', 'started_at': analyst_start},
                  'tasks': {task['task_id']: {'host': 'fixture-replay', 'agent_id': 'archived-candidate',
                           'run_id': 'replay-copy-' + task['task_id'], 'started_at': engineer_start, 'finished_at': engineer_finish}
                            for task in state['plan']['tasks']}}
        documentation = documentation_check(state, result)
        verification = finish(state, result, actors)
        negatives = negative_controls(state, args.dbt)
        negatives.append(documentation_negative(state, result))
        report = {'kind': 'paired_agent_fixture_replay', 'passed': True, 'scope': 'Local DuckDB only; no agents dispatched by replay, no live Snowflake/Omni acceptance.',
                  'verification': verification, 'documentation': documentation, 'legacy_compatibility': legacy, 'negative_controls': negatives}
        write_json(state['output'] / 'qualification.json', report)
        print('Rental qualification passed', flush=True)
        return 0
    except (ValueError, OSError, KeyError) as error:
        print('Qualification failed: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
