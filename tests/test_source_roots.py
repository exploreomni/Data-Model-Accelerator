"""Synthetic named repositories, exact input hashes and unchanged legacy scope."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import engagement_stages as stages
import guided_workflow as guided
import run_control
import source_roots as roots
import test_engagement_stages as fixtures


class SourceRootTests(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.StageTests('test_design_only_and_forged_approval_never_unlock_code')
        self.h.setUp(); self.addCleanup(self.h.doCleanups)
        self.state = self.h.state
        self.other = self.h.root / 'legacy-repository'; self.other.mkdir()
        self.file = self.other / 'orders.sql'; self.file.write_text('select 42 as orders_id')
        self.request = {'schema_version': 1, 'roots': [{'id': 'legacy', 'path': str(self.other),
                        'revision': 'revision-1', 'dirty': 'unknown'}]}

    def register(self):
        roots.register(self.state, self.request, self.h.run)

    def test_cli_adds_roots_without_restart_or_invalidating_unrelated_review(self):
        review = {'schema_version': 1, 'kind': 'human_design_review', 'decision': 'approve',
                  'reviewer': 'Synthetic reviewer', 'review_reference': 'synthetic://review',
                  'bindings': stages.review_bindings(self.state, ['products'])}
        self.state = guided.stage_action(self.h.run, 'approve-design', entities=['products'], document=review)
        before = stages.entity_bindings(self.state, ['products'])
        source_bytes = {p: p.read_bytes() for root in (self.h.repo, self.other) for p in root.iterdir()}
        document = self.h.root / 'roots.json'; document.write_text(json.dumps(self.request))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(guided.main(['register-source-roots', '--run', str(self.h.run),
                '--document', str(document), '--no-render']), 0)
        self.state = guided.resume_engagement(self.h.run)
        self.assertEqual(self.state['engagement_id'], self.h.state['engagement_id'])
        self.assertEqual(self.state['inputs']['source']['path'], str(self.h.repo))
        self.assertEqual(stages.entity_bindings(self.state, ['products']), before)
        self.assertIn('products', stages.approved_entities(self.state))
        public = roots.public_summary(self.state)
        self.assertEqual((public['count'], public['registry_revision']), (2, 1))
        self.assertTrue(all(row['coverage_complete'] for row in public['roots']))
        self.assertNotIn(str(self.h.root), json.dumps(public))
        self.assertEqual(source_bytes, {p: p.read_bytes() for p in source_bytes})

    def test_same_relative_name_resolves_exactly_and_scoped_changes_stale_only_dependents(self):
        self.register()
        doc = copy.deepcopy(self.state['workflow']['design']); doc.pop('sha256'); doc['revision'] += 1
        next(e for e in doc['entities'] if e['id'] == 'orders')['source_paths'] = ['@sources/legacy/orders.sql']
        stages.import_design(self.state, doc)
        self.assertEqual(roots.resolve(self.state, 'orders.sql'), self.h.repo / 'orders.sql')
        self.assertEqual(roots.resolve(self.state, '@sources/legacy/orders.sql'), self.file)
        self.assertEqual(stages._source_hash(self.state, '@sources/legacy/orders.sql'), hashlib.sha256(self.file.read_bytes()).hexdigest())
        before = stages.entity_bindings(self.state, ['orders', 'products'])
        self.file.write_text('select 43 as orders_id')
        after = stages.entity_bindings(self.state, ['orders', 'products'])
        self.assertNotEqual(before['orders'], after['orders'])
        self.assertEqual(before['products'], after['products'])
        revision = copy.deepcopy(self.request); revision['roots'][0]['revision'] = 'revision-2'
        roots.register(self.state, revision, self.h.run)
        changed = stages.entity_bindings(self.state, ['orders', 'products'])
        self.assertNotEqual(changed['orders'], after['orders'])
        self.assertEqual(changed['products'], after['products'])

    def test_registration_is_additive_idempotent_and_rebinding_rejected_atomically(self):
        self.register(); first = copy.deepcopy(self.state)
        self.register(); self.assertEqual(self.state, first)
        another = self.h.root / 'another'; another.mkdir()
        for bad in ({'schema_version': 1, 'roots': [{'id': 'legacy', 'path': str(another)}]},
                    {'schema_version': 1, 'roots': self.request['roots'] * 2},
                    {'schema_version': 1, 'roots': [{'id': 'duplicate', 'path': str(self.other)}]},
                    {'schema_version': 1, 'roots': [{'id': 'inside', 'path': str(self.h.repo)}]}):
            with self.assertRaises(ValueError): roots.register(self.state, bad, self.h.run)
            self.assertEqual(self.state, first)
        roots.register(self.state, {'schema_version': 1, 'roots': [{'id': 'third', 'path': str(another)}]}, self.h.run)
        self.assertEqual([r['id'] for r in self.state['inputs']['source']['roots']], ['legacy', 'third'])

    def test_secret_unknown_traversal_and_symlink_paths_are_not_resolved(self):
        self.register()
        (self.other / 'redirect.sql').symlink_to(self.h.repo / 'products.sql')
        for reference in ('@sources/missing/orders.sql', '@sources/legacy/../orders.sql',
                          '@sources/legacy/.env', '@sources/legacy/key.pem', '@sources/legacy/redirect.sql'):
            with self.subTest(reference=reference), self.assertRaises(ValueError): roots.resolve(self.state, reference)
        link = self.h.root / 'linked'; link.symlink_to(self.other, target_is_directory=True)
        with self.assertRaises(ValueError):
            roots.register(self.state, {'schema_version': 1, 'roots': [{'id': 'linked', 'path': str(link)}]}, self.h.run)

    def test_all_output_boundaries_reject_every_registered_source(self):
        self.register()
        for output in (self.other, self.other / 'nested', self.h.root):
            with self.assertRaises(ValueError): roots.ensure_output(self.state, output)
        self.assertEqual(roots.ensure_output(self.state, self.h.artifacts), self.h.artifacts)
        state = copy.deepcopy(self.h.state)
        state['workflow']['artifact_root'] = str(self.h.artifacts)
        with self.assertRaises(ValueError):
            roots.register(state, {'schema_version': 1, 'roots': [{'id': 'candidate', 'path': str(self.h.artifacts)}]}, self.h.run)

    def test_direct_and_guided_task_outputs_cannot_use_either_repository(self):
        self.state = guided.stage_action(self.h.run, 'register-source-roots', document=self.request)
        before_state = (self.h.run / 'state.json').read_bytes()
        before_files = {p: p.read_bytes() for root in (self.h.repo, self.other) for p in root.iterdir()}
        stages.register_tasks(self.state, self.h.tasks())
        for root in (self.h.repo, self.other):
            with self.subTest(root=root.name):
                with self.assertRaisesRegex(ValueError, 'every registered read-only source'):
                    stages.plan_tasks(self.state, root)
                with self.assertRaisesRegex(ValueError, 'every registered read-only source'):
                    guided.stage_action(self.h.run, 'plan-tasks', document=self.h.tasks(), artifact_root=root)
        self.assertEqual((self.h.run / 'state.json').read_bytes(), before_state)
        self.assertEqual({p: p.read_bytes() for p in before_files}, before_files)
        self.assertEqual(set(p for root in (self.h.repo, self.other) for p in root.iterdir()), set(before_files))

    def test_adding_root_preserves_primary_packet_limits_and_secondary_blockers(self):
        primary = self.h.repo / 'large.sql'; primary.write_text('x' * 1024)
        before = roots.capture(self.state, ['large.sql'])
        self.register()
        with patch('source_adapters.base.MAX_FILE_BYTES', 128), patch('source_adapters.filesystem.MAX_FILE_BYTES', 128):
            self.assertEqual(roots.capture(self.state, ['large.sql']), before)
        original = guided._assess_repository
        def assess(repo, framework, warehouse, **options):
            result = original(repo, framework, warehouse, **options)
            if Path(repo) == self.other:
                result['findings'].append({'id': 'unsupported_generation', 'severity': 'blocker',
                    'blocks': ['generation'], 'summary': 'Synthetic unsupported source contract',
                    'next_action': 'Review the source contract', 'paths': ['orders.sql']})
            return result
        with patch.object(guided, '_assess_repository', side_effect=assess):
            guided._refresh(self.state)
        self.assertFalse(self.state['readiness']['generation_ready'])
        finding = next(f for f in self.state['readiness']['platform']['findings'] if f['id'] == 'source.legacy.unsupported_generation')
        self.assertEqual(finding['paths'], ['@sources/legacy/orders.sql'])

    def test_legacy_virtual_looking_paths_remain_legacy_and_collision_is_explicit(self):
        folder = self.h.repo / '@sources' / 'legacy'; folder.mkdir(parents=True)
        path = folder / 'orders.sql'; path.write_text('legacy literal directory')
        self.assertIsNone(roots.public_summary(self.state))
        self.assertEqual(roots.resolve(self.state, '@sources/legacy/orders.sql'), path)
        with self.assertRaisesRegex(ValueError, 'collides'): self.register()
        self.assertNotIn('roots', self.state['inputs']['source'])

    def test_missing_root_and_bounded_coverage_remain_visible_without_false_readiness(self):
        self.state = guided.stage_action(self.h.run, 'register-source-roots', document=self.request)
        moved = self.other.with_name('held'); self.other.rename(moved)
        self.state = guided.resume_engagement(self.h.run)
        row = next(r for r in roots.public_summary(self.state)['roots'] if r['id'] == 'legacy')
        self.assertFalse(row['coverage_complete']); self.assertIsNone(row['fingerprint'])
        self.assertFalse(self.state['readiness']['generation_ready'])
        self.assertFalse(self.state['readiness']['execution_authorized'])

    def test_named_dispatch_reuse_follows_actual_bytes_and_protects_checkpoint_outputs(self):
        self.register()
        request = {'schema_version': 1, 'work_id': 'extract-legacy', 'attempt_id': 'one',
                   'role': 'source_specialist', 'scope_ids': ['legacy'],
                   'source_paths': ['@sources/legacy/orders.sql']}
        self.assertEqual(run_control.claim_work(self.state, request)['action'], 'dispatch')
        checkpoint = {'schema_version': 1, 'attempt_id': 'one', 'status': 'outputs_recorded',
                      'reason': 'Synthetic extraction', 'outputs': ['extracted.json']}
        with self.assertRaises(ValueError): run_control.checkpoint_work(self.state, checkpoint, self.other)
        (self.h.artifacts / 'extracted.json').write_text('{}')
        run_control.checkpoint_work(self.state, checkpoint, self.h.artifacts)
        self.assertEqual(run_control.claim_work(self.state, {**request, 'attempt_id': 'two'})['action'], 'reuse')
        self.file.write_text('select 44 as orders_id')
        self.assertEqual(run_control.claim_work(self.state, {**request, 'attempt_id': 'three'})['action'], 'dispatch')


if __name__ == '__main__': unittest.main()
