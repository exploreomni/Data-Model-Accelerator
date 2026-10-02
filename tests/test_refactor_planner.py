"""Planning and evidence invariants; no dbt, network or agent execution."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
import ae_common as common
import plan_refactor as planner


def model(model_id, domain, layer='staging', depends_on=()):
    return {'id': model_id, 'domain': domain, 'layer': layer,
            'path': 'models/' + layer + '/' + model_id + '.sql',
            'depends_on': list(depends_on), 'decision_status': 'accepted',
            'rule_ids': ['rule.' + model_id]}


class RefactorPlannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / 'project'
        self.project.mkdir()
        (self.project / 'dbt_project.yml').write_text('name: reviewed\nconfig-version: 2\n')
        self.spec = {'schema_version': 1, 'catalogue_sha256': 'a' * 64,
                     'models': [model('stg_orders', 'orders', depends_on=['source.raw.orders']),
                                model('int_orders', 'orders', 'intermediate', ['stg_orders']),
                                model('fct_revenue', 'finance', 'marts', ['int_orders'])],
                     'external_dependencies': ['source.raw.orders'],
                     'shared_paths': {'macros/keys.sql': 'orders', 'dbt_project.yml': 'orders',
                                      'documentation/model.md': 'finance'}}

    def plan(self, spec=None):
        return planner.make_plan(self.project, self.spec if spec is None else spec)

    def test_deterministic_dependency_waves_and_exact_ownership(self):
        before = common.snapshot(self.project)
        plan = self.plan()
        self.assertEqual(plan, self.plan())
        self.assertEqual(plan['waves'], [['analytics-engineer-orders'], ['analytics-engineer-finance']])
        self.assertEqual(plan['model_waves'], [['stg_orders'], ['int_orders'], ['fct_revenue']])
        self.assertEqual(plan['tasks'][0]['model_ids'], ['stg_orders', 'int_orders'])
        self.assertEqual(plan['tasks'][1]['depends_on'], ['analytics-engineer-orders'])
        self.assertEqual(plan['file_ownership']['macros/keys.sql'], {'domain': 'orders', 'model_id': None})
        self.assertIn('documentation/model.md', plan['tasks'][1]['allowed_writes'])
        self.assertEqual(plan['source_snapshot'], before)
        self.assertEqual(common.snapshot(self.project), before)
        self.assertEqual(plan['specification_sha256'], common.hash_json(self.spec))
        self.assertTrue(all(task['execution_mode'] == 'planned' for task in plan['tasks']))

    def test_task_order_independent_of_model_list_order(self):
        spec = copy.deepcopy(self.spec)
        spec['models'].reverse()
        a, b = self.plan(), self.plan(spec)
        self.assertEqual(a['waves'], b['waves'])
        self.assertEqual([t['task_id'] for t in a['tasks']], [t['task_id'] for t in b['tasks']])
        self.assertEqual(a['file_ownership'], b['file_ownership'])
        self.assertNotEqual(a['specification_sha256'], b['specification_sha256'])

    def test_source_edits_additions_and_removals_change_snapshot(self):
        first = self.plan()['source_snapshot']['sha256']
        file = self.project / 'dbt_project.yml'
        file.write_text('name: changed\nconfig-version: 2\n')
        second = self.plan()['source_snapshot']['sha256']
        self.assertNotEqual(first, second)
        extra = self.project / 'README.md'
        extra.write_text('new source context')
        self.assertNotEqual(second, self.plan()['source_snapshot']['sha256'])
        extra.unlink()
        self.assertEqual(second, self.plan()['source_snapshot']['sha256'])

    def test_model_dependency_cycle_rejected(self):
        self.spec['models'] = [model('a', 'orders', depends_on=['b']), model('b', 'orders', depends_on=['a'])]
        self.spec['shared_paths'] = {}
        with self.assertRaisesRegex(ValueError, 'Model dependency cycle'):
            self.plan()

    def test_domain_cycle_rejected_even_when_model_graph_is_acyclic(self):
        self.spec['models'] = [model('a1', 'orders'), model('b1', 'finance', depends_on=['a1']),
                               model('a2', 'orders', depends_on=['b1'])]
        with self.assertRaisesRegex(ValueError, 'Domain dependency cycle'):
            self.plan()

    def test_unresolved_dependency_rejected(self):
        self.spec['models'][0]['depends_on'] = ['absent']
        with self.assertRaisesRegex(ValueError, 'Unresolved dependencies'):
            self.plan()

    def test_later_layer_dependency_rejected(self):
        self.spec['models'][0]['depends_on'] = ['fct_revenue']
        with self.assertRaisesRegex(ValueError, 'later layer'):
            self.plan()

    def test_unaccepted_decision_rejected(self):
        self.spec['models'][0]['decision_status'] = 'proposed'
        with self.assertRaisesRegex(ValueError, 'must be accepted'):
            self.plan()

    def test_duplicate_model_and_external_overlap_rejected(self):
        for mode in ('duplicate', 'external'):
            with self.subTest(mode=mode):
                spec = copy.deepcopy(self.spec)
                if mode == 'duplicate':
                    spec['models'].append(copy.deepcopy(spec['models'][0]))
                else:
                    spec['external_dependencies'].append('stg_orders')
                with self.assertRaisesRegex(ValueError, 'Duplicate or external model id'):
                    self.plan(spec)

    def test_duplicate_casefold_and_parent_path_ownership_rejected(self):
        original = self.spec['models'][0]['path']
        for path in (original, original.upper(), original + '/child.sql'):
            with self.subTest(path=path):
                spec = copy.deepcopy(self.spec)
                spec['models'][1]['path'] = path
                with self.assertRaisesRegex(ValueError, 'overlapping file ownership'):
                    self.plan(spec)

    def test_extra_owned_paths_are_exclusive(self):
        self.spec['models'][0]['owned_paths'] = ['tests/order_grain.sql', 'models/staging/schema.yml']
        task = self.plan()['tasks'][0]
        self.assertIn('tests/order_grain.sql', task['allowed_writes'])
        self.spec['shared_paths']['tests/order_grain.sql'] = 'finance'
        with self.assertRaisesRegex(ValueError, 'overlapping file ownership'):
            self.plan()

    def test_shared_owner_requires_existing_domain(self):
        self.spec['shared_paths']['macros/keys.sql'] = 'unknown'
        with self.assertRaisesRegex(ValueError, 'no domain task'):
            self.plan()

    def test_invalid_paths_and_control_paths_rejected(self):
        for path in ('../outside.sql', '/outside.sql', 'models//x.sql', './x.sql', 'models/*.sql',
                     'models/x?.sql', 'models/[x].sql', 'C:/x.sql', 'models\\x.sql',
                     'models/\nx.sql', 'models/x.sql ', '.git/config', 'target/x.sql',
                     'dbt_packages/x.sql', 'profiles.yml', '.env.local', 'keys/private.pem'):
            with self.subTest(path=path):
                spec = copy.deepcopy(self.spec)
                spec['models'][0]['path'] = path
                with self.assertRaises(ValueError):
                    self.plan(spec)

    def test_existing_directory_or_file_parent_cannot_be_owned(self):
        for path in ('dbt_project.yml/child.sql', 'models'):
            with self.subTest(path=path):
                (self.project / 'models').mkdir(exist_ok=True)
                spec = copy.deepcopy(self.spec)
                spec['models'][0]['path'] = path
                with self.assertRaises(ValueError):
                    self.plan(spec)

    def test_symlinks_in_source_and_project_root_rejected(self):
        outside = self.root / 'outside.sql'
        outside.write_text('select 1')
        (self.project / 'link.sql').symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.plan()
        (self.project / 'link.sql').unlink()
        link = self.root / 'linked-project'
        link.symlink_to(self.project, target_is_directory=True)
        with self.assertRaises(ValueError):
            planner.make_plan(link, self.spec)

    def test_malformed_spec_fields_fail_closed(self):
        mutations = [lambda s: s.update(schema_version=True), lambda s: s.update(catalogue_sha256='A' * 64),
                     lambda s: s.update(models=[]), lambda s: s.update(extra='unreviewed'),
                     lambda s: s.update(external_dependencies='raw'),
                     lambda s: s['models'][0].update(id='bad id'),
                     lambda s: s['models'][0].update(domain='Finance'),
                     lambda s: s['models'][0].update(layer='silver'),
                     lambda s: s['models'][0].update(rule_ids=[]),
                     lambda s: s['models'][0].update(rule_ids=['r1', 'r1']),
                     lambda s: s['models'][0].update(depends_on=['source.raw.orders'] * 2),
                     lambda s: s['models'][0].update(owned_paths='models/a.sql')]
        for mutate in mutations:
            spec = copy.deepcopy(self.spec)
            mutate(spec)
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                self.plan(spec)

    def test_cli_creates_only_new_external_plan_and_prompts(self):
        spec_path = self.root / 'spec.json'
        common.write_json(spec_path, self.spec)
        output = self.root / 'plan'
        command = [sys.executable, str(SCRIPTS / 'plan_refactor.py'), '--project', str(self.project),
                   '--spec', str(spec_path), '--output', str(output)]
        before = common.snapshot(self.project)
        run = subprocess.run(command, text=True, capture_output=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        plan = common.load_json(output / 'plan.json')
        for task in plan['tasks']:
            self.assertEqual((output / task['prompt_path']).read_text(), task['prompt'])
        self.assertEqual(common.snapshot(self.project), before)
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
        command[-1] = str(self.project / 'forbidden-output')
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
        self.assertFalse((self.project / 'forbidden-output').exists())

    def test_json_loading_rejects_duplicates_nonfinite_and_size(self):
        path = self.root / 'input.json'
        for content in ('{"a": 1, "a": 2}', '{"nested":{"a":1,"a":2}}',
                        '{"a":NaN}', '{"a":Infinity}', '{"a":1e999}'):
            path.write_text(content)
            with self.subTest(content=content), self.assertRaises(ValueError):
                common.load_json(path)
        path.write_text('{"a":1}')
        with self.assertRaisesRegex(ValueError, 'byte limit'):
            common.load_json(path, max_bytes=2)

    def test_exclusive_json_write_and_canonical_hash(self):
        path = self.root / 'evidence.json'
        common.write_json(path, {'b': 2, 'a': 1})
        self.assertEqual(common.load_json(path), {'a': 1, 'b': 2})
        self.assertEqual(common.hash_json({'a': 1, 'b': 2}), common.hash_json({'b': 2, 'a': 1}))
        self.assertEqual(len(common.hash_file(path)), 64)
        with self.assertRaises(FileExistsError):
            common.write_json(path, {'changed': True})
        for invalid in ({1: 'non-string key'}, {'nan': float('nan')}, ('tuple',)):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                common.hash_json(invalid)

    def test_evidence_symlink_read_write_hash_rejected(self):
        path = self.root / 'evidence.json'
        path.write_text('{}')
        link = self.root / 'link.json'
        link.symlink_to(path)
        for operation in (lambda: common.load_json(link), lambda: common.hash_file(link),
                          lambda: common.write_json(link, {})):
            with self.assertRaises(ValueError):
                operation()


if __name__ == '__main__':
    unittest.main()
