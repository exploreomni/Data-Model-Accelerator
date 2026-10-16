"""Portable review projections; no native execution or approval is inferred."""
import base64
import copy
import csv
import hashlib
import io
import json
import re
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

from test_delivery_portal import fixture, portal
import portal_checks


class PortableModelDeliverableTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.state, self.review = fixture(self.root)
        self.sequence = 0

    def package(self, **kwargs):
        self.sequence += 1
        path = self.root / f'delivery-{self.sequence}.zip'
        manifest = portal.package_delivery(self.state, self.review, self.root, path, **kwargs)
        with zipfile.ZipFile(path) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        data = portal_checks.parse_page(files['START_HERE.html'])[1]
        return path, manifest, files, data

    def rewrite(self, path, manifest, files, data):
        encoded = json.dumps(data).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
        files['START_HERE.html'] = re.sub(r'(<script id="delivery-data" type="application/json">).*?(</script>)',
            lambda match: match[1] + encoded + match[2], files['START_HERE.html'].decode(), flags=re.S).encode()
        manifest['files'] = portal.package_file_inventory(data, {name: body for name, body in files.items() if name != 'DELIVERY_MANIFEST.json'})
        files['DELIVERY_MANIFEST.json'] = json.dumps(manifest).encode()
        with zipfile.ZipFile(path, 'w') as archive:
            for name, body in files.items(): archive.writestr(name, body)

    def replace_generated(self, files, data, suffix, body):
        item = next(row for row in data['generated_deliverables'] if row['path'].endswith(suffix))
        item.update(base64=base64.b64encode(body).decode(), sha256=hashlib.sha256(body).hexdigest(), size=len(body))
        files[item['path']] = body

    def test_selected_deliverables_are_real_files_with_an_exhaustive_classified_manifest(self):
        path, manifest, files, data = self.package()
        self.assertEqual(1, manifest['schema_version'])
        self.assertEqual(1, manifest['package_layout_version'])
        self.assertEqual(1, data['file_count'])  # Registered artifacts keep their own denominator.
        self.assertEqual(4, len(data['generated_deliverables']))
        self.assertEqual(set(files) - {'DELIVERY_MANIFEST.json'}, {row['path'] for row in manifest['files']})
        roles = {row['path']: row for row in manifest['files']}
        self.assertEqual('index', roles['README.md']['role'])
        self.assertFalse(roles['README.md']['embedded'])
        self.assertEqual('entrypoint', roles['START_HERE.html']['role'])
        for item in data['generated_deliverables']:
            self.assertEqual(base64.b64decode(item['base64']), files[item['path']])
            self.assertEqual('generated_deliverable', roles[item['path']]['role'])
            self.assertTrue(roles[item['path']]['embedded'])
        readme = files['README.md'].decode()
        self.assertIn('[START_HERE.html](START_HERE.html)', readme)
        self.assertIn('do not establish native validation', readme)
        self.assertNotIn('02_Implementation', readme)
        self.assertFalse(any(name.endswith('/') for name in files))
        self.assertEqual('integrity_verified', portal.verify_delivery(path)['status'])

    def test_audiences_and_categories_omit_unselected_generated_content(self):
        marker = 'COLUMN_SELECTED_ONLY'
        self.review['models'][0]['columns'][0]['name'] = marker
        for audience, categories, generated_categories in (
            ('reviewer', ['diagrams'], {'diagrams'}), ('reviewer', ['dictionary'], {'dictionary'}),
            ('reviewer', ['documentation'], set()), ('engineer', ['implementation'], set()),
            ('audit', ['technical_audit'], set()),
        ):
            with self.subTest(audience=audience, categories=categories):
                path, _, files, data = self.package(audience=audience, include=categories)
                self.assertEqual(generated_categories, {row['category'] for row in data['generated_deliverables']})
                if 'dictionary' not in categories:
                    self.assertNotIn(marker, b'\n'.join(files.values()).decode(errors='replace'))
                if categories == ['diagrams'] or categories == ['dictionary']:
                    self.assertEqual([], data['files'])
                    self.assertEqual(0, data['projection']['selected_artifact_count'])
                if audience == 'audit':
                    self.assertFalse(any(name.startswith('01_Model/') for name in files))
                self.assertEqual('integrity_verified', portal.verify_delivery(path)['status'])

    def test_csv_and_markdown_preserve_all_columns_and_unknown_definitions_safely(self):
        self.review['models'][0]['columns'] = [{'name': 'column_' + str(i), 'type': 'TEXT', 'description': 'a | b < c'} for i in range(9)]
        self.review['models'][0]['columns'][0]['name'] = '=SUM(A1:A2)'
        self.review['models'][1]['columns'] = []
        _, _, files, _ = self.package(include=['dictionary'])
        rows = list(csv.DictReader(io.StringIO(files['01_Model/Dictionary/data-dictionary.csv'].decode())))
        self.assertEqual(11, len(rows))
        self.assertEqual("'=SUM(A1:A2)", rows[0]['column_name'])
        self.assertEqual('Column definitions not supplied.', rows[9]['description'])
        markdown = files['01_Model/Dictionary/data-dictionary.md'].decode()
        self.assertIn('column\u005f8', markdown.replace('\\_', '_'))
        self.assertIn('a \\| b &lt; c', markdown)

    def test_paged_svg_scope_and_editable_source_keep_every_model_and_connection(self):
        self.review['models'] = [{'id': f'gold.table_{i}', 'name': f'table_{i}', 'layer': 'gold', 'columns': []} for i in range(80)]
        self.review['relationships'] = [{'from': f'gold.table_{i}', 'to': f'gold.table_{i+1}', 'kind': 'lineage'} for i in range(79)]
        path, _, files, data = self.package(include=['diagrams'])
        diagrams = [row for row in data['generated_deliverables'] if row['path'].endswith('.svg')]
        self.assertGreater(len(diagrams), 1)
        ids = [identifier for row in diagrams for identifier in row['diagram_model_ids']]
        self.assertEqual(80, len(ids)); self.assertEqual(80, len(set(ids)))
        source = json.loads(files['01_Model/ERD/model-source.json'])
        self.assertEqual(self.review['relationships'], source['relationships'])
        self.assertEqual(80, len(source['models']))
        self.assertTrue(all('columns' not in model for model in source['models']))
        self.assertEqual('integrity_verified', portal.verify_delivery(path)['status'])

    def test_exports_are_deterministic_and_source_and_frozen_outputs_are_unchanged(self):
        before_review, before_state = copy.deepcopy(self.review), copy.deepcopy(self.state)
        source = {row['path']: (self.root / row['path']).read_bytes() for row in self.review['artifacts']}
        first, _, files, _ = self.package()
        second, _, again, _ = self.package()
        self.assertEqual(files, again); self.assertEqual(first.read_bytes(), second.read_bytes())
        with self.assertRaisesRegex(ValueError, 'exists'):
            portal.package_delivery(self.state, self.review, self.root, first)
        self.assertEqual(before_review, self.review); self.assertEqual(before_state, self.state)
        self.assertEqual(source, {name: (self.root / name).read_bytes() for name in source})

    def test_generated_collisions_fail_without_rewriting_registered_files(self):
        body = b'Registered bytes must stay immutable.'
        source = self.root / 'Dictionary/data-dictionary.md'
        source.parent.mkdir(); source.write_bytes(body)
        self.review['artifacts'].append({'id': 'registered-dictionary', 'path': 'Dictionary/data-dictionary.md',
            'category': 'dictionary', 'audiences': ['reviewer'], 'sha256': hashlib.sha256(body).hexdigest()})
        with self.assertRaisesRegex(ValueError, 'collides'):
            self.package(include=['dictionary'])
        self.assertEqual(body, source.read_bytes())
        self.assertFalse(list(self.root.glob('*.zip')))
        with self.assertRaisesRegex(ValueError, 'README'):
            portal.package_file_inventory({'files': [{'path': 'README.md', 'category': 'documentation'}]}, {})

    def test_forged_generated_identity_path_category_and_hash_fail(self):
        _, _, _, data = self.package()
        for key, value in (('id', 'forged'), ('path', '../escape.svg'), ('category', 'implementation'), ('sha256', '0'*64)):
            changed = copy.deepcopy(data)
            changed['generated_deliverables'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                portal.validate_generated_deliverables(changed)

    def test_self_consistent_changed_dictionary_and_source_still_fail_review_inventory(self):
        for suffix in ('model-source.json', 'data-dictionary.csv'):
            with self.subTest(suffix=suffix):
                path, manifest, files, data = self.package()
                item = next(row for row in data['generated_deliverables'] if row['path'].endswith(suffix))
                body = files[item['path']].replace(b'bronze.orders', b'bronze.forged')
                self.replace_generated(files, data, suffix, body)
                self.rewrite(path, manifest, files, data)
                with self.assertRaisesRegex(ValueError, 'differs from selected review'):
                    portal.verify_delivery(path)

    def test_equivalent_svg_layout_and_json_formatting_are_supported(self):
        path, manifest, files, data = self.package()
        item = next(row for row in data['generated_deliverables'] if row['path'].endswith('.svg'))
        tree = ET.fromstring(files[item['path']])
        tree.set('width', str(float(tree.get('width')) + 100))
        tree.set('viewBox', '0 0 ' + tree.get('width') + ' ' + tree.get('height'))
        self.replace_generated(files, data, '.svg', ET.tostring(tree))
        source = json.loads(files['01_Model/ERD/model-source.json'])
        self.replace_generated(files, data, 'model-source.json', json.dumps(source).encode())
        self.rewrite(path, manifest, files, data)
        self.assertEqual('integrity_verified', portal.verify_delivery(path)['status'])

    def test_manifest_cannot_relabel_a_generated_file_as_registered(self):
        path, manifest, files, _ = self.package()
        next(row for row in manifest['files'] if row['role'] == 'generated_deliverable')['role'] = 'registered_artifact'
        files['DELIVERY_MANIFEST.json'] = json.dumps(manifest).encode()
        with zipfile.ZipFile(path, 'w') as archive:
            for name, body in files.items(): archive.writestr(name, body)
        with self.assertRaisesRegex(ValueError, 'file roles differ'):
            portal.verify_delivery(path)

    def test_output_scanning_covers_generated_files_and_whole_zip(self):
        with patch.object(portal, '_check_disclosure_bytes', wraps=portal._check_disclosure_bytes) as scan:
            _, _, _, data = self.package()
        filenames = {call.args[1] for call in scan.call_args_list}
        self.assertTrue({row['path'] for row in data['generated_deliverables']} <= filenames)
        self.assertTrue({'README.md', 'START_HERE.html', 'delivery.zip'} <= filenames)

    def test_generated_only_deliverables_cannot_bypass_disclosure_scanning(self):
        marker = 'synthetic.person@example.invalid'
        self.review['models'][0]['columns'][0]['description'] = marker
        with self.assertRaises(ValueError) as error:
            self.package(include=['dictionary'])
        self.assertNotIn(marker, str(error.exception))
        self.assertFalse(list(self.root.glob('*.zip')))
        self.review['models'][0]['columns'][0]['description'] = 'Source identifier'
        self.review['models'][0]['grain'] = marker
        with self.assertRaises(ValueError):
            self.package(include=['diagrams'])
        self.assertFalse(list(self.root.glob('*.zip')))


if __name__ == '__main__':
    unittest.main()
