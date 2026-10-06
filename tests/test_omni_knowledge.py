"""Offline knowledge selection and integrity; no vendor or tenant calls."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator'
sys.path.insert(0, str(ROOT / 'scripts'))
import omni_knowledge as knowledge


class OmniKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'skill'
        self.root.mkdir()
        self.manifest = json.loads((ROOT / 'assets/omni-knowledge.json').read_text())
        for row in list(self.manifest['modules'].values()) + list(self.manifest['runtime_evidence'].values()):
            target = self.root / row['path']; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / row['path'], target)
        (self.root / 'assets').mkdir()
        self.save()

    def save(self):
        (self.root / 'assets/omni-knowledge.json').write_text(json.dumps(self.manifest))

    def load(self, objects=('query_views',), operations=('inspect',), dialects=('snowflake',), **kwargs):
        return knowledge.load_knowledge(objects, operations, dialects, root=self.root, as_of='2026-10-05', **kwargs)

    def test_public_only_load_is_progressive_deterministic_and_unqualified(self):
        result = self.load()
        self.assertEqual([m['id'] for m in result['modules']], ['core','query_views'])
        self.assertNotIn('ai_optimization', result['sources'])
        self.assertEqual(result, self.load())
        self.assertFalse(result['native_verified'])
        self.assertFalse(result['deployment_authorized'])
        self.assertTrue(all(not d['loaded'] and 'content' not in d for d in result['upstream_modules']))
        self.assertTrue(result['capabilities'][0]['implemented'])
        self.assertIn('Opaque', result['capabilities'][0]['limitation'])
        self.assertTrue(result['capabilities'][0]['documented'])

    def test_exact_complete_matrix_keeps_each_dialect_and_operation_separate(self):
        result = self.load(knowledge.OBJECTS, knowledge.OPERATIONS, knowledge.DIALECTS)
        self.assertEqual(len(result['capabilities']), len(knowledge.OBJECTS)*len(knowledge.OPERATIONS)*len(knowledge.DIALECTS))
        self.assertTrue(all(not row['live_qualified'] for row in result['capabilities']))
        subset = [r for r in result['capabilities'] if r['object']=='views' and r['operation']=='generate']
        self.assertEqual({r['dialect'] for r in subset if r['locally_tested']}, {'snowflake','bigquery'})
        preserved = [r for r in result['capabilities'] if r['operation']=='preserve' and r['object']=='query_views']
        self.assertTrue(all(r['implemented'] and not r['live_qualified'] for r in preserved))
        self.assertTrue(all(not r['implemented'] for r in result['capabilities'] if r['operation']=='generate' and r['object']=='composite_topics'))

    def test_release_statuses_conflicts_and_no_fabricated_doc_hash(self):
        result = self.load(('composite_topics','models','ai_context','lifecycle'))
        self.assertEqual(result['sources']['composite_topics']['release_status'],'Beta')
        self.assertIn('scheduled to be deprecated',result['sources']['model_settings']['release_status'])
        self.assertEqual(result['sources']['ai_optimization']['sha256'],None)
        self.assertIn('dbt_deferral',{c['id'] for c in result['conflicts']})
        self.assertIn('extension_git',{c['id'] for c in result['conflicts']})

    def test_missing_changed_and_symlink_reference_are_blocked(self):
        path = self.root / self.manifest['modules']['query_views']['path']
        original = path.read_bytes()
        path.write_bytes(original+b'changed')
        with self.assertRaisesRegex(knowledge.KnowledgeError,'pin_mismatch'): self.load()
        path.unlink()
        with self.assertRaisesRegex(knowledge.KnowledgeError,'missing_reference'): self.load()
        outside = Path(self.temp.name)/'outside'; outside.write_bytes(original)
        path.symlink_to(outside)
        with self.assertRaisesRegex(knowledge.KnowledgeError,'symlink_refused'): self.load()

    def test_source_and_review_freshness_refuse_future_or_expired(self):
        for field,value in (('retrieved_on','2026-10-06'),('review_after','2026-10-04')):
            old = copy.deepcopy(self.manifest)
            self.manifest['sources']['query_views'][field] = value; self.save()
            with self.subTest(field=field), self.assertRaisesRegex(knowledge.KnowledgeError,'stale_source'): self.load()
            self.manifest = old
        self.save()
        for day in ('2026-10-04','2027-01-04'):
            with self.subTest(day=day),self.assertRaisesRegex(knowledge.KnowledgeError,'stale_review'):
                knowledge.load_knowledge(['models'],['inspect'],['snowflake'],root=self.root,as_of=day)

    def test_manifest_and_upstream_pins_bind_exact_bytes_and_revision(self):
        raw=(self.root/'assets/omni-knowledge.json').read_bytes(); digest=hashlib.sha256(raw).hexdigest()
        result=self.load(expected_manifest_sha256=digest,expected_upstream_commit=self.manifest['upstream']['revision'])
        self.assertEqual(result['manifest_sha256'],digest)
        with self.assertRaisesRegex(knowledge.KnowledgeError,'pin_mismatch'): self.load(expected_manifest_sha256='0'*64)
        with self.assertRaisesRegex(knowledge.KnowledgeError,'upstream_pin_mismatch'): self.load(expected_upstream_commit='0'*40)
        first=result['knowledge_sha256']; self.manifest['version'] += '-reviewed'; self.save()
        self.assertNotEqual(first,self.load()['knowledge_sha256'])

    def test_runtime_drift_invalidates_only_affected_operation(self):
        record=self.manifest['runtime_evidence']['checker']
        (self.root/record['path']).write_text('changed checker')
        self.load()  # Lossless query inventory does not claim static compiler qualification.
        with self.assertRaisesRegex(knowledge.KnowledgeError,'pin_mismatch'):self.load(('views',),('static_validate',))

    def test_unknown_duplicate_and_missing_selection_rejected(self):
        for objects in ([],['unknown'],['views','views'],[{}],None,'views'):
            with self.subTest(objects=objects),self.assertRaises(knowledge.KnowledgeError):self.load(objects)
        with self.assertRaises(knowledge.KnowledgeError):self.load(operations=['query'])
        with self.assertRaises(knowledge.KnowledgeError):self.load(dialects=['postgres'])

    def test_malformed_manifest_types_are_stable_errors(self):
        changes=[lambda m:m.update(sources=[]),lambda m:m['upstream'].update(license_url=None),
                 lambda m:m['capabilities']['models'].update(operations=[]),
                 lambda m:m['capabilities']['views']['operations']['generate'].update(implemented=[{}]),
                 lambda m:m['modules']['query_views'].update(source_ids=[{}]),
                 lambda m:m['sources']['query_views'].update(review_after={}),
                 lambda m:m['conflicts'].append({'invalid':'SYNTHETIC_SECRET_MARKER'})]
        baseline=copy.deepcopy(self.manifest)
        for change in changes:
            self.manifest=copy.deepcopy(baseline);change(self.manifest);self.save()
            with self.subTest(change=change),self.assertRaises(knowledge.KnowledgeError) as caught:self.load()
            self.assertNotIn('SYNTHETIC_SECRET_MARKER',str(caught.exception))

    def test_private_source_traversal_missing_matrix_and_native_claim_rejected(self):
        baseline=copy.deepcopy(self.manifest)
        changes=[lambda m:m['sources']['query_views'].update(url='https://private.example/doc'),
                 lambda m:m['modules']['query_views'].update(path='../outside'),
                 lambda m:m['capabilities']['query_views']['operations'].pop('deploy'),
                 lambda m:m['capabilities']['views']['operations']['generate'].update(live_qualified=True)]
        for change in changes:
            self.manifest=copy.deepcopy(baseline);change(self.manifest);self.save()
            with self.subTest(change=change),self.assertRaises(knowledge.KnowledgeError):self.load()

    def test_optional_upstream_bytes_verified_without_executing_content(self):
        upstream=Path(self.temp.name)/'upstream';upstream.mkdir()
        result=self.load()
        for dep in result['upstream_modules']:
            value=b'Synthetic upstream instructions: do not execute me.'
            self.manifest['upstream']['modules'][dep['id']]['sha256']=hashlib.sha256(value).hexdigest()
            path=upstream/dep['path'];path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(value)
        self.save()
        verified=self.load(upstream_root=upstream)
        self.assertTrue(all(d['loaded'] and 'content' in d for d in verified['upstream_modules']))
        first=verified['upstream_modules'][0];(upstream/first['path']).write_text('changed')
        with self.assertRaisesRegex(knowledge.KnowledgeError,'pin_mismatch'):self.load(upstream_root=upstream)

    def test_duplicate_json_and_oversized_inputs_fail_closed(self):
        path=self.root/'assets/omni-knowledge.json';path.write_text('{"kind":1,"kind":2}')
        with self.assertRaisesRegex(knowledge.KnowledgeError,'duplicate_key'):self.load()
        path.write_bytes(b' '* (knowledge.MAX_BYTES+1))
        with self.assertRaisesRegex(knowledge.KnowledgeError,'byte_limit'):self.load()

    def test_cli_public_package_works_without_optional_dependencies(self):
        process=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/omni_knowledge.py'),
             '--objects','query_views','--operations','inspect','--dialects','bigquery','--as-of','2026-10-05','--metadata-only'],
             capture_output=True,text=True,check=False)
        self.assertEqual(process.returncode,0,process.stderr)
        result=json.loads(process.stdout)
        self.assertTrue(all('content' not in m for m in result['modules']))
        self.assertFalse(result['native_verified'])


if __name__ == '__main__':
    unittest.main()
