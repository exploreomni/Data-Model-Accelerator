"""Cross-artifact integration tests using explicitly synthetic native receipts."""
import copy
from datetime import timedelta
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
from ae_common import hash_file, hash_json, load_json, snapshot, write_json
from benchmark_results import compare
from freeze_benchmark import freeze
from plan_refactor import make_plan
from test_dbt_evidence import make_fixture
from verify_dbt_evidence import instant


class RefactorRunTests(unittest.TestCase):
    def setUp(self):
        from verify_refactor_run import verify_run
        from repair_events import append_event
        self.verify_run = verify_run
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.native = make_fixture(self.root / 'native')
        self.candidate = self.native.parent / 'project'
        self.source = self.root / 'source'
        shutil.copytree(self.candidate, self.source)
        (self.source / 'models/fact.sql').unlink()
        spec = {'schema_version': 1, 'catalogue_sha256': 'a' * 64,
                'models': [{'id': 'fact', 'domain': 'billing', 'layer': 'marts', 'path': 'models/fact.sql',
                            'depends_on': ['source.staging'], 'decision_status': 'accepted', 'rule_ids': ['r1']}],
                'external_dependencies': ['source.staging'], 'shared_paths': {}}
        write_json(self.root / 'spec.json', spec)
        plan = make_plan(self.source, spec)
        write_json(self.root / 'plan.json', plan)
        write_json(self.root / 'expected.json', {'rows': [{'id': 1}]})
        case = {'id': 'metric', 'category': 'compatibility',
                'context': {'timezone': 'UTC', 'principal': 'synthetic', 'watermark': 'fixture'},
                'keys': ['id'], 'columns': {'id': {'type': 'integer', 'nullable': False}},
                'expected': {'path': 'expected.json', 'sha256': hash_file(self.root / 'expected.json'), 'query_id': 'synthetic-oracle'}}
        contract = {'schema_version': 1, 'analyst_id': 'analyst-1',
                    'source_revision': plan['source_snapshot']['sha256'], 'catalogue_sha256': 'a' * 64, 'cases': [case]}
        write_json(self.root / 'contract.json', contract)
        baseline = freeze(self.root / 'contract.json', self.root / 'baseline.json')
        native = load_json(self.native)
        start = instant(native['execution']['started_at'], 'native')
        finish = instant(native['execution']['finished_at'], 'native')
        # These are synthetic artifact timestamps, not observed process/agent times.
        baseline['created_at'] = (start - timedelta(seconds=20)).isoformat()
        baseline['baseline_sha256'] = hash_json({k: v for k, v in baseline.items() if k != 'baseline_sha256'})
        self.save('baseline.json', baseline)
        write_json(self.root / 'actual-rows.json', {'rows': [{'id': 1}]})
        actual = {'schema_version': 1, 'baseline_sha256': baseline['baseline_sha256'],
                  'candidate_sha256': snapshot(self.candidate)['sha256'], 'analyst_id': 'analyst-1',
                  'cases': [{'id': 'metric', 'context': case['context'], 'result': {
                      'path': 'actual-rows.json', 'sha256': hash_file(self.root / 'actual-rows.json'), 'query_id': 'synthetic-candidate'}}]}
        write_json(self.root / 'actual.json', actual)
        write_json(self.root / 'benchmark.json', compare(self.root / 'baseline.json', self.root / 'actual.json', self.candidate))
        task_id = plan['tasks'][0]['task_id']
        event = append_event(self.root / 'events.jsonl', {'kind': 'validation_passed',
            'candidate_sha256': actual['candidate_sha256'], 'evidence_sha256': hash_file(self.root / 'benchmark.json'),
            'at': (finish + timedelta(seconds=1)).isoformat(), 'actor_id': 'analyst-1', 'task_id': None, 'case_ids': []},
            '0' * 64, {'metric'}, {task_id})
        self.record = {'schema_version': 1, 'execution_mode': 'fixture_replay', 'candidate_project': str(self.candidate),
                       'tasks': [{'task_id': task_id, 'host': 'synthetic-host', 'agent_id': 'engineer-1', 'run_id': 'engineering-run',
                                  'started_at': (start - timedelta(seconds=15)).isoformat(), 'finished_at': (start - timedelta(seconds=1)).isoformat(),
                                  'files': [{'path': 'models/fact.sql', 'before_sha256': None, 'after_sha256': hash_file(self.candidate / 'models/fact.sql')}]}],
                       'analyst': {'host': 'synthetic-host', 'agent_id': 'analyst-1', 'run_id': 'analyst-run',
                                   'started_at': (start - timedelta(seconds=25)).isoformat(), 'finished_at': (finish + timedelta(seconds=2)).isoformat()},
                       'events_head': event['event_sha256'], 'event_evidence': [self.assoc('benchmark.json')]}
        for name, file in [('plan', 'plan.json'), ('specification', 'spec.json'), ('baseline', 'baseline.json'),
                           ('actual', 'actual.json'), ('benchmark', 'benchmark.json'), ('events', 'events.jsonl')]:
            self.record[name] = self.assoc(file)
        self.record['native'] = {'path': str(self.native), 'sha256': hash_file(self.native)}
        self.path = self.root / 'run.json'

    def save(self, name, value):
        (self.root / name).write_text(json.dumps(value))

    def assoc(self, name):
        return {'path': name, 'sha256': hash_file(self.root / name)}

    def check(self):
        self.save('run.json', self.record)
        return self.verify_run(self.path)

    def denied(self):
        result = self.check()
        self.assertFalse(result['evidence_complete'], result)
        self.assertEqual(result['state'], 'incomplete')
        self.assertTrue(result['errors'])

    def test_complete_evidence_is_local_and_explicit_fixture_replay(self):
        result = self.check()
        self.assertTrue(result['evidence_complete'], result)
        self.assertEqual(result['state'], 'local_validated')
        self.assertEqual(result['execution_mode'], 'fixture_replay')
        self.assertEqual(result['changed_files'], 1)

    def test_self_review_and_reused_run_ids_rejected(self):
        original = copy.deepcopy(self.record)
        for field, value in [('agent_id', 'analyst-1'), ('run_id', 'analyst-run')]:
            self.record = copy.deepcopy(original)
            self.record['tasks'][0][field] = value
            self.denied()

    def test_missing_duplicate_or_invented_task_rejected(self):
        original = copy.deepcopy(self.record['tasks'])
        for tasks in ([], original * 2, [dict(original[0], task_id='invented')]):
            self.record['tasks'] = tasks
            self.denied()

    def test_unowned_and_omitted_changes_rejected(self):
        self.record['tasks'][0]['files'] = []
        self.denied()
        (self.candidate / 'unowned.txt').write_text('unexpected')
        self.denied()

    def test_source_drift_rejected(self):
        (self.source / 'dbt_project.yml').write_text('changed source')
        self.denied()

    def test_rehashed_plan_edit_rejected(self):
        plan = load_json(self.root / 'plan.json')
        plan['tasks'][0]['allowed_writes'].append('anything.sql')
        self.save('plan.json', plan)
        self.record['plan'] = self.assoc('plan.json')
        self.denied()

    def test_candidate_edit_invalidates_native_build_even_with_updated_file_claim(self):
        path = self.candidate / 'models/fact.sql'
        path.write_text(path.read_text() + '\n-- changed after validation\n')
        self.record['tasks'][0]['files'][0]['after_sha256'] = hash_file(path)
        self.denied()

    def test_false_benchmark_summary_cannot_replace_recomputation(self):
        benchmark = load_json(self.root / 'benchmark.json')
        benchmark['coverage']['passed_cases'] = 999
        self.save('benchmark.json', benchmark)
        self.record['benchmark'] = self.assoc('benchmark.json')
        self.denied()

    def test_changed_expected_results_rejected(self):
        self.save('expected.json', {'rows': [{'id': 2}]})
        self.denied()

    def test_missing_actual_case_cannot_be_hidden_by_summary(self):
        actual = load_json(self.root / 'actual.json')
        actual['cases'] = []
        self.save('actual.json', actual)
        self.record['actual'] = self.assoc('actual.json')
        self.denied()

    def test_missing_or_changed_event_evidence_rejected(self):
        self.record['event_evidence'] = []
        self.denied()
        self.record['event_evidence'] = [self.assoc('benchmark.json')]
        self.record['events_head'] = 'f' * 64
        self.denied()

    def test_engineering_before_baseline_and_premature_analyst_finish_rejected(self):
        original = copy.deepcopy(self.record)
        self.record['tasks'][0]['started_at'] = self.record['analyst']['started_at']
        self.denied()
        self.record = original
        self.record['analyst']['finished_at'] = self.record['tasks'][0]['finished_at']
        self.denied()

    def test_unexecuted_or_unknown_record_fields_rejected(self):
        self.record['execution_mode'] = 'planned'
        self.denied()
        self.record['execution_mode'] = 'fixture_replay'
        self.record['silently_approve'] = True
        self.denied()

    def add_foundation(self):
        spec = load_json(self.root / 'spec.json')
        spec['models'][0]['depends_on'] = ['stg']
        spec['models'].append({'id': 'stg', 'domain': 'foundation', 'layer': 'staging', 'path': 'models/stg_invoice.sql',
                               'depends_on': ['source.staging'], 'decision_status': 'accepted', 'rule_ids': ['r0']})
        self.save('spec.json', spec)
        self.save('plan.json', make_plan(self.source, spec))
        self.record['specification'], self.record['plan'] = self.assoc('spec.json'), self.assoc('plan.json')
        start = instant(self.record['tasks'][0]['started_at'], 'billing start')
        self.record['tasks'].append({'task_id': 'analytics-engineer-foundation', 'host': 'synthetic-host',
                                    'agent_id': 'foundation-engineer', 'run_id': 'foundation-run',
                                    'started_at': (start - timedelta(seconds=3)).isoformat(),
                                    'finished_at': (start - timedelta(seconds=1)).isoformat(), 'files': []})

    def test_multiple_domains_require_dependency_order_and_exact_file_owner(self):
        self.add_foundation()
        self.assertTrue(self.check()['evidence_complete'])
        original = copy.deepcopy(self.record)
        self.record['tasks'][1]['finished_at'] = self.record['tasks'][0]['finished_at']
        self.denied()
        self.record = original
        self.record['tasks'][1]['files'] = self.record['tasks'][0]['files']
        self.record['tasks'][0]['files'] = []
        self.denied()

    def test_planned_models_cannot_be_omitted_or_satisfied_by_test_resources(self):
        original = load_json(self.root / 'spec.json')
        for path in ('models/omitted.sql', 'tests/grain.sql'):
            spec = copy.deepcopy(original)
            spec['models'].append({'id': 'promised', 'domain': 'billing', 'layer': 'marts', 'path': path,
                                   'depends_on': ['fact'], 'decision_status': 'accepted', 'rule_ids': ['r2']})
            self.save('spec.json', spec)
            self.save('plan.json', make_plan(self.source, spec))
            self.record['specification'], self.record['plan'] = self.assoc('spec.json'), self.assoc('plan.json')
            self.denied()

    def repair_history(self, wrong_baseline=False):
        from repair_events import append_event
        final = load_json(self.root / 'benchmark.json')
        failed = copy.deepcopy(final)
        failed.update(passed=False, candidate_sha256='b' * 64)
        failed['cases'][0].update(passed=False, errors=['synthetic defect'])
        if wrong_baseline:
            failed['baseline_sha256'] = 'c' * 64
        self.save('failed-benchmark.json', failed)
        task = self.record['tasks'][0]
        change = {'kind': 'repair_change', 'candidate_sha256': final['candidate_sha256'],
                  'task_id': task['task_id'], 'changed_paths': ['models/fact.sql']}
        self.save('repair.json', change)
        head = '0' * 64
        log = self.root / 'repair-history.jsonl'
        native_finish = load_json(self.native)['execution']['finished_at']
        rows = [('validation_failed', 'failed-benchmark.json', 'analyst-1', None, ['metric'], task['started_at']),
                ('repair_completed', 'repair.json', task['agent_id'], task['task_id'], ['metric'], task['finished_at']),
                ('validation_passed', 'benchmark.json', 'analyst-1', None, [], (instant(native_finish, 'native') + timedelta(seconds=1)).isoformat())]
        for kind, file, actor, task_id, cases, at in rows:
            document = load_json(self.root / file)
            event = append_event(log, {'kind': kind, 'candidate_sha256': document['candidate_sha256'],
                'evidence_sha256': hash_file(self.root / file), 'at': at, 'actor_id': actor, 'task_id': task_id, 'case_ids': cases},
                head, {'metric'}, {task['task_id']})
            head = event['event_sha256']
        self.record.update(events=self.assoc('repair-history.jsonl'), events_head=head,
                           event_evidence=[self.assoc(file) for file in ('failed-benchmark.json', 'repair.json', 'benchmark.json')])

    def test_complete_repair_history_preserves_failures_and_passes(self):
        self.repair_history()
        result = self.check()
        self.assertTrue(result['evidence_complete'], result)
        self.assertEqual(result['repair_count'], 1)

    def test_historical_validation_cannot_switch_baselines(self):
        self.repair_history(wrong_baseline=True)
        self.denied()
