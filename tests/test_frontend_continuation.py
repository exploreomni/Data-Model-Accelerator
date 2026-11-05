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

    def test_v2_surfaces_and_task_mode_survive_preparation_and_stable_retry(self):
        req = dict(self.request, schema_version=2, target_surfaces=['app'], task_mode='net-new',
                   dashboard_ids=[], app_ids=['entry'], topic_names=['orders'],
                   destination={'base_url':'https://example.invalid','model_id':'model-1','branch_id':'branch-1',
                                'model_version_id':'revision-1'})
        identity = frontend.choose(self.state, req)
        self.assertEqual(identity, frontend.choose(self.state, req))
        output = self.root / 'v2-app'
        first = frontend.prepare(self.state, identity, self.inputs, output, 'synthetic://disclosure')
        packet = json.loads((output / 'continuation.json').read_bytes())
        self.assertEqual(frontend.prepare(self.state, identity, self.inputs, output, 'synthetic://disclosure'), first)
        for k in ('target_surfaces','task_mode','topic_names','destination','app_ids'):
            self.assertEqual(packet[k], req[k])
        self.assertIsNone(packet['semantic_review'])
        self.assertFalse(packet['authorizes_target_write'])
        self.assertFalse(any('dashboard inventory' in line.lower() for line in packet['unresolved']))
        self.assertNotEqual(identity, frontend.choose(self.state, dict(req, target_surfaces=['app','dashboard'])))
        self.assertNotEqual(identity, frontend.choose(self.state, dict(req, task_mode='enhancement')))
        self.state['answers']['migration_scope'] = 'full_dashboard'
        independent = frontend.choose(self.state, dict(req, app_ids=['separate-app']))
        self.assertEqual(frontend.item(self.state, independent)['mode'], 'independent')

    def test_v2_evidence_selection_requires_exact_unchanged_bytes(self):
        readback = self.inputs / 'readback.json'
        readback.write_text('{"example":"original"}')
        row = {'path':'readback.json','purpose':'topic_readback','sha256':hashlib.sha256(readback.read_bytes()).hexdigest()}
        request = dict(self.request, schema_version=2, target_surfaces=['app','dashboard'], task_mode='migration',
                       context_files=[row])
        identity = frontend.choose(self.state, request)
        output = self.root / 'v2-bound'
        frontend.prepare(self.state, identity, self.inputs, output, 'synthetic://disclosure')
        packet = json.loads((output / 'continuation.json').read_bytes())
        self.assertEqual(packet['topic_readback']['sha256'], row['sha256'])
        self.assertEqual(packet['target_surfaces'], ['dashboard','app'])
        self.assertIsNone(packet['native_validation'])
        readback.write_text('{"example":"changed"}')
        with self.assertRaisesRegex(ValueError, 'evidence bytes changed'):
            frontend.prepare(self.state, identity, self.inputs, self.root / 'changed', 'synthetic://disclosure')
        with self.assertRaisesRegex(ValueError, 'Pin the selected'):
            frontend.choose(self.state, dict(request, context_files=[{'path':'readback.json','purpose':'topic_readback'}]))

    def test_v2_delivery_shows_task_and_original_app_ids(self):
        import base64
        import delivery_portal as portal
        import portal_checks
        import shutil
        request = dict(self.request, schema_version=2, target_surfaces=['app'], task_mode='enhancement',
                       dashboard_ids=[], app_ids=['source-app'])
        frontend.choose(self.state, request)
        page = self.root / 'START_HERE.html'
        portal.render_engagement(self.state, page)
        self.assertTrue(portal.check_page(page, javascript=shutil.which('node') is not None))
        _, data = portal_checks.parse_page(page.read_text())
        data['selected_categories'] = ['documentation']
        file = next(r for r in portal.generated_deliverables(data) if r['id'] == 'generated:frontend-continuation')
        summary = base64.b64decode(file['base64']).decode()
        self.assertIn('Target surfaces: app', summary)
        self.assertIn('Task mode: enhancement', summary)
        self.assertIn('Source Apps: source-app', summary)

    def test_mixed_version_fallback_retains_app_without_dashboard_downgrade(self):
        skills = self.root / 'skills'
        for name in set(frontend.COMMON_SKILLS) | {'omni-dashboard-designer','omni-app-engineer',
                                                    'omni-product-owner','omni-design-systems'}:
            path = skills / name; path.mkdir(parents=True); (path / 'SKILL.md').write_text('synthetic')
        for file in ('omni-artifact-accelerator/scripts/analyst_project.py',
                     'omni-backend-handoff/scripts/dma_frontend.py', 'omni-backend-handoff/scripts/migration.py',
                     'omni-backend-handoff/scripts/cowork.py','omni-backend-handoff/scripts/continuation.py'):
            path = skills / file; path.parent.mkdir(exist_ok=True); path.write_text('raise AssertionError("discovery executed code")')
        descriptor = {'schema_version':1,'kind':'omni_frontend_capabilities','continuation_protocol_versions':[1],
                      'semantic_handoff_versions':['omni-handoff-v1'],'entrypoint':'scripts/continuation.py',
                      'authorizes_target_write':False}
        caps = skills / 'omni-backend-handoff/capabilities.json'; caps.write_text(json.dumps(descriptor))
        self.assertEqual(frontend.discover(skills)['protocol_version'], 1)
        req = dict(self.request, schema_version=2, target_surfaces=['app'], task_mode='net-new', dashboard_ids=[])
        identity = frontend.choose(self.state, req)
        output = self.root / 'portable'
        prepared = frontend.prepare(self.state, identity, self.inputs, output, 'synthetic://disclosure', skills_root=skills)
        self.assertEqual(prepared['route'], 'portable_handoff')
        self.assertEqual(json.loads((output/'continuation.json').read_bytes())['target_surfaces'], ['app'])
        descriptor.update(continuation_protocol_versions=[1,2], target_surfaces=['dashboard','app'],
                          task_modes=['net-new','migration','enhancement'])
        caps.write_text(json.dumps(descriptor))
        app = skills / 'omni-app-designer'
        self.assertIn(app.name, frontend.discover(skills, target_surfaces=['app'])['missing_skills'])
        app.mkdir(); (app/'SKILL.md').write_text('synthetic')
        (skills/'omni-dashboard-designer/SKILL.md').unlink()
        self.assertEqual(frontend.discover(skills, target_surfaces=['app'])['protocol_version'], 2)
        self.assertEqual(frontend.discover(skills, target_surfaces=['app','dashboard'])['status'], 'incompatible')

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
