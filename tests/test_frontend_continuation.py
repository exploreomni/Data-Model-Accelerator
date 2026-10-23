"""Optional handoff behavior and isolation, without native target side effects."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import frontend_continuation as frontend
import guided_workflow as guided
import test_domain_workflow as fixtures


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.DomainTests('test_stale_selection_is_rejected')
        self.h.setUp(); self.addCleanup(self.h.doCleanups)
        self.state = self.h.state
        self.root = self.h.h.root
        self.inputs = self.h.h.artifacts
        self.request = dict(schema_version=1, domain_id='sales', choice='prepare_handoff',
            request_reference='synthetic://user/continue', dashboard_ids=['orders', 'customers'], topic_names=[])

    def test_completed_domain_selection_closure_and_unrelated_design_change(self):
        self.assertIsNone(self.state['workflow']['domain_journey']['active_domain_id'])
        first = frontend.scoped_context(self.state, 'sales')
        self.assertEqual(first['entity_ids'], ['customers', 'orders'])
        changed = copy.deepcopy(self.state)
        changed['workflow']['design']['revision'] += 1
        changed['workflow']['design']['entities'][2]['grain'] = 'Another domain changed'
        self.assertEqual(first, frontend.scoped_context(changed, 'sales'))
        changed['workflow']['design']['entities'][0]['security'] = 'Shared dependency changed'
        self.assertNotEqual(first, frontend.scoped_context(changed, 'sales'))

    def test_choice_is_repeatable_without_scope_or_authority_expansion(self):
        identity = frontend.choose(self.state, self.request)
        baseline = copy.deepcopy(self.state)
        self.assertEqual(identity, frontend.choose(self.state, self.request))
        self.assertEqual(baseline, self.state)
        self.assertEqual('independent', frontend.item(self.state, identity)['mode'])
        self.assertEqual('model_semantic', self.state['answers']['migration_scope'])
        self.assertEqual([], self.state['workflow']['approvals'])
        changed = {**self.request, 'choice': 'continue_now'}
        with self.assertRaisesRegex(ValueError, 'new user request'):
            frontend.choose(self.state, changed)
        frontend.choose(self.state, {**changed, 'request_reference': 'synthetic://user/continue-now'})
        self.assertEqual(1, len(frontend.item(self.state, identity)['history']))

    def test_decline_creates_no_packet_and_cannot_dispatch(self):
        identity = frontend.choose(self.state, {**self.request, 'choice': 'not_now'})
        output = self.root / 'declined'
        with self.assertRaisesRegex(ValueError, 'declined'):
            frontend.prepare(self.state, identity, self.inputs, output, 'synthetic://disclosure')
        self.assertFalse(output.exists())
        with self.assertRaisesRegex(ValueError, 'Declined'):
            frontend.record_progress(self.state, dict(schema_version=1, continuation_id=identity,
                scope_sha256=frontend.item(self.state, identity)['scope_sha256'], status='started', reference='test'))

    def test_missing_semantics_generates_provisional_repeatable_packet(self):
        identity = frontend.choose(self.state, self.request)
        output = self.root / 'packet'
        result = frontend.prepare(self.state, identity, self.inputs, output, 'synthetic://disclosure')
        self.assertFalse(result['agents_dispatched']); self.assertFalse(result['authorizes_target_write'])
        self.assertTrue(result['unresolved'])
        raw = (output / 'continuation.json').read_bytes()
        self.assertEqual(result, frontend.prepare(self.state, identity, self.inputs, output, 'synthetic://disclosure'))
        self.assertEqual(raw, (output / 'continuation.json').read_bytes())
        (output / 'CONTINUE.txt').unlink()
        frontend.prepare(self.state, identity, self.inputs, output, 'synthetic://disclosure')
        self.assertTrue((output / 'CONTINUE.txt').is_file())
        data = json.loads(raw)
        self.assertNotIn(str(self.root), raw.decode())
        for file in data['files']:
            self.assertEqual(file['sha256'], hashlib.sha256((output / file['path']).read_bytes()).hexdigest())

    def test_changed_files_and_symlinks_cannot_replace_existing_packet(self):
        source = self.inputs / 'inventory.json'; source.write_text('{"ids":["orders"]}')
        request = {**self.request, 'context_files': [{'path': 'inventory.json', 'purpose': 'source_inventory'}]}
        identity = frontend.choose(self.state, request); output = self.root / 'packet'
        frontend.prepare(self.state, identity, self.inputs, output, 'synthetic://disclosure')
        first = (output / 'continuation.json').read_bytes()
        source.write_text('{"ids":["orders", "customers"]}')
        with self.assertRaisesRegex(ValueError, 'Existing handoff differs'):
            frontend.prepare(self.state, identity, self.inputs, output, 'synthetic://disclosure')
        self.assertEqual(first, (output / 'continuation.json').read_bytes())
        source.unlink(); source.symlink_to(self.h.h.catalogue)
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            frontend.prepare(self.state, identity, self.inputs, self.root / 'other', 'synthetic://disclosure')

    def test_progress_and_public_projection_do_not_expose_private_inputs(self):
        identity = frontend.choose(self.state, self.request)
        row = frontend.item(self.state, identity)
        frontend.record_progress(self.state, dict(schema_version=1, continuation_id=identity,
            scope_sha256=row['scope_sha256'], status='started', reference=str(self.root), project_id='frontend-1', worker_id='worker-1'))
        summary = frontend.public_summary(self.state, ['customers', 'orders'])
        self.assertEqual('started', summary['items'][0]['status'])
        self.assertNotIn(str(self.root), json.dumps(summary))
        self.assertIsNone(frontend.public_summary(self.state, ['products']))
        self.state['workflow']['design']['entities'][0]['grain'] = 'Changed selected interface'
        self.assertEqual('stale', frontend.public_summary(self.state)['items'][0]['status'])
        self.state['workflow']['domain_journey']['domains'] = []
        row = frontend.public_summary(self.state)['items'][0]
        self.assertEqual('stale', row['status'])
        self.assertIn('no longer registered', row['next_action'])
        self.state['workflow']['domain_journey'] = None
        self.assertEqual('stale', frontend.public_summary(self.state)['items'][0]['status'])

    def test_interrupted_member_publication_retries_without_partial_files(self):
        from unittest.mock import patch
        identity = frontend.choose(self.state, self.request)
        output = self.root / 'packet'
        original = frontend.os.link
        calls = []
        def interrupt(source, target, **kwargs):
            calls.append(target)
            if len(calls) == 2: raise OSError('Synthetic interrupted publication')
            return original(source, target, **kwargs)
        with patch.object(frontend.os, 'link', side_effect=interrupt):
            with self.assertRaisesRegex(OSError, 'interrupted'):
                frontend.prepare(self.state, identity, self.inputs, output, 'synthetic://disclosure')
        self.assertTrue(calls[0].is_file())
        self.assertFalse(calls[1].exists())
        result = frontend.prepare(self.state, identity, self.inputs, output, 'synthetic://disclosure')
        self.assertEqual('handoff_prepared', result['status'])

    def test_discovery_is_read_only_and_rejects_missing_siblings(self):
        skills = self.root / 'skills'; skills.mkdir()
        self.assertEqual('missing', frontend.discover(skills)['status'])
        orchestrator = skills / 'omni-artifact-accelerator'; orchestrator.mkdir(); (orchestrator / 'SKILL.md').write_text('test')
        self.assertEqual('unknown', frontend.discover(skills)['status'])
        backend = skills / 'omni-backend-handoff'; backend.mkdir()
        (backend / 'capabilities.json').write_text(json.dumps(dict(schema_version=1,
            continuation_protocol_versions=[1], semantic_handoff_versions=['omni-handoff-v1'])))
        self.assertEqual('incompatible', frontend.discover(skills)['status'])

    def test_real_workflow_records_optional_choice_without_changing_stages(self):
        run = self.h.h.run
        guided.stage_action(run, 'register-domains', document=self.h.candidates)
        state = guided.stage_action(run, 'configure-frontend', document=self.request)
        self.assertEqual(1, len(state['workflow']['frontend_continuations']['items']))
        self.assertEqual('model_semantic', state['answers']['migration_scope'])
        self.assertEqual([], state['workflow']['approvals'])

    def test_offline_page_navigation_and_export_omission(self):
        import delivery_portal as portal
        import portal_checks
        import shutil
        frontend.choose(self.state, self.request)
        page = self.root / 'START_HERE.html'
        portal.render_engagement(self.state, page)
        result = portal.check_page(page, javascript=shutil.which('node') is not None)
        self.assertTrue(result)
        parsed, data = portal_checks.parse_page(page.read_text())
        self.assertIn('dashboard-migration', parsed.nodes)
        self.assertEqual('selected', data['workflow']['frontend_continuation']['items'][0]['status'])
        data['selected_categories'] = ['documentation']
        files = portal.generated_deliverables(data)
        self.assertTrue(any(r['id'] == 'generated:frontend-continuation' for r in files))
        portal._trim_workflow_details(data)
        self.assertNotIn('frontend_continuation', data['workflow'])

    def test_real_zip_includes_only_selected_frontend_summary(self):
        import delivery_portal as portal
        import portal_checks
        import test_delivery_portal as deliveries
        import zipfile
        from run_guided_delivery_demo import synthetic_disclosure
        _, review = deliveries.fixture(self.root)
        review['source_fingerprint'] = portal.source_fingerprint(self.state)
        review['context_sha256'] = portal.context_fingerprint(self.state)
        review['target'] = {k: self.state['answers'][k] for k in ('framework', 'warehouse')}
        review['models'] = [dict(id=e['id'], name=e['name'], layer='gold', grain=e['grain'], columns=[])
                            for e in self.state['workflow']['design']['entities']]
        review['relationships'] = []
        review['design_binding'] = {k: self.state['workflow']['design'][k] for k in ('id', 'revision', 'sha256')}
        review['disclosure'] = synthetic_disclosure(review['artifacts'], 'engineer')
        identity = frontend.choose(self.state, {**self.request, 'dashboard_ids': ['private-dashboard-scope']})
        progress = dict(schema_version=1, continuation_id=identity,
            scope_sha256=frontend.item(self.state, identity)['scope_sha256'], status='returned', reference='synthetic://return')
        with self.assertRaisesRegex(ValueError, 'identifier'):
            frontend.record_progress(self.state, {**progress, 'artifact_ids': [str(self.root)]})
        frontend.record_progress(self.state, {**progress, 'artifact_ids': ['0', '3', 'excluded-private-metadata']})
        for category in ('documentation', 'implementation'):
            output = self.root / (category + '.zip')
            portal.package_delivery(self.state, review, self.root, output, audience='engineer', include=[category])
            with zipfile.ZipFile(output) as archive:
                html = archive.read('START_HERE.html').decode()
                _, payload = portal_checks.parse_page(html)
                self.assertEqual(category == 'documentation',
                                 'frontend_continuation' in payload.get('workflow', {}))
                self.assertEqual(category == 'documentation',
                                 any(p.endswith('DASHBOARD_CONTINUATION.md') for p in archive.namelist()))
                self.assertNotIn(str(self.root), html)
                self.assertNotIn('excluded-private-metadata', html)
                if category == 'documentation':
                    self.assertEqual(['0'], payload['workflow']['frontend_continuation']['items'][0]['artifact_ids'])
                if category == 'implementation':
                    self.assertNotIn('private-dashboard-scope', html)


if __name__ == '__main__': unittest.main()
