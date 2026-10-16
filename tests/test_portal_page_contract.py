"""Rendered-page contracts and selected-byte integrity, using synthetic inputs."""
import base64
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import delivery_portal as portal
import portal_checks as checks
from test_delivery_portal import fixture


class PortalPageContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.state, self.review = fixture(self.root)

    def package(self, **kwargs):
        path = self.root / ('delivery-' + str(len(list(self.root.glob('*.zip')))) + '.zip')
        manifest = portal.package_delivery(self.state, self.review, self.root, path, **kwargs)
        with zipfile.ZipFile(path) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        return path, manifest, entries, checks.parse_page(entries['START_HERE.html'])[1]

    def replace_data(self, page, data):
        before = page.split('<script id="delivery-data" type="application/json">', 1)
        after = before[1].split('</script>', 1)[1]
        return before[0] + '<script id="delivery-data" type="application/json">' + json.dumps(data) + '</script>' + after

    def test_page_modes_and_counts_are_explicit_and_do_not_disclose_exclusions(self):
        path, _, entries, data = self.package()
        self.assertEqual('reviewer', data['audience'])
        self.assertEqual('package', data['page_mode'])
        self.assertEqual(1, data['file_count'])
        self.assertEqual(1, data['projection']['selected_artifact_count'])
        self.assertEqual(3, data['projection']['excluded_artifact_count'])
        self.assertEqual(['diagrams', 'dictionary', 'documentation', 'validation'], data['selected_categories'])
        page = entries['START_HERE.html'].decode()
        for forbidden in ('models/gold.sql', 'seeds/raw.csv', 'audit/evidence.json', 'SENSITIVE_RAW_MARKER', 'INTERNAL_AUDIT_MARKER'):
            self.assertNotIn(forbidden, page)
        self.assertEqual('page_contract_verified', portal.check_page(path)['status'])

    def test_status_render_never_reads_registered_artifact_bytes_or_requires_node(self):
        for record in self.review['artifacts']:
            (self.root / record['path']).unlink()
        destination = self.root / 'status.html'
        with patch('portal_checks.shutil.which', side_effect=AssertionError('Normal rendering must not require Node')):
            portal.render_engagement(self.state, destination, self.review)
        _, data = checks.parse_page(destination.read_bytes())
        self.assertEqual('status', data['page_mode'])
        self.assertEqual([], data['files'])
        self.assertEqual([], data['selected_categories'])
        self.assertEqual(0, data['file_count'])
        self.assertEqual(4, data['projection']['excluded_artifact_count'])
        self.assertIn('not read', data['projection']['qualification'])

    def test_fresh_renders_are_identical_and_saved_bytes_match_selected_artifacts(self):
        first, _, entries, data = self.package(audience='engineer')
        second, _, again, _ = self.package(audience='engineer')
        self.assertEqual(entries['START_HERE.html'], again['START_HERE.html'])
        selected = portal.select_artifacts(self.review, self.root, 'engineer', portal.resolve_selection(self.state, 'engineer'))
        expected = {record['destination']: record['content'] for record in selected}
        checks.validate_page(entries['START_HERE.html'], expected_files=expected, expected_data=data)
        for path in (first, second):
            self.assertEqual('integrity_verified', portal.verify_delivery(path)['status'])
        status = self.root / 'status.html'
        portal.render_engagement(self.state, status, self.review)
        initial = status.read_bytes()
        portal.render_engagement(self.state, status, self.review)
        self.assertEqual(initial, status.read_bytes())

    def test_engineer_subsets_and_audit_keep_only_their_selected_bytes(self):
        for audience, include, expected in (
            ('engineer', ['implementation'], ['02_Implementation/models/gold.sql']),
            ('audit', None, ['Technical_Audit/audit/evidence.json']),
        ):
            with self.subTest(audience=audience):
                path, _, entries, data = self.package(audience=audience, include=include)
                self.assertEqual(expected, [record['path'] for record in data['files']])
                self.assertEqual(1, data['file_count'])
                self.assertEqual('integrity_verified', portal.verify_delivery(path)['status'])
                checks.validate_page(entries['START_HERE.html'])

    def test_nested_section_parents_ids_classes_and_navigation_are_checked(self):
        _, _, entries, _ = self.package()
        page = entries['START_HERE.html'].decode()
        changes = (
            (page.replace('id="architecture"', 'id="lineage"', 1), 'unique'),
            (page.replace('id="architecture" class="review-section panel"', 'id="architecture" class="panel"', 1), 'review section'),
            (page.replace('id="lineage" class="review-section panel"', 'id="lineage" data-section class="review-section panel"', 1), 'review section'),
            (page.replace('href="#lineage" data-nav="lineage"', 'href="#model" data-nav="lineage"', 1), 'navigation'),
            (page.replace(' data-nav="replacement-map"', '', 1), 'no navigation'),
            (page.replace('id="review-feedback" class="review-section panel" data-section',
                          'id="review-feedback" class="review-section panel"', 1), 'review section'),
            (page.replace(' data-nav="review-feedback"', '', 1), 'no navigation'),
            (page.replace('id="model"', 'id="wrong-model"', 1), 'parent route'),
        )
        for mutated, message in changes:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    checks.validate_page(mutated)

    def test_embedded_file_size_hash_count_and_inventory_are_verified(self):
        _, _, entries, data = self.package(audience='engineer')
        page = entries['START_HERE.html'].decode()
        for mutation in ('bytes', 'size', 'hash', 'count', 'projection', 'category', 'duplicate'):
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(data)
                item = changed['files'][0]
                if mutation == 'bytes': item['base64'] = base64.b64encode(b'changed bytes').decode()
                elif mutation == 'size': item['size'] += 1
                elif mutation == 'hash': item['sha256'] = '0' * 64
                elif mutation == 'count': changed['file_count'] += 1
                elif mutation == 'projection': changed['projection']['selected_artifact_count'] += 1
                elif mutation == 'category': changed['selected_categories'] = []
                elif mutation == 'duplicate': changed['files'].append(copy.deepcopy(item))
                with self.assertRaisesRegex(ValueError, 'Page'):
                    checks.validate_page(self.replace_data(page, changed))
        with self.assertRaisesRegex(ValueError, 'inventory differs'):
            checks.validate_page(page, expected_files={})

    def test_zip_verifier_rejects_self_consistent_page_payload_that_disagrees_with_archive(self):
        path, manifest, entries, data = self.package()
        changed = b'Self-consistent but unselected payload'
        data['files'][0].update(base64=base64.b64encode(changed).decode(), size=len(changed),
                                sha256=hashlib.sha256(changed).hexdigest())
        entries['START_HERE.html'] = self.replace_data(entries['START_HERE.html'].decode(), data).encode()
        record = next(row for row in manifest['files'] if row['path'] == 'START_HERE.html')
        record.update(bytes=len(entries['START_HERE.html']), sha256=hashlib.sha256(entries['START_HERE.html']).hexdigest())
        entries['DELIVERY_MANIFEST.json'] = json.dumps(manifest).encode()
        with zipfile.ZipFile(path, 'w') as archive:
            for name, body in entries.items(): archive.writestr(name, body)
        with self.assertRaisesRegex(ValueError, 'embedded inventory differs'):
            portal.verify_delivery(path)

    def test_check_page_cli_does_not_assess_or_require_engagement_state(self):
        path, _, _, _ = self.package()
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch('portal_checks.shutil.which', return_value=None):
            self.assertEqual(0, portal.main(['check-page', str(path)]))
        self.assertEqual('page_contract_verified', json.loads(output.getvalue())['status'])
        with patch('portal_checks.shutil.which', return_value=None):
            with self.assertRaisesRegex(ValueError, 'Node is required only'):
                portal.check_page(path, javascript=True)

    def test_selected_semantic_views_retain_dimension_only_models_and_omit_with_evidence(self):
        from omni_contract import canonical_hash
        data = portal._presentation(self.state, self.review)
        summary = {'schema_version': 1, 'kind': 'omni_semantic_handoff',
                   'pins': {'context_sha256': data['engagement']['context_sha256'],
                            'target': data['engagement']['target'], 'model_candidate_sha256': 'a' * 64},
                   'static_status': 'candidate', 'topics': [], 'metrics': [], 'query_views': {},
                   'dependencies': [], 'decisions': [], 'unknowns': [], 'next_actions': [],
                   'views': {'dimension_only': {'kind': 'physical_or_inherited', 'dimensions': 2, 'measures': 0}}}
        summary['handoff_sha256'] = canonical_hash(summary)
        body = json.dumps(summary).encode()
        artifact = {'id': 'semantic', 'sha256': hashlib.sha256(body).hexdigest(), 'content': body}
        data['review']['omni'] = {'artifact_id': artifact['id'], 'sha256': artifact['sha256']}
        portal._select_omni_evidence(data, [artifact])
        self.assertEqual(summary['views'], data['review']['omni']['views'])
        portal._select_omni_evidence(data, [])
        self.assertNotIn('views', data['review']['omni'])
        self.assertEqual('not_included', data['review']['omni']['evidence_state'])

    def test_frozen_legacy_semantic_projection_verifies_without_weakening_new_views(self):
        from omni_contract import canonical_hash
        path, manifest, entries, data = self.package()
        summary = {'schema_version': 1, 'kind': 'omni_semantic_handoff',
                   'pins': {'context_sha256': data['engagement']['context_sha256'],
                            'target': data['engagement']['target'], 'model_candidate_sha256': 'a' * 64},
                   'static_status': 'candidate', 'topics': [], 'metrics': [], 'query_views': {},
                   'dependencies': [], 'decisions': [], 'unknowns': [], 'next_actions': [],
                   'views': {'dimension_only': {'kind': 'physical_or_inherited', 'dimensions': 2, 'measures': 0}}}
        summary['handoff_sha256'] = canonical_hash(summary)
        body = json.dumps(summary).encode()
        file = data['files'][0]
        old_path, portable_path = file['path'], '01_Model/semantic.json'
        del entries[old_path]
        entries[portable_path] = body
        file.update(path=portable_path, base64=base64.b64encode(body).decode(),
                    size=len(body), sha256=hashlib.sha256(body).hexdigest())
        next(record for record in manifest['files'] if record['path'] == old_path)['path'] = portable_path
        data['review']['omni'] = {'artifact_id': file['id'], 'sha256': file['sha256']}
        portal._select_omni_evidence(data, [{'id': file['id'], 'sha256': file['sha256'], 'content': body}])
        current = copy.deepcopy(data)
        legacy = copy.deepcopy(data)
        for key in ('page_mode', 'file_count', 'selected_categories', 'projection', 'package_layout_version', 'generated_deliverables'):
            legacy.pop(key)
        legacy['review']['omni'].pop('views')

        def write(snapshot):
            contents={name:body for name,body in entries.items() if name!='DELIVERY_MANIFEST.json'}
            saved=copy.deepcopy(manifest)
            contents['START_HERE.html'] = self.replace_data(entries['START_HERE.html'].decode(), snapshot).encode()
            if 'package_layout_version' in snapshot:
                contents['README.md']=portal.package_readme(snapshot)
                saved['files']=portal.package_file_inventory(snapshot,contents)
            else:
                saved.pop('package_layout_version')
                contents={name:body for name,body in contents.items() if name=='START_HERE.html' or name in {row['path'] for row in snapshot['files']}}
                saved['files']=[{'path':name,'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()} for name,body in sorted(contents.items())]
            contents['DELIVERY_MANIFEST.json'] = json.dumps(saved).encode()
            with zipfile.ZipFile(path, 'w') as archive:
                for name, content in contents.items(): archive.writestr(name, content)

        write(legacy)
        self.assertEqual('integrity_verified', portal.verify_delivery(path)['status'])
        write(current)
        self.assertEqual('integrity_verified', portal.verify_delivery(path)['status'])
        for snapshot in (legacy, current):
            changed = copy.deepcopy(snapshot)
            changed['review']['omni']['views'] = {'forged': {'kind': 'physical_or_inherited', 'dimensions': 1, 'measures': 0}}
            write(changed)
            with self.assertRaisesRegex(ValueError, 'Omni evidence.*differs'):
                portal.verify_delivery(path)
        current['review']['omni'].pop('views')
        write(current)
        with self.assertRaisesRegex(ValueError, 'Omni evidence.*differs'):
            portal.verify_delivery(path)

    @unittest.skipUnless(shutil.which('node'), 'Node is required only for explicit JavaScript self-checks')
    def test_javascript_check_covers_all_executable_blocks_and_excludes_json(self):
        _, _, entries, _ = self.package()
        page = entries['START_HERE.html'].decode()
        result = checks.check_javascript(page)
        self.assertEqual(2, result['scripts'])
        self.assertFalse(result['smoke'])
        with self.assertRaisesRegex(ValueError, 'syntax check failed'):
            checks.check_javascript(page.replace('</body>', '<script>const invalid = ;</script></body>'))
        minimal = ('<!doctype html><html><body><script id="delivery-data" type="application/json">'
                   '{"payload":true}</script><script>document.getElementById("control").textContent="ready";</script>'
                   '<script>document.getElementById("control").textContent+=" twice";</script></body></html>')
        result = checks.check_javascript(minimal,
            prelude='const assert=require("node:assert/strict"),control={textContent:""};const document={getElementById:()=>control};',
            assertions='assert.equal(control.textContent,"ready twice");')
        self.assertEqual({'status': 'javascript_checked', 'scripts': 2, 'smoke': True}, result)


if __name__ == '__main__':
    unittest.main()
