"""Independent synthetic expectations for supplied dbt source, never dbt execution."""
import builtins
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
from source_adapters.dbt import CAPABILITY, SUPPORTED_MANIFEST_SCHEMAS, parse
from source_adapters.registry import validate

HAS_YAML = importlib.util.find_spec('yaml') is not None
HAS_SQL = importlib.util.find_spec('sqlglot') is not None
SCHEMA = 'https://schemas.getdbt.com/dbt/manifest/v12.json'
RAW = "{{ config(materialized='incremental') }}\r\nselect * from {{ ref('pkg', 'orders', version=1) }}\n"


def node(kind='model', package='shop', name='orders', **updates):
    value = {'resource_type': kind, 'package_name': package, 'name': name,
             'unique_id': kind + '.' + package + '.' + name,
             'original_file_path': 'models/' + name + '.sql', 'raw_code': RAW,
             'checksum': {'name': 'sha256', 'checksum': hashlib.sha256(RAW.encode()).hexdigest()},
             'config': {'materialized': 'incremental', 'unique_key': 'id'},
             'depends_on': {'nodes': [], 'macros': []}}
    value.update(updates)
    return value


def manifest(**updates):
    value = {'metadata': {'dbt_schema_version': SCHEMA, 'dbt_version': '1.10.0',
                         'adapter_type': 'snowflake', 'invocation_id': 'synthetic-invocation',
                         'generated_at': '2026-10-15T00:00:00Z'},
             'nodes': {}, 'sources': {}, 'macros': {}, 'exposures': {}, 'disabled': {}}
    value.update(updates)
    return value


def checked(files):
    result = parse(files)
    validate(result, files)
    return result


def exported(value):
    return checked({'repo/target/manifest.json': json.dumps(value)})


def codes(result):
    return {g['code'] for g in result['gaps']}


class ManifestTests(unittest.TestCase):
    def test_capability_is_versioned_and_offline(self):
        self.assertEqual(CAPABILITY['acquisition'], 'supplied_exports')
        self.assertEqual(SUPPORTED_MANIFEST_SCHEMAS, (SCHEMA,))

    def test_native_resources_ids_namespaces_dependencies_and_exact_bytes(self):
        model = node(depends_on={'nodes': ['source.shop.raw.orders', 'model.pkg.orders.v1'],
                                 'macros': ['macro.pkg.helper']},
                     compiled_code='select * from "WAREHOUSE"."RAW"."ORDERS"',
                     refs=[{'package': 'pkg', 'name': 'orders', 'version': 1}],
                     config={'materialized': 'incremental', 'incremental_strategy': 'merge',
                             'unique_key': ['id'], 'on_schema_change': 'fail', 'contract': {'enforced': True},
                             'grants': {'select': ['analyst']}, 'post-hook': [{'sql': 'grant select on {{ this }} to role reader', 'transaction': False}]},
                     access='private', group='finance', columns={'id': {'name': 'id', 'data_type': 'NUMBER',
                         'constraints': [{'type': 'primary_key'}], 'meta': {'policy_tags': ['restricted']}}})
        upstream = node(package='pkg', name='orders', unique_id='model.pkg.orders.v1', version=1)
        source = node('source', name='orders', unique_id='source.shop.raw.orders', raw_code=None,
                      source_name='raw', database='WAREHOUSE', schema='RAW', identifier='Orders',
                      loaded_at_field='loaded_at', freshness={'warn_after': {'count': 12, 'period': 'hour'}})
        macro = node('macro', package='pkg', name='helper', raw_code=None,
                     macro_sql='{% macro helper() %}{{ run_query("select 1") }}{% endmacro %}')
        exposure = node('exposure', name='dashboard', raw_code=None,
                        depends_on={'nodes': ['model.shop.orders']}, owner={'name': 'Team'}, type='dashboard')
        test = node('test', name='unique_orders_id.123', test_metadata={'name': 'unique', 'kwargs': {'column_name': 'id'}},
                    depends_on={'nodes': ['model.shop.orders'], 'macros': []})
        value = manifest(nodes={v['unique_id']: v for v in (model, upstream, test)},
                         sources={source['unique_id']: source}, macros={macro['unique_id']: macro},
                         exposures={exposure['unique_id']: exposure})
        text = json.dumps(value, indent=2) + '\n'
        result = checked({'repo/nested/manifest.json': text})
        objects = {o['native_id']: o for o in result['objects'] if o['native_id']}
        self.assertEqual(set(objects), {'model.shop.orders', 'model.pkg.orders.v1', 'source.shop.raw.orders',
                                        'macro.pkg.helper', 'exposure.shop.dashboard', 'test.shop.unique_orders_id.123'})
        self.assertEqual(objects['model.shop.orders']['details']['raw_metadata']['config'], model['config'])
        self.assertEqual(objects['source.shop.raw.orders']['details']['raw_metadata']['identifier'], 'Orders')
        edges = [d for d in result['dependencies'] if d['source_id'] == objects['model.shop.orders']['id']]
        self.assertEqual({d['target'] for d in edges}, {'source.shop.raw.orders', 'model.pkg.orders.v1', 'macro.pkg.helper'})
        self.assertTrue(all(d['details']['resolution'] == 'supplied_manifest_id' for d in edges))
        self.assertEqual(next(e['text'] for e in result['expressions'] if e['details']['interpretation'] == 'supplied_raw_code'), RAW)
        self.assertIn(text, [e['text'] for e in result['expressions']])
        self.assertIn(macro['macro_sql'], [e['text'] for e in result['expressions']])
        self.assertIn(model['compiled_code'], [e['text'] for e in result['expressions']])
        self.assertIn('dbt.compiled_revision_unverified', codes(result))
        self.assertIn('dbt.effective_security_unverified', codes(result))
        self.assertEqual(objects['model.shop.orders']['evidence']['sha256'], hashlib.sha256(text.encode()).hexdigest())
        self.assertFalse(result['execution_performed'])
        self.assertEqual(result['native_validation'], 'not_run')
        self.assertEqual(result['export_completeness'], 'not_established')

    def test_disabled_is_real_v12_map_of_lists_and_not_active_binding(self):
        active = node(depends_on={'nodes': ['model.shop.hidden'], 'macros': []})
        disabled = node(name='hidden', config={'enabled': False})
        value = manifest(nodes={active['unique_id']: active}, disabled={disabled['unique_id']: [disabled, disabled]})
        result = exported(value)
        hidden = [o for o in result['objects'] if o['native_id'] == 'model.shop.hidden']
        self.assertEqual(len(hidden), 2)
        self.assertTrue(all(o['details']['disabled'] for o in hidden))
        self.assertEqual(result['dependencies'][0]['details']['resolution'], 'unresolved')
        self.assertIn('dbt.dependency_unresolved', codes(result))

    def test_new_unknown_and_spoofed_schema_versions_do_not_extract_resources(self):
        for uri in ('https://schemas.getdbt.com/dbt/manifest/v13.json', 'http://schemas.getdbt.com/dbt/manifest/v12.json',
                    'https://attacker.invalid/dbt/manifest/v12.json', None, ['v12']):
            with self.subTest(uri=uri):
                value = manifest(metadata={'dbt_schema_version': uri}, nodes={'model.shop.orders': node()})
                result = exported(value)
                self.assertFalse(result['objects'])
                self.assertIn('dbt.unsupported_manifest_version', codes(result))

    def test_identity_mismatch_and_malformed_collections_cannot_become_nodes(self):
        result = exported(manifest(nodes={'model.other.orders': node()}, sources=[], macros={'bad': None}, disabled=[]))
        self.assertFalse([o for o in result['objects'] if o['native_id']])
        self.assertTrue({'dbt.invalid_native_identity', 'dbt.invalid_collection', 'dbt.invalid_resource',
                         'dbt.invalid_disabled'} <= codes(result))

    def test_invalid_dependencies_are_not_coerced_and_absent_ids_stay_unresolved(self):
        row = node(depends_on={'nodes': ['model.other.absent'], 'macros': 'macro.other.not_array'})
        result = exported(manifest(nodes={row['unique_id']: row}))
        self.assertEqual([d['target'] for d in result['dependencies']], ['model.other.absent'])
        self.assertIn('dbt.invalid_dependencies', codes(result))
        self.assertIn('dbt.dependency_unresolved', codes(result))

    def test_missing_dependencies_and_malformed_config_are_explicit_gaps(self):
        row = node(config='not a mapping')
        row.pop('depends_on')
        result = exported(manifest(nodes={row['unique_id']: row}))
        self.assertTrue({'dbt.invalid_config', 'dbt.missing_dependencies'} <= codes(result))
        self.assertFalse(result['dependencies'])

    def test_empty_manifest_cannot_establish_project_scope(self):
        result = exported(manifest())
        self.assertIn('dbt.empty_manifest_scope', codes(result))

    def test_malformed_json_duplicate_keys_and_opaque_artifacts_are_gaps(self):
        for text in ('{', '{"metadata":{},"metadata":{}}', '{"metadata": NaN}',
                     '{"results":[]}', '[]'):
            with self.subTest(text=text):
                result = checked({'manifest.json': text})
                self.assertFalse(result['objects'])
                self.assertEqual(result['source_files'][0]['status'], 'partial')
                self.assertTrue(result['gaps'])

    def test_unknown_compiled_dialect_is_not_snowflake_by_filename(self):
        value = manifest(nodes={'model.shop.orders': node(compiled_code='select 1')})
        value['metadata'].pop('adapter_type')
        result = checked({'snowflake/manifest.json': json.dumps(value)})
        compiled = next(e for e in result['expressions'] if e['details']['interpretation'] == 'supplied_compiled_code')
        self.assertEqual(compiled['language'], 'sql:unknown')
        self.assertIn('dbt.dialect_unknown', codes(result))


@unittest.skipUnless(HAS_YAML, 'Pinned PyYAML required for YAML structural tests')
class YamlAndBindingTests(unittest.TestCase):
    def test_omitted_optional_versions_are_supported_but_yaml_extension_is_not_native(self):
        result = checked({'dbt_project.yml': 'name: shop\n', 'models/properties.yml': 'models: [{name: orders}]\n',
                          'models/properties.yaml': 'version: 2\nmodels: [{name: not_native}]\n'})
        self.assertTrue(any(o['kind'] == 'dbt_project' for o in result['objects']))
        self.assertTrue(any(o['name'] == 'orders' for o in result['objects']))
        self.assertFalse(any(o['name'] == 'not_native' for o in result['objects']))
        self.assertIn('dbt.yaml_extension_unsupported', codes(result))

    def test_unknown_or_quoted_yaml_versions_are_not_inferred(self):
        for version in ('3', '"2"', 'true', 'null'):
            result = checked({'dbt_project.yml': 'name: shop\nconfig-version: ' + version,
                              'models/p.yml': 'version: ' + version + '\nmodels: [{name: x}]'})
            self.assertFalse(result['objects'])
            self.assertTrue({'dbt.unsupported_project', 'dbt.unsupported_yaml'} <= codes(result))

    def test_project_properties_packages_preserve_configuration_security_and_tests(self):
        files = {'nested/dbt_project.yml': "name: shop\nconfig-version: 2\nmodel-paths: [warehouse/models]\nmodels:\n  shop:\n    +materialized: incremental\n    +grants: {select: [reader]}\non-run-start: [\"{{ log('inert', info=True) }}\"]\n",
                 'nested/warehouse/schema.yml': "version: 2\nmodels:\n  - name: orders\n    latest_version: 2\n    versions: [{v: 1}, {v: 2}]\n    columns:\n      - name: id\n        data_tests: [unique, not_null]\n    config:\n      access: private\nsources:\n  - name: raw\n    database: RAW\n    schema: ingest\n    tables: [{name: orders, identifier: 'Orders'}]\n",
                 'nested/packages.yml': "packages:\n  - git: https://example.invalid/package.git\n    revision: exact-sha\n  - local: ../shared\n",
                 'nested/dependencies.yml': 'projects:\n  - name: upstream_project\n'}
        result = checked(files)
        project = next(o for o in result['objects'] if o['kind'] == 'dbt_project')
        self.assertEqual(project['details']['raw_metadata']['model-paths'], ['warehouse/models'])
        model = next(o for o in result['objects'] if o['kind'] == 'dbt_models_declaration')
        self.assertEqual(model['details']['raw_metadata']['columns'][0]['data_tests'], ['unique', 'not_null'])
        self.assertIsNone(model['native_id'])
        table = next(o for o in result['objects'] if o['kind'] == 'dbt_source_table_declaration')
        self.assertEqual(table['details']['raw_metadata']['identifier'], 'Orders')
        self.assertEqual(len([o for o in result['objects'] if o['kind'] == 'dbt_package_declaration']), 3)
        self.assertTrue({'dbt.package_resolution_unverified', 'dbt.effective_security_unverified',
                         'dbt.hook_behavior_unverified', 'dbt.property_binding_unverified'} <= codes(result))
        self.assertFalse(result['dependencies'])
        for path, original in files.items():
            self.assertIn(original, [e['text'] for e in result['expressions'] if e['evidence']['path'] == path])

    @unittest.skipUnless(HAS_SQL, 'Pinned SQLGlot required')
    def test_dialect_requires_exact_package_path_and_raw_bytes(self):
        raw = 'select ID from RAW.SALES.ORDERS\r\n'
        row = node(raw_code=raw, checksum={'name': 'sha256', 'checksum': hashlib.sha256(raw.encode()).hexdigest()})
        files = {'repo/dbt_project.yml': 'name: shop\nconfig-version: 2\n',
                 'repo/models/orders.sql': raw, 'exports/manifest.json': json.dumps(manifest(nodes={row['unique_id']: row}))}
        result = checked(files)
        expression = next(e for e in result['expressions'] if e['evidence']['path'] == 'repo/models/orders.sql')
        self.assertEqual(expression['language'], 'snowflake')
        self.assertEqual(expression['text'], raw)
        self.assertTrue(any(d['target'] == 'RAW.SALES.ORDERS' for d in result['dependencies']))
        files['repo/models/orders.sql'] = raw.replace('\r\n', '\n')
        changed = checked(files)
        expr = next(e for e in changed['expressions'] if e['evidence']['path'] == 'repo/models/orders.sql')
        self.assertEqual(expr['language'], 'sql:unknown')
        self.assertIn('dbt.authored_code_mismatch', codes(changed))
        self.assertFalse(changed['dependencies'])

    def test_same_named_models_in_different_packages_do_not_bind(self):
        row = node(package='other')
        result = checked({'repo/dbt_project.yml': 'name: shop\nconfig-version: 2\n',
                          'repo/models/orders.sql': RAW, 'manifest.json': json.dumps(manifest(nodes={row['unique_id']: row}))})
        authored = next(o for o in result['objects'] if o['kind'] == 'dbt_authored_file')
        self.assertIsNone(authored['details']['manifest_binding'])

    def test_multiple_manifests_do_not_select_current_by_file_order(self):
        row = node()
        text = json.dumps(manifest(nodes={row['unique_id']: row}))
        result = checked({'repo/dbt_project.yml': 'name: shop\nconfig-version: 2\n', 'repo/models/orders.sql': RAW,
                          'old/manifest.json': text, 'new/manifest.json': text})
        self.assertIn('dbt.ambiguous_manifest_binding', codes(result))

    def test_invalid_checksum_and_unsafe_original_path_cannot_bind(self):
        for update, expected in (({'checksum': {'name': 'sha256', 'checksum': 'bad'}}, 'dbt.checksum_mismatch'),
                                 ({'original_file_path': '../models/orders.sql'}, 'dbt.invalid_original_path')):
            row = node(**update)
            result = checked({'repo/dbt_project.yml': 'name: shop\nconfig-version: 2\n', 'repo/models/orders.sql': RAW,
                              'manifest.json': json.dumps(manifest(nodes={row['unique_id']: row}))})
            self.assertIn(expected, codes(result))
            authored = next(o for o in result['objects'] if o['kind'] == 'dbt_authored_file')
            self.assertIsNone(authored['details']['manifest_binding'])

    def test_yaml_aliases_duplicate_keys_and_executable_tags_are_rejected(self):
        for text in ('name: shop\nname: other\nconfig-version: 2\n', 'name: &x shop\nother: *x',
                     '!!python/object/apply:os.system ["touch /tmp/dbt-must-not-run"]', '[unclosed'):
            result = checked({'dbt_project.yml': text})
            self.assertIn('dbt.invalid_yaml', codes(result))
            self.assertFalse(result['objects'])


class PreservationAndSafetyTests(unittest.TestCase):
    def test_no_regex_ref_hallucination_or_dynamic_execution(self):
        text = "-- {{ ref('comment_only') }}\n{% for n in var('names') %} select * from {{ ref(n) }} {% endfor %}\n{{ run_query('DROP TABLE important') }}"
        with patch('subprocess.run', side_effect=AssertionError('must not run')), patch('os.system', side_effect=AssertionError('must not run')):
            result = checked({'deep/models/inert.sql': text, 'models/python.py': 'raise RuntimeError("must not execute")'})
        self.assertFalse(result['dependencies'])
        self.assertIn(text, [e['text'] for e in result['expressions']])
        self.assertTrue({'dbt.jinja_unrendered', 'dbt.python_unexecuted'} <= codes(result))

    def test_seed_rows_and_profile_credentials_are_not_copied_into_report(self):
        csv = 'id,email\n1,secret@example.invalid\n'
        result = checked({'repo/seeds/a.csv': csv, 'profiles.yml': 'password: do-not-copy-secret\n',
                          'partial_parse.msgpack': 'opaque'})
        serialized = json.dumps(result)
        self.assertNotIn('secret@example.invalid', serialized)
        self.assertNotIn('do-not-copy-secret', serialized)
        self.assertEqual(result['source_files'][2]['sha256'], hashlib.sha256(csv.encode()).hexdigest())
        self.assertIn('dbt.seed_data_uninterpreted', codes(result))
        self.assertIn('dbt.profiles_unsupported', codes(result))

    def test_missing_optional_dependencies_retain_bytes_with_gap(self):
        original_import = builtins.__import__
        def without_optional(name, *args, **kwargs):
            if name.split('.')[0] in {'yaml', 'sqlglot', 'dbt', 'jinja2'}:
                raise ImportError('not available')
            return original_import(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=without_optional):
            result = checked({'dbt_project.yml': 'name: shop\nconfig-version: 2\n', 'model.sql': 'select 1'})
        self.assertIn('dbt.yaml_dependency_missing', codes(result))
        self.assertIn('sql.dialect_unknown', codes(result))
        self.assertEqual(len(result['expressions']), 2)

    def test_unsupported_and_empty_inputs_remain_honest(self):
        for files in ({}, {'unknown.zip': 'archive'}):
            result = checked(files)
            self.assertEqual(result['native_validation'], 'not_run')
            self.assertEqual(result['export_completeness'], 'not_established')
            self.assertFalse(result['execution_performed'])
            self.assertTrue(all(f['status'] != 'parsed' for f in result['source_files']))


if __name__ == '__main__':
    unittest.main()
