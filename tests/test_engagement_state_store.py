"""Synthetic storage scale/integrity tests; no customer input or execution."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_engagement_stages as fixtures
import guided_workflow as guided
import engagement_state_store as store


class EngagementStateStoreTests(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.StageTests('test_design_only_and_forged_approval_never_unlock_code')
        self.h.setUp(); self.addCleanup(self.h.doCleanups)
        self.state, self.run = self.h.state, self.h.run

    def compact(self):
        self.state['workflow']['storage_fixture'] = {'items': ['synthetic-' + str(i) for i in range(8000)]}
        with patch.object(store, 'INLINE_STATE_BYTES', 1024):
            guided._save(self.run, self.state, 'synthetic_storage')
        self.assertTrue(store.is_index(guided._json(self.run / 'state.json')))
        return copy.deepcopy(self.state)

    def objects(self):
        return set((self.run / 'state-store/objects').glob('*.json'))

    def test_inline_legacy_bytes_and_api_are_unchanged(self):
        self.assertEqual(guided._json(self.run / 'state.json'), self.state)
        self.assertEqual(guided.load_engagement(self.run), self.state)
        self.assertFalse((self.run / 'state-store').exists())
        self.assertEqual(store.storage_stats(self.run)['format'], 'inline')
        self.assertEqual(store.load_revision(self.run, self.state['revision']), self.state)

    def test_1250_entities_and_large_observations_resume_without_linked_run(self):
        source_before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.h.repo.iterdir() if p.is_file()}
        doc = copy.deepcopy(self.h.doc); doc['revision'] += 1
        template = doc['entities'][0]
        doc['entities'] = []
        for index in range(1250):
            entity = copy.deepcopy(template)
            entity.update(id='model_%04d' % index, name='model_%04d' % index, depends_on=[], asset_ids=[])
            doc['entities'].append(entity)
        doc['relationships'] = []
        fixtures.stages.import_design(self.state, doc)
        self.state['workflow']['runs'] = [{'task_id': 'build-%04d' % i, 'run_id': 'run-%04d' % i,
            'fingerprint': 'a' * 64, 'outputs': {}, 'assurance': 'host_reported_file_integrity',
            'generation_mode': 'provisional', 'artifact_checks': {'findings': [
                {'model_id': 'model_%04d' % i, 'code': 'synthetic_observation', 'detail': 'x' * 14336}]}}
            for i in range(1250)]
        guided._save(self.run, self.state, 'synthetic_scale')
        before = copy.deepcopy(self.state); first_objects = self.objects()
        stats = store.storage_stats(self.run)
        self.assertGreater(stats['logical_bytes'], guided.MAX_JSON_BYTES)
        self.assertLess(stats['index_bytes'], 256 * 1024)
        self.assertEqual(guided.load_engagement(self.run), before)
        self.assertEqual(store.load_revision(self.run, before['revision']), before)
        guided._save(self.run, self.state, 'unchanged_material')
        self.assertEqual(self.objects(), first_objects)
        resumed = guided.resume_engagement(self.run)
        self.assertEqual(resumed['engagement_id'], before['engagement_id'])
        self.assertEqual(len(resumed['workflow']['design']['entities']), 1250)
        self.assertEqual(resumed['workflow']['runs'], before['workflow']['runs'])
        self.assertFalse(resumed['readiness']['execution_authorized'])
        self.assertEqual(store.load_revision(self.run, before['revision']), before)
        self.assertEqual(source_before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.h.repo.iterdir() if p.is_file()})

    def test_component_tamper_and_missing_file_fail_closed(self):
        self.compact(); path = sorted(self.objects())[0]; original = path.read_bytes()
        path.write_bytes(original.replace(b'synthetic-', b'corrupted-', 1))
        with self.assertRaises((ValueError, OSError)): guided.load_engagement(self.run)
        path.write_bytes(original); self.assertEqual(guided.load_engagement(self.run), self.state)
        path.unlink()
        with self.assertRaises(OSError): guided.load_engagement(self.run)

    def test_component_traversal_symlink_and_index_tamper_fail_closed(self):
        self.compact(); original = guided._json(self.run / 'state.json')
        changed = copy.deepcopy(original); changed['logical_bytes'] += 1
        (self.run / 'state.json').write_bytes(guided._bytes(changed))
        with self.assertRaisesRegex(ValueError, 'index integrity'): guided.load_engagement(self.run)
        changed = copy.deepcopy(original)
        pending = [changed['tree']]
        while pending:
            node = pending.pop()
            if node['type'] == 'blob':
                node['reference']['path'] = '../outside.json'; break
            if node['type'] in ('dict', 'list'): pending.extend(p['node'] for p in node['parts'])
        changed['index_sha256'] = guided._digest({k: v for k, v in changed.items() if k != 'index_sha256'})
        (self.run / 'state.json').write_bytes(guided._bytes(changed))
        with self.assertRaisesRegex(ValueError, 'path must match'): guided.load_engagement(self.run)
        (self.run / 'state.json').write_bytes(guided._bytes(original))
        path = sorted(self.objects())[0]; outside = self.h.root / 'outside.json'
        outside.write_bytes(path.read_bytes()); path.unlink(); path.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'Symlink'): guided.load_engagement(self.run)

    def test_interrupted_compact_save_keeps_previous_head_and_recovers_initial_index(self):
        previous = self.compact(); head = (self.run / 'state.json').read_bytes()
        real_replace = guided.os.replace
        def interrupt(src, dst):
            if Path(dst).name == 'state.json': raise OSError('synthetic head interruption')
            return real_replace(src, dst)
        changed = copy.deepcopy(previous); changed['answers']['priority_domain'] = 'Uncommitted scope'
        with patch.object(store, 'INLINE_STATE_BYTES', 1024), patch.object(guided.os, 'replace', side_effect=interrupt):
            with self.assertRaisesRegex(OSError, 'head interruption'):
                guided._save(self.run, changed, 'interrupted')
        self.assertEqual((self.run / 'state.json').read_bytes(), head)
        self.assertEqual(guided.load_engagement(self.run), previous)
        with patch.object(store, 'INLINE_STATE_BYTES', 1024): resumed = guided.resume_engagement(self.run)
        self.assertEqual(resumed['answers']['priority_domain'], previous['answers']['priority_domain'])
        self.assertGreater(resumed['revision'], changed['revision'])
        fresh = self.h.root / 'interrupted-initial'; fresh.mkdir()
        initial = copy.deepcopy(previous); initial['revision'] = 0
        with patch.object(store, 'INLINE_STATE_BYTES', 1024), patch.object(guided.os, 'replace', side_effect=interrupt):
            with self.assertRaises(OSError): guided._save(fresh, initial, 'initial')
        self.assertFalse((fresh / 'state.json').exists())
        with patch.object(store, 'INLINE_STATE_BYTES', 1024): recovered = guided.resume_engagement(fresh)
        self.assertEqual(recovered['history'][-1]['action'], 'resumed_after_interrupted_start')
        self.assertTrue(store.is_index(guided._json(fresh / 'state.json')))
        self.assertEqual(guided.load_engagement(fresh), recovered)

    def test_bounds_reject_without_replacing_head_or_truncating(self):
        before = (self.run / 'state.json').read_bytes()
        with patch.object(store, 'MAX_LOGICAL_BYTES', 100):
            with self.assertRaisesRegex(ValueError, 'logical size'):
                guided._save(self.run, copy.deepcopy(self.state), 'too_large')
        self.assertEqual((self.run / 'state.json').read_bytes(), before)
        self.assertEqual(guided.load_engagement(self.run), self.state)
        with patch.object(store, 'MAX_DEPTH', 2):
            with self.assertRaisesRegex(ValueError, 'logical structure'):
                guided._save(self.run, copy.deepcopy(self.state), 'too_deep')
        self.assertEqual((self.run / 'state.json').read_bytes(), before)

    def test_deduplicated_components_hydrate_independently_and_keep_review_freshness(self):
        if getattr(self.h, 'key', None) is not None:
            self.h.approve(['orders']); self.state = self.h.state
        value = {'items': ['synthetic-' + str(i) for i in range(8000)],
                 'user_marker': {'type': 'blob', 'reference': 'ordinary user data'}}
        self.state['workflow']['left'] = copy.deepcopy(value)
        self.state['workflow']['right'] = copy.deepcopy(value)
        approval = copy.deepcopy(self.state['workflow']['approvals'])
        with patch.object(store, 'INLINE_STATE_BYTES', 1024): guided._save(self.run, self.state, 'deduplicated')
        stats = store.storage_stats(self.run)
        self.assertGreater(stats['component_references'], stats['unique_components'])
        loaded = guided.load_engagement(self.run)
        loaded['workflow']['left']['items'][0] = 'changed in memory'
        self.assertEqual(loaded['workflow']['right'], value)
        self.assertEqual(loaded['workflow']['approvals'], approval)
        self.assertEqual(fixtures.stages.approved_entities(loaded), fixtures.stages.approved_entities(self.state))
        (self.h.repo / 'orders.sql').write_text('select 999 as orders_id')
        self.assertNotIn('orders', fixtures.stages.approved_entities(guided.load_engagement(self.run)))

    def test_repeated_reference_cannot_understate_expansion_size(self):
        self.compact(); index = guided._json(self.run / 'state.json')
        pending = [index['tree']]
        while pending:
            node = pending.pop()
            if node['type'] == 'blob': break
            if node['type'] in ('dict', 'list'): pending.extend(p['node'] for p in node['parts'])
        repeated = copy.deepcopy(node); repeated['reference']['bytes'] = 1
        index['tree']['parts'] += [
            {'type': 'item', 'key': 'first_reference', 'node': copy.deepcopy(node)},
            {'type': 'item', 'key': 'false_size', 'node': repeated}]
        index['index_sha256'] = guided._digest({k: v for k, v in index.items() if k != 'index_sha256'})
        with self.assertRaisesRegex(ValueError, 'Repeated engagement component size'):
            store.hydrate(self.run, index)

    def test_long_unicode_observation_is_chunked_losslessly(self):
        text = '\u2603\U0001f310\n' * 150000
        self.state['workflow']['long_observation'] = text
        with patch.object(store, 'INLINE_STATE_BYTES', 1024):
            guided._save(self.run, self.state, 'large_unicode_observation')
        self.assertEqual(guided.load_engagement(self.run)['workflow']['long_observation'], text)
        self.assertTrue(all(path.stat().st_size <= store.MAX_COMPONENT_BYTES for path in self.objects()))


if __name__ == '__main__': unittest.main()
