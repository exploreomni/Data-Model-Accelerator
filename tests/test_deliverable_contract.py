"""Adversarial coverage checks; file presence never establishes SQL correctness."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import deliverable_contract as contract
import engagement_stages as stages
import finalize_delivery
import test_engagement_stages as fixtures


class DeliverableContractTests(unittest.TestCase):
    def setUp(self):
        self.state = {'answers': {'framework': 'dbt', 'deliverables': ['implementation'],
                                 'semantic_target': 'omni', 'migration_scope': 'model_semantic'},
                      'workflow': {'design': fixtures.candidate()}}
        self.task = {'id': 'build', 'stage': 'implementation', 'entity_ids': ['customers'],
                     'depends_on': [], 'components': [], 'outputs': ['customers.sql']}

    def test_omni_relationships_yaml_cannot_satisfy_dbt(self):
        self.task['outputs'] = ['customers.view', 'customers.topic', 'relationships.yaml']
        with self.assertRaisesRegex(ValueError, 'Omni/config YAML'):
            stages.register_tasks(self.state, {'schema_version': 1, 'tasks': [self.task]})

    def test_one_model_cannot_credit_unimplemented_entities(self):
        self.task['entity_ids'] = ['customers', 'products']
        with self.assertRaisesRegex(ValueError, 'products'):
            contract.entity_artifacts(self.state, self.task)
        self.task['entity_outputs'] = {key: ['customers.sql'] for key in self.task['entity_ids']}
        with self.assertRaisesRegex(ValueError, 'multiple entities'):
            contract.entity_artifacts(self.state, self.task)

    def test_multiple_named_outputs_and_explicit_aliases(self):
        self.task.update(entity_ids=['customers', 'products'], outputs=['models/customers.sql', 'models/products.py'])
        self.assertEqual(len(contract.entity_artifacts(self.state, self.task)), 2)
        self.task.update(outputs=['models/customer_alias.sql', 'models/products.py'],
                         entity_outputs={'customers': ['models/customer_alias.sql'], 'products': ['models/products.py']})
        self.assertEqual(contract.entity_artifacts(self.state, self.task)['customers'], ['models/customer_alias.sql'])

    def test_test_or_macro_is_not_a_model(self):
        for path in ('tests/customers.sql', 'macros/customers.sql'):
            self.task['outputs'] = [path]
            with self.assertRaises(ValueError):
                contract.entity_artifacts(self.state, self.task)

    def test_reuse_binding_requires_exact_existing_model_evidence(self):
        entity = self.state['workflow']['design']['entities'][0]
        entity.update(disposition='reuse', reuse={'existing_id': 'existing-customers'})
        self.state['workflow']['design']['existing_models'] = [{'id': 'existing-customers', 'evidence_refs': ['catalogue:customers']}]
        self.task['outputs'] = ['binding.json']
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory).resolve()
            path = Path(directory) / 'binding.json'
            path.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'Existing-model binding'):
                contract.verify_entity_files(self.state, self.task, directory)
            binding = {'schema_version': 1, 'kind': 'existing_model_binding', 'entity_id': 'customers',
                       'existing_id': 'existing-customers', 'evidence_refs': ['catalogue:customers']}
            path.write_text(json.dumps(binding))
            contract.verify_entity_files(self.state, self.task, directory)
            binding['existing_id'] = 'different'
            path.write_text(json.dumps(binding))
            with self.assertRaises(ValueError):
                contract.verify_entity_files(self.state, self.task, directory)

    def test_source_declarations_and_other_frameworks_keep_supported_paths(self):
        self.task['outputs'] = ['sources.yml']
        self.state['workflow']['design']['entities'][0]['object_kind'] = 'source'
        contract.entity_artifacts(self.state, self.task)
        self.state['answers']['framework'] = 'coalesce'
        self.task['outputs'] = ['node.yml']
        contract.entity_artifacts(self.state, self.task)
        self.state['answers']['framework'] = 'native_sql'
        self.task['outputs'] = ['customers.sql']
        contract.entity_artifacts(self.state, self.task)

    def test_python_model_shape_is_checked_without_execution(self):
        self.task['outputs'] = ['customers.py']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = root / 'customers.py'
            path.write_text('raise RuntimeError("must never execute")')
            with self.assertRaisesRegex(ValueError, 'model\\(dbt, session\\)'):
                contract.verify_entity_files(self.state, self.task, root)
            path.write_text('def model(dbt, session):\n    raise RuntimeError("must never execute")\n')
            contract.verify_entity_files(self.state, self.task, root)

    @unittest.skipUnless(importlib.util.find_spec('yaml'), 'Optional pinned YAML dependency is required for source declaration checks')
    def test_shared_sources_file_covers_each_source_table(self):
        self.task.update(entity_ids=['customers', 'products'], outputs=['sources.yml'],
                         entity_outputs={key: ['sources.yml'] for key in ('customers', 'products')})
        for e in self.state['workflow']['design']['entities']:
            e['object_kind'] = 'source'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); path = root / 'sources.yml'
            path.write_text('base_view: arbitrary_omni_view\n')
            with self.assertRaisesRegex(ValueError, 'actual sources'):
                contract.verify_entity_files(self.state, self.task, root)
            path.write_text('version: 2\nsources:\n  - name: raw\n    tables:\n      - name: customers\n')
            with self.assertRaisesRegex(ValueError, 'products'):
                contract.verify_entity_files(self.state, self.task, root)
            path.write_text(path.read_text() + '      - name: products\n')
            contract.verify_entity_files(self.state, self.task, root)

    def test_finalizer_rejects_semantic_only_category_spoof(self):
        state = {'answers': self.state['answers']}
        manifest = {'files': [{'path': 'START_HERE.html'}, {'path': '02_Implementation/orders.view',
                              'category': 'implementation', 'bytes': 20}]}
        with self.assertRaisesRegex(ValueError, 'warehouse implementation'):
            finalize_delivery.check_selected_delivery(state, {}, 'engineer', ['implementation'], manifest)

    def test_canonical_package_requires_both_stages_and_exact_packaged_bytes(self):
        doc = self.state['workflow']['design']
        doc['entities'] = [doc['entities'][0]]
        self.state['workflow']['tasks'] = [self.task]
        digest = hashlib.sha256(b'select 1').hexdigest()
        self.state['workflow']['last_plan'] = {'tasks': [{'id': 'build', 'action': 'reuse', 'outputs': {'customers.sql': digest}}]}
        manifest = {'files': [{'path': '02_Implementation/customers.sql', 'category': 'implementation',
                              'bytes': 8, 'sha256': digest}]}
        with self.assertRaisesRegex(ValueError, 'semantic code is incomplete'):
            contract.check_packaged_code(self.state, manifest)
        self.state['answers']['migration_scope'] = 'model_only'
        contract.check_packaged_code(self.state, manifest)
        manifest['files'][0]['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'implementation code is incomplete'):
            contract.check_packaged_code(self.state, manifest)

    def test_actual_stage_rejects_omni_instead_of_warehouse_without_changing_saved_plan(self):
        harness = fixtures.StageTests(methodName='test_design_only_and_forged_approval_never_unlock_code')
        harness.setUp()
        self.addCleanup(harness.doCleanups)
        before = copy.deepcopy(harness.state['workflow']['tasks'])
        task = copy.deepcopy(self.task)
        task['outputs'] = ['customers.view', 'relationships.yaml']
        with self.assertRaisesRegex(ValueError, 'native code artifacts'):
            harness.plan({'schema_version': 1, 'tasks': [task]})
        self.assertEqual(harness.state['workflow']['tasks'], before)
