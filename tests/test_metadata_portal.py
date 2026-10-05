"""Synthetic portable metadata review; no native or customer acceptance claims."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
import zipfile

from test_delivery_portal import fixture, portal
from test_metadata_contract import dictionary, configuration, build_contract
from test_warehouse_metadata_plan import observation, plan_metadata, tagged_contract
from ae_common import hash_json
from metadata_observation import seal


class MetadataPortalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.state, self.review = fixture(self.root)

    def register(self, plan=None, *, category='documentation', audiences=None, body=None):
        if plan is None:
            contract = build_contract(dictionary(), configuration())
            plan = plan_metadata(contract, observation(contract))
        body = json.dumps(plan).encode() if body is None else body
        path = self.root / 'metadata-plan.json'
        path.write_bytes(body)
        artifact = {'id': 'metadata-plan', 'path': path.name, 'category': category,
                    'audiences': audiences or ['reviewer', 'engineer'], 'sha256': hashlib.sha256(body).hexdigest()}
        self.review['artifacts'] = [a for a in self.review['artifacts'] if a['id'] != artifact['id']] + [artifact]
        self.review['metadata'] = {'plan_artifact_id': artifact['id'], 'sha256': artifact['sha256']}
        return plan

    def package(self, **kwargs):
        path = self.root / ('delivery-' + str(len(list(self.root.glob('*.zip')))) + '.zip')
        portal.package_delivery(self.state, self.review, self.root, path, **kwargs)
        return path

    def payload(self, path):
        with zipfile.ZipFile(path) as archive:
            page = archive.read('START_HERE.html').decode()
        return json.loads(re.search(r'<script id="delivery-data" type="application/json">(.*?)</script>', page, re.S).group(1))

    def rewrite(self, path, mutate_data=None, mutate_entries=None, mutate_manifest=None):
        with zipfile.ZipFile(path) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        manifest = json.loads(entries.pop('DELIVERY_MANIFEST.json'))
        if mutate_data:
            page = entries['START_HERE.html'].decode()
            data = self.payload(path)
            mutate_data(data)
            encoded = json.dumps(data).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
            page = re.sub(r'(<script id="delivery-data" type="application/json">).*?(</script>)',
                          lambda m: m.group(1) + encoded + m.group(2), page, flags=re.S)
            entries['START_HERE.html'] = page.encode()
        if mutate_entries:
            mutate_entries(entries)
        manifest['files'] = [{'path': name, 'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body)}
                             for name, body in sorted(entries.items())]
        if mutate_manifest:
            mutate_manifest(manifest)
        entries['DELIVERY_MANIFEST.json'] = json.dumps(manifest).encode()
        result = self.root / ('rewritten-' + str(len(list(self.root.glob('*.zip')))) + '.zip')
        with zipfile.ZipFile(result, 'w') as archive:
            for name, body in entries.items():
                archive.writestr(name, body)
        return result

    def test_selected_plan_derives_scope_and_changes_from_exact_bytes(self):
        plan = self.register()
        path = self.package()
        value = self.payload(path)['review']['metadata']
        self.assertEqual(value['evidence_state'], 'selected')
        self.assertEqual(value['status'], 'ready')
        self.assertEqual(value['target'], {'framework': 'dbt', 'warehouse': 'snowflake', 'environment': 'development'})
        self.assertEqual(value['counts']['resources_required'], 1)
        self.assertEqual(value['counts']['columns_required'], 1)
        self.assertEqual(value['counts']['observed_columns'], 1)
        self.assertEqual(value['counts']['unknown_sensitivity_columns'], 0)
        self.assertEqual(value['changes'][0]['before'], None)
        self.assertEqual(value['changes'][0]['after'], plan['operations'][0]['after'])
        self.assertEqual(value['sequence'], plan['phases'])
        self.assertTrue(value['privilege_requirements'])
        self.assertNotIn('contract', value)
        self.assertNotIn('identity', value['target'])
        self.assertNotIn('sql', value['changes'][0])
        self.assertNotIn('migration', json.dumps(value))
        self.assertEqual(portal.verify_delivery(path)['status'], 'integrity_verified')

    def test_baseline_extra_column_denominator_and_blocker_are_not_hidden(self):
        contract = build_contract(dictionary(), configuration())
        before = observation(contract)
        before['resources'][0]['columns'].append({'name': 'not_documented', 'data_type': 'VARCHAR', 'comment': None, 'tags': []})
        self.register(plan_metadata(contract, seal(before)))
        value = self.payload(self.package())['review']['metadata']
        self.assertEqual(value['counts']['columns_required'], 1)
        self.assertEqual(value['counts']['observed_columns'], 2)
        self.assertEqual(value['status'], 'blocked')
        self.assertTrue(any('undocumented' in issue for issue in value['blockers']))

    def test_raw_and_excluded_resources_retain_scope_decisions(self):
        value, config = dictionary(), configuration()
        source = copy.deepcopy(value['models'][0])
        source['source_id'] = 'source.raw.customer'
        del source['model_id']
        source['columns'][0]['column_id'] = 'raw-customer-id'
        source['columns'][0]['source_refs'] = [{'object_id': source['source_id'], 'column_path': ['customer_id'],
                                               'catalogue_sha256': config['catalogue_sha256']}]
        value.update(sources=[source], source_inventory_sha256='d'*64)
        raw = copy.deepcopy(config['resources'][0])
        raw.update(resource_id=source['source_id'], resource_type='source', layer='raw',
                   source_write_decision='Synthetic explicit source-owner scope')
        raw['relation']['namespace'][-1] = 'raw'
        config['resources'].append(raw)
        config['metadata_policy'].update(raw_comments=True, source_ids=[source['source_id']])
        config['resources'][0].update(disposition='documented_only', reason='Target writes excluded in this synthetic scope')
        contract = build_contract(value, config)
        self.register(plan_metadata(contract, observation(contract)))
        data = self.payload(self.package())['review']['metadata']
        self.assertEqual(data['counts']['resources_selected'], 2)
        self.assertEqual(data['counts']['resources_required'], 1)
        self.assertEqual(data['counts']['source_resources'], 1)
        self.assertEqual(data['scope'][0]['reason'], config['resources'][0]['reason'])
        self.assertEqual(data['scope'][1]['source_write_decision'], raw['source_write_decision'])
        self.assertTrue(all(row['phase'] == 'source_metadata' for row in data['changes']))

    def test_missing_governance_is_a_visible_request_not_a_grant(self):
        contract = tagged_contract()
        self.register(plan_metadata(contract, observation(contract)))
        value = self.payload(self.package())['review']['metadata']
        self.assertEqual(value['status'], 'blocked')
        self.assertTrue(value['governance_requests'])
        self.assertEqual(value['governance_requests'][0]['requested_value'], 'RESTRICTED')

    def test_no_op_is_not_a_pass_or_execution_claim(self):
        contract = build_contract(dictionary(), configuration())
        self.register(plan_metadata(contract, observation(contract, expected=True)))
        value = self.payload(self.package())['review']['metadata']
        self.assertEqual(value['status'], 'no_op')
        self.assertEqual(value['counts']['native_statements'], 0)
        self.assertEqual(value['counts']['unchanged_assignments'], 2)
        self.assertIn('does not authenticate', value['observation']['qualification'])

    def test_omitted_category_and_audience_keep_an_unknown_view(self):
        for category, audiences, include in [('validation', None, ['documentation']),
                                              ('documentation', ['engineer'], ['documentation']),
                                              ('technical_audit', ['audit'], ['documentation'])]:
            with self.subTest(category=category, audiences=audiences):
                self.register(category=category, audiences=audiences)
                path = self.package(include=include)
                value = self.payload(path)['review']['metadata']
                self.assertEqual(value, portal._metadata_omitted(self.review['metadata']))
                self.assertNotIn('counts', value)
                self.assertEqual(portal.verify_delivery(path)['status'], 'integrity_verified')

    def test_local_render_has_no_metadata_evidence_claim(self):
        self.register()
        path = self.root / 'local.html'
        portal.render_engagement(self.state, path, self.review)
        page = path.read_text()
        data = json.loads(re.search(r'<script id="delivery-data" type="application/json">(.*?)</script>', page, re.S).group(1))
        self.assertEqual(data['review']['metadata']['evidence_state'], 'not_included')

    def test_reference_cannot_supply_its_own_summary_or_stale_hash(self):
        self.register()
        original = copy.deepcopy(self.review['metadata'])
        for ref in [dict(original, status='pass'), dict(original, sha256='0'*64),
                    dict(original, plan_artifact_id='missing'), None]:
            with self.subTest(ref=ref):
                self.review['metadata'] = ref
                with self.assertRaisesRegex(ValueError, 'Metadata'):
                    self.package()

    def test_modified_registry_artifact_and_resealed_fake_plan_are_rejected(self):
        self.register()
        (self.root / 'metadata-plan.json').write_text('{}')
        with self.assertRaises(ValueError):
            self.package()
        plan = self.register()
        plan['counts']['native_statements'] = 0
        plan['plan_sha256'] = hash_json({k: v for k, v in plan.items() if k != 'plan_sha256'})
        self.register(plan)
        with self.assertRaisesRegex(ValueError, 'canonical projection'):
            self.package()

    def test_other_target_and_non_plan_json_are_rejected(self):
        contract = build_contract(dictionary(), configuration('bigquery'))
        self.register(plan_metadata(contract, observation(contract)))
        with self.assertRaisesRegex(ValueError, 'target differs'):
            self.package()
        self.register(body=b'{"schema_version": 1, "kind": "quality_evidence"}')
        with self.assertRaisesRegex(ValueError, 'Unsupported metadata'):
            self.package()

    def test_duplicate_and_nonfinite_json_are_rejected(self):
        plan = self.register()
        for prefix in ['{"schema_version":1,', '{"extra":NaN,']:
            with self.subTest(prefix=prefix):
                self.register(body=(prefix + json.dumps(plan)[1:]).encode())
                with self.assertRaisesRegex(ValueError, 'Disclosure scan'):
                    self.package()

    def test_zip_summary_tampering_is_rejected_even_with_new_integrity_hash(self):
        self.register()
        path = self.package()
        for mutate in [lambda v: v.update(status='pass'), lambda v: v['counts'].update(columns_required=0),
                       lambda v: v.update(blockers=['invented']), lambda v: v['changes'][0].update(after='invented')]:
            with self.subTest(mutate=mutate):
                forged = self.rewrite(path, lambda data: mutate(data['review']['metadata']))
                with self.assertRaisesRegex(ValueError, 'Metadata evidence'):
                    portal.verify_delivery(forged)

    def test_zip_download_bytes_must_match_archived_plan_bytes(self):
        self.register()
        path = self.package()
        def mutate(data):
            item = next(f for f in data['files'] if f['id'] == 'metadata-plan')
            item['base64'] = base64.b64encode(b'{"changed":true}').decode()
        with self.assertRaisesRegex(ValueError, 'Embedded metadata artifact differs'):
            portal.verify_delivery(self.rewrite(path, mutate))

    def test_removed_artifact_cannot_retain_selected_summary(self):
        self.register()
        path = self.package()
        def mutate(data):
            data['files'] = [f for f in data['files'] if f['id'] != 'metadata-plan']
        def remove(entries):
            del entries['01_Model/metadata-plan.json']
        with self.assertRaisesRegex(ValueError, 'Metadata evidence'):
            portal.verify_delivery(self.rewrite(path, mutate, remove))
        def omit(data):
            mutate(data)
            data['review']['metadata'] = portal._metadata_omitted(data['review']['metadata'])
        reduced = self.rewrite(path, omit, remove)
        self.assertEqual(portal.verify_delivery(reduced)['status'], 'integrity_verified')

    def test_metadata_context_and_package_target_cannot_be_removed_or_changed(self):
        self.register()
        path = self.package()
        for mutation in [lambda m: m.pop('context_sha256'), lambda m: m['target'].update(warehouse='bigquery')]:
            with self.subTest(mutation=mutation):
                forged = self.rewrite(path, mutate_manifest=mutation)
                with self.assertRaisesRegex(ValueError, 'Metadata'):
                    portal.verify_delivery(forged)

    def test_duplicate_embedded_artifact_id_is_rejected(self):
        self.register()
        path = self.package()
        def mutate(data):
            data['files'].append(next(f for f in data['files'] if f['id'] == 'metadata-plan'))
        with self.assertRaisesRegex(ValueError, 'Duplicate selected metadata'):
            portal.verify_delivery(self.rewrite(path, mutate))

    def test_hostile_description_stays_json_and_plain_text(self):
        value = dictionary()
        payload = '</script><img src=x onerror=alert(1)> & "雪"\nsecond line'
        value['models'][0]['description'] = payload
        contract = build_contract(value, configuration())
        self.register(plan_metadata(contract, observation(contract)))
        path = self.package()
        self.assertIn(payload, self.payload(path)['review']['metadata']['changes'][0]['after'])
        with zipfile.ZipFile(path) as archive:
            page = archive.read('START_HERE.html').decode()
        self.assertNotIn('<img src=x', page)
        self.assertIn('n.textContent=text(value)', page)
        self.assertEqual(portal.verify_delivery(path)['status'], 'integrity_verified')

    def test_legacy_package_stays_valid_without_metadata_reference(self):
        path = self.package()
        self.assertNotIn('metadata', self.payload(path)['review'])
        self.assertEqual(portal.verify_delivery(path)['status'], 'integrity_verified')

    @unittest.skipUnless(shutil.which('node'), 'Node is required for the offline metadata export regression')
    def test_browser_reexport_omission_matches_python_projection(self):
        self.register()
        data = self.payload(self.package())
        js = (portal.ASSETS / 'portal.js').read_text()
        helpers = js[js.index('function metadataOmitted('):js.index('const metadata=review.metadata;')]
        script = "const assert=require('node:assert/strict');" + helpers
        script += '\nlet next=' + json.dumps(data) + ';const before=structuredClone(next);'
        script += "trimMetadataEvidence(next,next.files);assert.deepEqual(next,before);"
        script += "trimMetadataEvidence(next,next.files.filter(f=>f.id!=='metadata-plan'));"
        script += 'assert.deepEqual(next.review.metadata,' + json.dumps(portal._metadata_omitted(self.review['metadata'])) + ');'
        result = subprocess.run([shutil.which('node'), '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
