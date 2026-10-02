"""Replay boundaries against temporary fixtures; no native dbt or real agents."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
import ae_common as common
import run_refactor_qualification as qualification


class RefactorQualificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.fixture = self.root / 'fixture'
        for directory in ('input/repo', 'oracle', 'candidate/models/marts'):
            (self.fixture / directory).mkdir(parents=True)
        self.fixture_patch = patch.object(qualification, 'FIXTURE', self.fixture)
        self.fixture_patch.start()
        self.addCleanup(self.fixture_patch.stop)
        project_text = 'name: rental_trial\nconfig-version: 2\n'
        (self.fixture / 'input/repo/dbt_project.yml').write_text(project_text)
        (self.fixture / 'candidate/dbt_project.yml').write_text(project_text)
        (self.fixture / 'candidate/models/marts/fact.sql').write_text('select 1 as id\n')
        common.write_json(self.fixture / 'input/catalogue.json', {'origin': 'synthetic-test'})
        self.spec = {'schema_version': 1, 'catalogue_sha256': common.hash_file(self.fixture / 'input/catalogue.json'),
                     'models': [{'id': 'fact', 'domain': 'rental', 'layer': 'marts', 'path': 'models/marts/fact.sql',
                                 'depends_on': [], 'decision_status': 'accepted', 'rule_ids': ['r1']}],
                     'external_dependencies': [], 'shared_paths': {}}
        common.write_json(self.fixture / 'input/model-spec.json', self.spec)
        common.write_json(self.fixture / 'oracle/expected.json', {'rows': [{'id': 1}]})
        common.write_json(self.fixture / 'oracle/queries.json', {'metric': 'select 1 as id'})
        contract = {'schema_version': 1, 'analyst_id': 'analyst-1', 'source_revision': 'template-placeholder',
                    'catalogue_sha256': self.spec['catalogue_sha256'], 'cases': [{
                        'id': 'metric', 'category': 'compatibility',
                        'context': {'timezone': 'UTC', 'principal': 'synthetic', 'watermark': 'fixture'},
                        'keys': ['id'], 'columns': {'id': {'type': 'integer', 'nullable': False}},
                        'expected': {'path': 'expected.json', 'sha256': common.hash_file(self.fixture / 'oracle/expected.json'),
                                     'query_id': 'synthetic-test-query'}}]}
        common.write_json(self.fixture / 'oracle/contract-template.json', contract)
        self.freeze_pins()

    def freeze_pins(self):
        pins = {'schema_version': 1, 'files': qualification.fixture_inventory()}
        (self.fixture / 'fixture-pins.json').write_text(json.dumps(pins))

    def test_pins_bind_source_oracle_query_expected_and_candidate_bytes(self):
        self.assertEqual(qualification.verify_fixture(), qualification.fixture_inventory())
        for name in ('input/repo/dbt_project.yml', 'input/catalogue.json', 'oracle/queries.json',
                     'oracle/expected.json', 'candidate/models/marts/fact.sql'):
            path = self.fixture / name
            original = path.read_bytes()
            path.write_bytes(original + b'\n')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'frozen pins'):
                qualification.verify_fixture()
            path.write_bytes(original)

    def test_pin_inventory_rejects_added_deleted_or_unlisted_files(self):
        for scope in ('input', 'oracle', 'candidate'):
            path = self.fixture / scope / 'unlisted.txt'
            path.write_text('not frozen')
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                qualification.verify_fixture()
            path.unlink()
        path = self.fixture / 'oracle/queries.json'
        original = path.read_bytes()
        path.unlink()
        with self.assertRaises(ValueError):
            qualification.verify_fixture()
        path.write_bytes(original)
        pins = common.load_json(self.fixture / 'fixture-pins.json')
        del pins['files']['candidate/models/marts/fact.sql']
        (self.fixture / 'fixture-pins.json').write_text(json.dumps(pins))
        with self.assertRaises(ValueError):
            qualification.verify_fixture()

    def test_fixture_file_directory_and_scope_symlinks_are_rejected(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'secret.txt').write_text('must not be copied')
        for target, is_directory in ((outside / 'secret.txt', False), (outside, True)):
            link = self.fixture / 'input/link'
            link.symlink_to(target, target_is_directory=is_directory)
            with self.subTest(target=target), self.assertRaises(ValueError):
                qualification.fixture_inventory()
            link.unlink()
        moved = self.root / 'saved-oracle'
        (self.fixture / 'oracle').rename(moved)
        (self.fixture / 'oracle').symlink_to(moved, target_is_directory=True)
        with self.assertRaises(ValueError):
            qualification.fixture_inventory()

    def test_output_traversal_symlink_ancestor_and_fixture_child_fail_before_writes(self):
        existing = self.root / 'existing'
        existing.mkdir()
        outside = self.root / 'external'
        outside.mkdir()
        alias = self.root / 'alias'
        alias.symlink_to(outside, target_is_directory=True)
        attempted = [existing / '..' / 'escaped', alias / 'run', self.fixture / 'new-run']
        resolved = [self.root / 'escaped', outside / 'run', self.fixture / 'new-run']
        for output, destination in zip(attempted, resolved):
            with self.subTest(output=output), self.assertRaises(ValueError):
                qualification.prepare(output)
            self.assertFalse(destination.exists())

    def test_explicit_authoring_freezes_inputs_but_allows_candidate_in_progress(self):
        (self.fixture / 'fixture-pins.json').unlink()
        state = qualification.prepare(self.root / 'authoring', authoring=True)
        self.assertEqual(state['scopes'], ('input', 'oracle'))
        (self.fixture / 'candidate/models/marts/fact.sql').write_text('new authoring code')
        qualification.check_inputs(state)
        (self.fixture / 'oracle/queries.json').write_text('{"metric":"select 2 as id"}')
        with self.assertRaisesRegex(ValueError, 'inputs changed'):
            qualification.check_inputs(state)

    def test_input_drift_blocks_evaluation_before_native_invocation(self):
        state = qualification.prepare(self.root / 'prepared')
        (self.fixture / 'oracle/queries.json').write_text('{"metric":"select 2 as id"}')
        with patch.dict(sys.modules, {'duckdb': SimpleNamespace()}), patch.object(qualification, 'run_project') as native:
            with self.assertRaisesRegex(ValueError, 'inputs changed'):
                qualification.evaluate(state, self.fixture / 'candidate', 'accepted', '/unused/dbt')
            native.assert_not_called()
        self.assertFalse((state['output'] / 'accepted').exists())

    def test_input_drift_during_evaluation_blocks_benchmark_publication(self):
        state = qualification.prepare(self.root / 'prepared')
        class Connection:
            description = [('id',)]
            def __init__(self): self.rows = iter([(1,)])
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def execute(self, query): return self
            def fetchone(self): return next(self.rows, None)
        def native(*args, **kwargs):
            (self.fixture / 'oracle/queries.json').write_text('{"metric":"select 2 as id"}')
            return {'evidence_complete': True}
        modules = {'duckdb': SimpleNamespace(connect=lambda *a, **k: Connection()),
                   'yaml': SimpleNamespace(safe_dump=lambda value: 'synthetic-profile')}
        with patch.dict(sys.modules, modules), patch.object(qualification, 'run_project', side_effect=native):
            with self.assertRaisesRegex(ValueError, 'inputs changed'):
                qualification.evaluate(state, self.fixture / 'candidate', 'accepted', '/unused/dbt')
        self.assertFalse((state['output'] / 'accepted/benchmark.json').exists())

    def finish_fixture(self):
        state = qualification.prepare(self.root / 'prepared')
        accepted = state['output'] / 'accepted'
        accepted.mkdir()
        candidate = accepted / 'candidate'
        shutil.copytree(self.fixture / 'candidate', candidate)
        benchmark = {'passed': True, 'candidate_sha256': common.snapshot(candidate)['sha256']}
        common.write_json(accepted / 'benchmark.json', benchmark)
        common.write_json(accepted / 'actual.json', {})
        common.write_json(accepted / 'receipt.json', {})
        result = {'output': accepted, 'candidate': candidate, 'benchmark': benchmark,
                  'native': {'evidence_complete': True, 'receipt_path': str(accepted / 'receipt.json')}}
        actor = {'host': 'host', 'agent_id': 'analyst-1', 'run_id': 'analyst-run',
                 'started_at': '2026-09-23T10:00:00+00:00', 'finished_at': '2026-09-23T11:00:00+00:00'}
        actors = {'analyst': actor, 'validation_at': '2026-09-23T10:59:00+00:00', 'tasks': {
            state['plan']['tasks'][0]['task_id']: {'host': 'host', 'agent_id': 'engineer-1', 'run_id': 'engineer-run',
                'started_at': '2026-09-23T10:10:00+00:00', 'finished_at': '2026-09-23T10:30:00+00:00'}}}
        return state, result, actors

    def test_invalid_typed_export_is_retained_as_failed_full_benchmark_case(self):
        state = qualification.prepare(self.root / 'prepared')
        class Connection:
            description = [('id',)]
            def __init__(self): self.rows = iter([(1,), (1,)])
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def execute(self, query): return self
            def fetchone(self): return next(self.rows, None)
        modules = {'duckdb': SimpleNamespace(connect=lambda *a, **k: Connection()),
                   'yaml': SimpleNamespace(safe_dump=lambda value: 'synthetic-profile')}
        with patch.dict(sys.modules, modules), patch.object(qualification, 'run_project', return_value={'evidence_complete': True}):
            result = qualification.evaluate(state, self.fixture / 'candidate', 'duplicate', '/unused/dbt')
        self.assertFalse(result['benchmark']['passed'])
        self.assertEqual(result['benchmark']['coverage']['expected_cases'], 1)
        self.assertEqual(result['benchmark']['coverage']['failed_cases'], 1)
        errors = common.load_json(result['output'] / 'export-errors.json')['errors']
        self.assertEqual(errors, [{'case_id': 'metric', 'error': 'Duplicate composite key'}])
        self.assertFalse((result['output'] / 'result-metric.json').exists())

    def test_host_timestamp_preservation_and_required_completion_metadata(self):
        state, result, actors = self.finish_fixture()
        original = copy.deepcopy(actors)
        # Integration validity is tested elsewhere; this isolates timestamp handling.
        with patch.object(qualification, 'verify_run', return_value={'evidence_complete': True, 'errors': []}), \
                patch.object(qualification, 'now', side_effect=AssertionError('Host timestamps cannot use coordinator now')):
            qualification.finish(state, result, actors, mode='host_subagent')
        record = common.load_json(state['output'] / 'run-record.json')
        self.assertEqual(record['execution_mode'], 'host_subagent')
        self.assertEqual(record['analyst'], original['analyst'])
        event = json.loads((state['output'] / 'events.jsonl').read_text())
        self.assertEqual(event['at'], original['validation_at'])
        self.assertEqual(actors, original)
        for name in ('validation_at', 'finished_at'):
            missing = copy.deepcopy(original)
            if name == 'validation_at': del missing[name]
            else: del missing['analyst'][name]
            alternative = self.root / ('missing-' + name)
            shutil.copytree(state['output'], alternative)
            for filename in ('events.jsonl', 'run-record.json', 'run-verification.json'):
                (alternative / filename).unlink()
            alternate_state = dict(state, output=alternative)
            with self.subTest(name=name), self.assertRaises((ValueError, KeyError)):
                qualification.finish(alternate_state, result, missing, mode='host_subagent')
            self.assertFalse((alternative / 'run-record.json').exists())

    def test_replay_timestamps_and_mode_are_explicitly_synthetic(self):
        state, result, actors = self.finish_fixture()
        with patch.object(qualification, 'verify_run', return_value={'evidence_complete': True, 'errors': []}), \
                patch.object(qualification, 'now', side_effect=['2026-09-23T12:00:00Z', '2026-09-23T12:01:00Z']):
            qualification.finish(state, result, actors, mode='fixture_replay')
        record = common.load_json(state['output'] / 'run-record.json')
        self.assertEqual(record['execution_mode'], 'fixture_replay')
        self.assertEqual(record['analyst']['finished_at'], '2026-09-23T12:01:00Z')
        event = json.loads((state['output'] / 'events.jsonl').read_text())
        self.assertEqual(event['at'], '2026-09-23T12:00:00Z')

    def test_multi_domain_fixture_rejected_before_execution(self):
        other = copy.deepcopy(self.spec['models'][0])
        other.update(id='other', domain='other', path='models/marts/other.sql', depends_on=['fact'])
        self.spec['models'].append(other)
        (self.fixture / 'input/model-spec.json').write_text(json.dumps(self.spec))
        self.freeze_pins()
        with patch.object(qualification, 'run_project') as native:
            with self.assertRaisesRegex(ValueError, 'single-domain'):
                qualification.prepare(self.root / 'multi-domain')
            native.assert_not_called()


if __name__ == '__main__':
    unittest.main()
