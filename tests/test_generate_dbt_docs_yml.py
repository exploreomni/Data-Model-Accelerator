"""Static projection respects explicit identities, YAML ownership and review pins."""
import copy
from importlib import metadata
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/data-model-accelerator'
sys.path.insert(0, str(SKILL / 'scripts'))
from data_dictionary_v2 import migrate_dictionary
from generate_dbt_docs_yml import generate_project, MANIFEST_NAME
from test_data_dictionary_v2 import canonical

try:
    HAS_PINNED_YAML = metadata.version('ruamel.yaml') == '0.18.16'
except metadata.PackageNotFoundError:
    HAS_PINNED_YAML = False


def approved_dictionary():
    value = migrate_dictionary(canonical())
    for model in value['models']:
        for record in [model] + model['columns']:
            record['review_status'] = 'approved'
            record['provenance']['review_reference'] = 'explicit-fixture-review'
    return value


@unittest.skipUnless(HAS_PINNED_YAML, 'Pinned ruamel.yaml is installed in the full metadata verification environment')
class DbtDocsGenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / 'project'
        self.project.mkdir()
        (self.project / 'dbt_project.yml').write_text("name: fixture\nversion: '1.0.0'\nconfig-version: 2\n")
        (self.project / 'models').mkdir()
        (self.project / 'models/customer.sql').write_text("select 'never executed' as customer_id\n")
        self.dictionary = approved_dictionary()
        self.binding = {'model_id': self.dictionary['models'][0]['model_id'], 'resource_type': 'model',
                        'name': 'customer', 'property_path': 'models/_docs.yml', 'config_path': [],
                        'columns': [{'column_id': self.dictionary['models'][0]['columns'][0]['column_id'], 'name': 'customer_id'}]}
        self.bindings = {'schema_version': 1, 'kind': 'dbt_metadata_bindings', 'project_name': 'fixture', 'resources': [self.binding]}

    def preview(self, **options):
        return generate_project(self.project, self.dictionary, self.bindings, **options)

    def apply(self, preview, target='candidate', **options):
        destination = self.root / target
        result = self.preview(apply=True, output=destination, reviewed_preview_sha256=preview['preview_sha256'], **options)
        return destination, result

    def yaml(self, path):
        from ruamel.yaml import YAML
        return YAML(typ='safe', pure=True).load(path.read_text())

    def test_preview_changes_nothing_and_apply_requires_exact_digest(self):
        before = {str(p): p.read_bytes() for p in self.project.rglob('*') if p.is_file()}
        preview = self.preview()
        self.assertEqual(preview['status'], 'ready')
        self.assertEqual(len(preview['changes']), 2)
        self.assertEqual({str(p): p.read_bytes() for p in self.project.rglob('*') if p.is_file()}, before)
        with self.assertRaisesRegex(ValueError, 'exact reviewed'):
            self.preview(apply=True, output=self.root / 'bad', reviewed_preview_sha256='a' * 64)
        self.assertFalse((self.root / 'bad').exists())
        candidate, result = self.apply(preview)
        self.assertEqual((candidate / 'models/customer.sql').read_bytes(), (self.project / 'models/customer.sql').read_bytes())
        self.assertEqual(result['preview_sha256'], preview['preview_sha256'])
        project = self.yaml(candidate / 'dbt_project.yml')
        self.assertEqual(project['models']['fixture']['+persist_docs'], {'relation': True, 'columns': True})
        model = self.yaml(candidate / 'models/_docs.yml')['models'][0]
        self.assertIn('Grain: One fixture event', model['description'])
        self.assertEqual(model['config']['meta']['dma']['resource_id'], self.binding['model_id'])
        self.assertNotIn('meta', model)
        self.assertEqual({str(p): p.read_bytes() for p in self.project.rglob('*') if p.is_file()}, before)

    def test_unchanged_rerun_is_byte_identical_and_no_op(self):
        candidate, result = self.apply(self.preview())
        baseline = result['ownership_manifest']
        repeated = generate_project(candidate, self.dictionary, self.bindings, previous_manifest=baseline)
        self.assertEqual(repeated['status'], 'no_op', repeated['conflicts'])
        self.assertEqual(repeated['changes'], [])
        self.assertEqual(repeated['ownership_manifest'], baseline)
        destination = self.root / 'unchanged-copy'
        generate_project(candidate, self.dictionary, self.bindings, previous_manifest=baseline,
                         apply=True, output=destination, reviewed_preview_sha256=repeated['preview_sha256'])
        for path in candidate.rglob('*'):
            if path.is_file():
                self.assertEqual(path.read_bytes(), (destination / path.relative_to(candidate)).read_bytes())

    def test_units_do_not_hide_placeholder_descriptions(self):
        self.dictionary['models'][0]['columns'][0].update(description='TBD',units='USD')
        preview=self.preview()
        self.assertEqual(preview['status'],'conflicted')
        self.assertTrue(any('placeholder' in str(item) for item in preview['conflicts']))

    def test_three_way_updates_unchanged_owned_description(self):
        candidate, result = self.apply(self.preview())
        self.dictionary['models'][0]['description'] = 'New approved description'
        updated = generate_project(candidate, self.dictionary, self.bindings, previous_manifest=result['ownership_manifest'])
        self.assertFalse(updated['conflicts'])
        self.assertTrue(any('New approved description' in row['diff'] for row in updated['changes']))

    def test_human_change_conflicts_without_overwrite(self):
        candidate, result = self.apply(self.preview())
        path = candidate / 'models/_docs.yml'
        path.write_text(path.read_text().replace('Explicit fixture description', 'Human changed the meaning'))
        self.dictionary['models'][0]['description'] = 'Another approved description'
        before = path.read_bytes()
        preview = generate_project(candidate, self.dictionary, self.bindings, previous_manifest=result['ownership_manifest'])
        self.assertEqual(preview['status'], 'conflicted')
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            generate_project(candidate, self.dictionary, self.bindings, previous_manifest=result['ownership_manifest'],
                             apply=True, output=self.root / 'conflict', reviewed_preview_sha256=preview['preview_sha256'])
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.root / 'conflict').exists())

    def test_existing_unowned_definition_conflicts(self):
        (self.project / 'models/_docs.yml').write_text('version: 2\nmodels:\n  - name: customer\n    description: Existing owner definition\n')
        preview = self.preview()
        self.assertTrue(any('conflicts with the dictionary' in row['reason'] for row in preview['conflicts']))

    def test_roundtrip_preserves_comments_anchors_quotes_tests_alias_and_doc_jinja(self):
        (self.project / 'models/_docs.yml').write_text('''# Customer-owned documentation
version: 2
x-defaults: &defaults
  materialized: table
models:
  - name: customer
    description: 'Curated model description' # keep meaning
    config:
      <<: *defaults
      alias: "Curated_Name"
      persist_docs: {columns: false}
      meta:
        owner_note: "Do not replace"
    columns:
      - name: customer_id
        description: '{{ doc("customer") }}'
        tests: [not_null]
        constraints:
          - type: not_null
''')
        self.binding['description_policy'] = 'preserve'
        self.binding['columns'][0]['description_policy'] = 'preserve'
        preview = self.preview()
        self.assertFalse(preview['conflicts'], preview['conflicts'])
        candidate, _ = self.apply(preview)
        text = (candidate / 'models/_docs.yml').read_text()
        for marker in ('# Customer-owned documentation', '&defaults', '*defaults', '"Curated_Name"', '# keep meaning', '{{ doc("customer") }}'):
            self.assertIn(marker, text)
        self.assertIn('models:\n  - name: customer\n', text)
        model = self.yaml(candidate / 'models/_docs.yml')['models'][0]
        self.assertEqual(model['columns'][0]['tests'], ['not_null'])
        self.assertEqual(model['columns'][0]['constraints'], [{'type': 'not_null'}])
        self.assertEqual(model['config']['meta']['owner_note'], 'Do not replace')
        self.assertTrue(any(row.get('effective_static_persist_docs', {}).get('columns') is False for row in preview['exceptions']))

    def test_per_folder_and_project_false_overrides_are_preserved(self):
        (self.project / 'dbt_project.yml').write_text('''name: fixture
models:
  fixture:
    +persist_docs: {relation: false}
    silver:
      +persist_docs: {columns: false}
''')
        self.binding['config_path'] = ['silver']
        preview = self.preview()
        self.assertFalse(preview['conflicts'])
        candidate, _ = self.apply(preview)
        config = self.yaml(candidate / 'dbt_project.yml')['models']['fixture']
        self.assertFalse(config['+persist_docs']['relation'])
        self.assertFalse(config['silver']['+persist_docs']['columns'])
        self.assertTrue(any(row.get('effective_static_persist_docs') == {'relation': False, 'columns': False} for row in preview['exceptions']))

    def test_missing_or_duplicate_explicit_bindings_are_rejected(self):
        for change in (lambda b: b['resources'][0].update(model_id='guess.from.physical.name'),
                       lambda b: b['resources'].append(copy.deepcopy(b['resources'][0])),
                       lambda b: b['resources'][0]['columns'][0].update(column_id='guess'),
                       lambda b: b['resources'][0].update(columns=[]),
                       lambda b: b.update(project_name='wrong')):
            bindings = copy.deepcopy(self.bindings)
            change(bindings)
            with self.assertRaises(ValueError):
                generate_project(self.project, self.dictionary, bindings)

    def test_duplicate_patches_across_files_block_apply(self):
        for name in ('a.yml', 'b.yml'):
            (self.project / 'models' / name).write_text('models:\n  - name: customer\n')
        preview = self.preview()
        self.assertEqual(preview['status'], 'conflicted')
        self.assertTrue(any('Duplicate resource patch' in row['reason'] for row in preview['conflicts']))

    def test_different_existing_property_location_is_not_duplicated(self):
        (self.project / 'models/owned.yml').write_text('models:\n  - name: customer\n')
        preview = self.preview()
        self.assertTrue(any('different file' in row['reason'] for row in preview['conflicts']))

    def test_sources_are_separate_and_do_not_get_persist_docs(self):
        source = copy.deepcopy(self.dictionary['models'][0])
        source['source_id'] = source.pop('model_id') + ':source'
        source['columns'][0]['column_id'] += ':source'
        self.dictionary['sources'] = [source]
        self.dictionary['source_inventory_sha256'] = 'b' * 64
        self.bindings['resources'].append({'source_id': source['source_id'], 'resource_type': 'source',
            'source_name': 'raw', 'name': 'customer_raw', 'property_path': 'models/sources.yml',
            'columns': [{'column_id': source['columns'][0]['column_id'], 'name': 'CustomerID'}]})
        preview = self.preview()
        self.assertFalse(preview['conflicts'], preview['conflicts'])
        candidate, _ = self.apply(preview)
        document = self.yaml(candidate / 'models/sources.yml')
        self.assertNotIn('models', document)
        source_table = document['sources'][0]['tables'][0]
        self.assertEqual(source_table['name'], 'customer_raw')
        self.assertEqual(source_table['columns'][0]['name'], 'CustomerID')
        self.assertNotIn('persist_docs', source_table['config'])
        self.assertNotIn('sources', self.yaml(candidate / 'dbt_project.yml'))
        self.assertTrue(any('does not write source metadata' in row['reason'] for row in preview['exceptions']))

    def test_seed_and_snapshot_have_distinct_property_groups_and_defaults(self):
        self.dictionary['models'] = []
        self.bindings['resources'] = []
        for kind in ('model', 'seed', 'snapshot'):
            record = copy.deepcopy(approved_dictionary()['models'][0])
            record['model_id'] = kind + ':stable'
            record['columns'][0]['column_id'] = kind + ':column'
            self.dictionary['models'].append(record)
            item = copy.deepcopy(self.binding)
            item.update(model_id=record['model_id'], resource_type=kind, name=kind + '_name')
            item['columns'][0]['column_id'] = record['columns'][0]['column_id']
            self.bindings['resources'].append(item)
        preview = self.preview()
        self.assertFalse(preview['conflicts'], preview['conflicts'])
        candidate, _ = self.apply(preview)
        props = self.yaml(candidate / 'models/_docs.yml')
        config = self.yaml(candidate / 'dbt_project.yml')
        for plural in ('models', 'seeds', 'snapshots'):
            self.assertEqual(len(props[plural]), 1)
            self.assertEqual(config[plural]['fixture']['+persist_docs'], {'relation': True, 'columns': True})

    def test_versioned_models_preserve_alias_defined_in_and_inherited_columns(self):
        self.binding['version'] = 2
        (self.project / 'models/_docs.yml').write_text('''version: 2
models:
  - name: customer
    latest_version: 2
    columns:
      - name: inherited
        tests: [not_null]
    versions:
      - v: 1
        config: {alias: old_customer}
      - v: 2
        defined_in: customer_latest
        config: {alias: live_customer}
        columns:
          - include: '*'
''')
        preview = self.preview()
        self.assertFalse(preview['conflicts'], preview['conflicts'])
        candidate, _ = self.apply(preview)
        model = self.yaml(candidate / 'models/_docs.yml')['models'][0]
        self.assertEqual(model['latest_version'], 2)
        self.assertEqual(model['versions'][0], {'v': 1, 'config': {'alias': 'old_customer'}})
        self.assertEqual(model['versions'][1]['defined_in'], 'customer_latest')
        self.assertEqual(model['versions'][1]['config']['alias'], 'live_customer')
        self.assertEqual(model['versions'][1]['columns'][0], {'include': '*'})

    def test_unbound_version_is_not_guessed(self):
        (self.project / 'models/_docs.yml').write_text('models:\n  - name: customer\n    versions:\n      - v: 1\n')
        self.assertTrue(any('explicit version' in row['reason'] for row in self.preview()['conflicts']))

    def test_version_inherits_base_persistence_exception(self):
        self.binding['version'] = 2
        (self.project / 'models/_docs.yml').write_text('models:\n  - name: customer\n    config:\n      persist_docs: {columns: false}\n    versions:\n      - v: 2\n')
        preview = self.preview()
        self.assertFalse(preview['conflicts'], preview['conflicts'])
        self.assertTrue(any(row.get('effective_static_persist_docs', {}).get('columns') is False for row in preview['exceptions']))

    def test_document_markers_and_crlf_are_preserved(self):
        path = self.project / 'models/_docs.yml'
        path.write_bytes(b'---\r\nversion: 2\r\nmodels:\r\n  - name: customer\r\n...\r\n')
        candidate, _ = self.apply(self.preview())
        content = (candidate / 'models/_docs.yml').read_bytes()
        self.assertTrue(content.startswith(b'---\r\n'))
        self.assertTrue(content.endswith(b'...\r\n'))
        self.assertNotIn(b'\n', content.replace(b'\r\n', b''))

    def test_imported_jinja_is_not_emitted_and_project_macros_are_not_run(self):
        sentinel = self.root / 'should-not-exist'
        (self.project / 'macros').mkdir()
        macro = "{% macro danger() %}{{ run_query('drop table anything') }}{% endmacro %}"
        (self.project / 'macros/danger.sql').write_text(macro)
        self.dictionary['models'][0]['description'] = '{{ danger() }}'
        preview = self.preview()
        self.assertTrue(any('template-bearing' in row['reason'] for row in preview['conflicts']))
        self.assertFalse(sentinel.exists())
        self.assertEqual((self.project / 'macros/danger.sql').read_text(), macro)

    def test_unsafe_yaml_uses_review_patch_without_writes(self):
        for text in ('models: !unsafe []\n', 'models: []\nmodels: []\n', "{% if execute %}\nmodels: []\n{% endif %}\n"):
            (self.project / 'models/_docs.yml').write_text(text)
            preview = self.preview()
            self.assertEqual(preview['status'], 'conflicted')
            self.assertTrue(preview['field_patch'])
            self.assertEqual((self.project / 'models/_docs.yml').read_text(), text)

    def test_shared_alias_cannot_mutate_other_resource(self):
        (self.project / 'models/_docs.yml').write_text('''models:
  - &shared
    name: customer
  - *shared
''')
        self.assertTrue(self.preview()['conflicts'])

    def test_source_drift_or_dictionary_change_invalidates_preview(self):
        preview = self.preview()
        (self.project / 'models/customer.sql').write_text('select 2 as customer_id')
        with self.assertRaisesRegex(ValueError, 'reviewed preview'):
            self.apply(preview)
        preview = self.preview()
        self.dictionary['models'][0]['description'] = 'Different approved meaning'
        with self.assertRaisesRegex(ValueError, 'reviewed preview'):
            self.apply(preview)

    def test_existing_output_input_subdirectory_and_symlink_are_refused(self):
        preview = self.preview()
        for destination in (self.project, self.project / 'out'):
            with self.assertRaises(ValueError):
                self.preview(apply=True, output=destination, reviewed_preview_sha256=preview['preview_sha256'])
        linked = self.project / 'models/outside.sql'
        linked.symlink_to(self.root / 'missing.sql')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.preview()

    def test_unapproved_description_blocks_projection(self):
        self.dictionary['models'][0]['review_status'] = 'unresolved'
        self.assertTrue(any('not approved' in row['reason'] for row in self.preview()['conflicts']))

    def test_owned_baseline_cannot_be_tampered_silently(self):
        preview = self.preview()
        baseline = preview['ownership_manifest']
        baseline['fields'][0]['value'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            self.preview(previous_manifest=baseline)

    def test_cli_preview_and_apply_report_exact_status(self):
        dictionary, bindings = self.root / 'dictionary.json', self.root / 'bindings.json'
        dictionary.write_text(json.dumps(self.dictionary))
        bindings.write_text(json.dumps(self.bindings))
        report = self.root / 'preview.json'
        args = [sys.executable, str(SKILL / 'scripts/generate_dbt_docs_yml.py'), '--project', str(self.project),
                '--dictionary', str(dictionary), '--bindings', str(bindings), '--report', str(report)]
        process = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        preview = json.loads(report.read_text())
        args[-1] = str(self.root / 'apply.json')
        process = subprocess.run(args + ['--apply', '--output', str(self.root / 'candidate'),
                      '--reviewed-preview-sha256', preview['preview_sha256']], capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertTrue((self.root / 'candidate' / MANIFEST_NAME).is_file())


if __name__ == '__main__':
    unittest.main()
