"""Persisted intake, scoped context commands and candidate-only cache bindings."""
from contextlib import redirect_stdout, redirect_stderr
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import guided_workflow as guided
import engagement_stages as stages
import upstream_context as context
import staging_ports as ports
from test_guided_workflow import collector, BASE
from test_engagement_stages import candidate
import test_upstream_context_and_ports as context_fixtures


@unittest.skipUnless(importlib.util.find_spec('yaml'), 'Pinned PyYAML required for authored-source binding')
class GuidedContextDeliveryTests(unittest.TestCase):
    def setUp(self):
        # Reuse only its synthetic source/extraction builder, not its test cases.
        self.fixture = context_fixtures.ContextAndPortTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.source, self.target = self.fixture.root, self.fixture.source, self.fixture.target
        self.run = self.root / 'engagement'
        self.patch = patch.object(guided, '_assess_repository', collector)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        guided.start_engagement(self.source, self.run, BASE)
        guided.stage_action(self.run, 'register-source-roots', document={'schema_version': 1, 'roots': [
            {'id': 'target', 'path': str(self.target)}]})
        design = candidate()
        design['entities'] = design['entities'][:2]
        design['assets'] = design['assets'][:2]
        design['relationships'] = []
        for model, name in zip(design['entities'], ('gold', 'other')):
            model.update(id=name, name=name, domain='sales' if name == 'gold' else 'other',
                         source_paths=['models/' + name + '.sql'], depends_on=[], catalogue_pointers=[])
        self.state = guided.stage_action(self.run, 'import-design', document=design)
        self.state = guided.stage_action(self.run, 'register-domains', document={'schema_version': 1, 'domains': [
            {'id': 'sales', 'name': 'Sales', 'description': 'Synthetic domain', 'asset_ids': [],
             'source_paths': ['models/gold.sql'], 'shared_dependency_ids': []}]})
        self.extraction = {'schema_version': 1, 'extracts': [
            {'id': 'legacy', 'root_id': 'primary', 'result': self.fixture.report},
            {'id': 'target', 'root_id': 'target', 'result': self.fixture.target_report}],
            'bindings': [{'entity_id': 'gold', 'root_id': 'primary', 'native_ids': ['model.p.gold']}]}

    def command(self, action, document):
        path = self.root / (action + '.json')
        path.write_text(json.dumps(document))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            status = guided.main([action, '--run', str(self.run), '--document', str(path), '--no-render', '--json'])
        self.assertEqual(status, 0, err.getvalue())
        self.state = json.loads(out.getvalue())
        self.fixture.state = self.state
        return self.state

    def register(self):
        return self.command('record-upstream-context', self.extraction)

    def policy(self):
        node = self.fixture.node('model.p.stage')['id']
        return {'schema_version': 1, 'domain_id': 'sales', 'target_root_id': 'target',
                'source_root_ids': ['primary'], 'candidate_model_ids': ['gold'], 'missing_staging': 'propose_port',
                'staging_object_ids': [node], 'version_preference': 'compatible_target',
                'request_reference': 'synthetic://user/staging-policy'}

    def test_destination_is_optional_private_and_preserves_design_and_input_pins(self):
        self.assertNotIn('delivery_destination', guided._missing(BASE))
        before = copy.deepcopy(self.state)
        pins = stages.entity_bindings(before, ['gold', 'other'])
        destination = self.root / 'deliveries' / 'review-v1'
        self.state = guided.update_answers(self.run, {'delivery_destination': str(destination)})
        saved = guided.resume_engagement(self.run)
        self.assertEqual(saved['answers']['delivery_destination'], str(destination))
        self.assertEqual(guided._bindings(before), guided._bindings(saved))
        self.assertEqual(guided._delivery_choices(before), guided._delivery_choices(saved))
        self.assertEqual(before['workflow']['design'], saved['workflow']['design'])
        self.assertEqual(before['workflow']['approvals'], saved['workflow']['approvals'])
        self.assertEqual(pins, stages.entity_bindings(saved, ['gold', 'other']))
        self.assertFalse(destination.parent.exists())
        # A changed destination alone remains a logistics change.
        moved = guided.update_answers(self.run, {'delivery_destination': str(self.root / 'review-v2')})
        self.assertEqual(guided._bindings(saved), guided._bindings(moved))
        self.assertEqual(pins, stages.entity_bindings(moved, ['gold', 'other']))

    def test_destination_cli_answer_persists_and_rejects_unsafe_paths_without_revision(self):
        destination = self.root / 'review-v1'
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            status = guided.main(['answer', '--run', str(self.run), '--set', 'delivery_destination=' + str(destination),
                                  '--no-render', '--json'])
        self.assertEqual(status, 0, err.getvalue())
        self.assertEqual(json.loads(out.getvalue())['answers']['delivery_destination'], str(destination))
        revision = guided.load_engagement(self.run)['revision']
        link = self.root / 'alias'
        link.symlink_to(self.source, target_is_directory=True)
        for value in ('relative/path', str(self.root / '..' / 'escape'), str(link / 'version'), '/'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                guided.update_answers(self.run, {'delivery_destination': value})
        self.assertEqual(guided.load_engagement(self.run)['revision'], revision)

    def test_all_five_context_and_port_commands_persist_scoped_candidates(self):
        before = copy.deepcopy(self.state['workflow']['design'])
        source_bytes = {str(p): p.read_bytes() for root in (self.source, self.target) for p in root.rglob('*') if p.is_file()}
        self.register()
        view = self.command('upstream-context', {'entity_ids': ['gold'], 'domain_id': 'sales'})['workflow']['upstream_context_view']
        self.assertEqual(view['generation_entity_ids'], ['gold'])
        self.assertEqual({n['native_id'] for n in view['nodes']}, {'model.p.gold', 'model.p.stage', 'source.p.raw.events'})
        packet = self.command('upstream-context-packet', {'domain_id': 'sales'})['workflow']['upstream_context_packet']
        self.assertEqual(packet['generation_entity_ids'], ['gold'])
        self.assertEqual(packet['freshness'], 'selected_file_hashes_current')
        self.assertFalse(packet['source_text_included'])
        self.command('configure-staging-ports', self.policy())
        self.command('record-staging-ports', {'schema_version': 1, 'domain_id': 'sales', 'rows': [self.fixture.row()]})
        resumed = guided.resume_engagement(self.run)
        self.assertEqual(ports.summarize(resumed)['counts']['candidate'], 1)
        self.assertEqual(before, resumed['workflow']['design'])
        self.assertEqual(resumed['workflow']['tasks'], [])
        self.assertEqual(resumed['workflow']['approvals'], [])
        self.assertFalse(resumed['readiness']['execution_authorized'])
        self.assertEqual(source_bytes, {str(p): p.read_bytes() for root in (self.source, self.target) for p in root.rglob('*') if p.is_file()})

    def test_projection_requests_require_a_selector_and_cannot_cross_domain(self):
        self.register()
        revision = self.state['revision']
        for document in ({}, {'entity_ids': []}, {'entity_ids': ['unknown']},
                         {'domain_id': 'sales', 'entity_ids': ['other']}, {'domain_id': 'missing'},
                         {'entity_ids': ['gold'], 'extra': True}):
            with self.subTest(document=document), self.assertRaises(ValueError):
                guided.stage_action(self.run, 'upstream-context', document=document)
        self.assertEqual(guided.load_engagement(self.run)['revision'], revision)

    def test_packet_rejects_stale_bytes_and_registration_clears_cached_projections(self):
        self.register()
        self.command('upstream-context-packet', {'entity_ids': ['gold']})
        self.command('upstream-context', {'entity_ids': ['gold']})
        revision = self.state['revision']
        (self.source / 'models/stage.sql').write_text('select 9 as changed')
        with self.assertRaisesRegex(ValueError, 'bytes changed'):
            guided.stage_action(self.run, 'upstream-context-packet', document={'entity_ids': ['gold']})
        self.assertEqual(guided.load_engagement(self.run)['revision'], revision)
        self.register()
        self.assertNotIn('upstream_context_view', self.state['workflow'])
        self.assertNotIn('upstream_context_packet', self.state['workflow'])

    def test_upstream_bytes_and_port_policies_invalidate_only_affected_entity_pins(self):
        self.register()
        before = stages.entity_bindings(self.state, ['gold', 'other'], stage='implementation')
        self.command('configure-staging-ports', self.policy())
        policy_pins = stages.entity_bindings(self.state, ['gold', 'other'], stage='implementation')
        self.assertNotEqual(before['gold'], policy_pins['gold'])
        self.assertEqual(before['other'], policy_pins['other'])
        self.command('record-staging-ports', {'schema_version': 1, 'domain_id': 'sales', 'rows': [self.fixture.row()]})
        port_pins = stages.entity_bindings(self.state, ['gold', 'other'], stage='implementation')
        self.assertNotEqual(policy_pins['gold'], port_pins['gold'])
        self.assertEqual(policy_pins['other'], port_pins['other'])
        (self.source / 'models/stage.sql').write_text('select 9 as changed')
        changed = stages.entity_bindings(self.state, ['gold', 'other'], stage='implementation')
        self.assertNotEqual(port_pins['gold'], changed['gold'])
        self.assertEqual(port_pins['other'], changed['other'])

    def test_absent_features_keep_legacy_entity_pins_and_components_are_narrow(self):
        before = stages.entity_bindings(self.state, ['gold', 'other'])
        with patch.object(context, 'scope_bindings', return_value={}), patch.object(ports, 'scope_bindings', return_value={}):
            self.assertEqual(before, stages.entity_bindings(self.state, ['gold', 'other']))
        self.assertIn('scripts/delivery_transfer.py', stages.COMPONENT_FILES['packaging'])
        self.assertNotIn('scripts/delivery_transfer.py', stages.COMPONENT_FILES['implementation'])
        self.assertIn('scripts/upstream_context.py', stages.COMPONENT_FILES['design'])
        self.assertIn('scripts/staging_ports.py', stages.COMPONENT_FILES['implementation'])
        self.assertNotIn('scripts/staging_ports.py', stages.COMPONENT_FILES['semantic'])


if __name__ == '__main__':
    unittest.main()
