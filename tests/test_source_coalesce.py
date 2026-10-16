"""Independent expectations for the native Git contract, using synthetic metadata."""
import builtins
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
from source_adapters.coalesce import CAPABILITY, parse
from source_adapters.registry import parse as registry_parse, validate


def node(identity='source-id', name='ORDERS', location='RAW', column='source-column'):
    return {'fileVersion': 1, 'id': identity, 'name': name, 'type': 'Node', 'operation': {
        'name': name, 'version': 1, 'type': 'sourceInput', 'sqlType': 'Source',
        'locationName': location, 'database': '', 'schema': '', 'deployEnabled': True,
        'metadata': {'columns': [{'name': 'ORDER_ID', 'dataType': 'NUMBER(38,0)',
            'nullable': False, 'primaryKey': True, 'description': 'Declared order key',
            'columnReference': {'columnCounter': column, 'stepCounter': identity},
            'sourceColumnReferences': [{'columnReferences': [], 'transform': ''}]}]}}}


def files_for(*rows):
    # JSON syntax is valid YAML; serialization is not the oracle for extraction.
    return {'nested/project/nodes/%s.yml' % row['id']: json.dumps(row) for row in rows}


def checked(files):
    result = parse(files)
    validate(result, files)
    return result


def codes(result):
    return {gap['code'] for gap in result['gaps']}


@unittest.skipUnless(importlib.util.find_spec('yaml'), 'Pinned PyYAML dependency required')
class CoalesceGitTests(unittest.TestCase):
    def test_native_identity_nested_path_original_expression_and_hash(self):
        row = node()
        row['operation']['config'] = {'preSQL': "  SELECT 'unchanged';\n"}
        files = files_for(row)
        result = registry_parse('coalesce', files)
        asset = next(o for o in result['objects'] if o['kind'] == 'coalesce_node')
        column = next(o for o in result['objects'] if o['kind'] == 'coalesce_column')
        self.assertEqual(asset['native_id'], 'source-id')
        self.assertEqual(asset['details']['project_scope'], 'nested/project')
        self.assertEqual(asset['details']['raw_metadata'], row)
        self.assertEqual(column['native_id'], 'source-column')
        self.assertEqual(column['details']['node_id'], 'source-id')
        self.assertEqual(column['details']['raw_metadata']['dataType'], 'NUMBER(38,0)')
        self.assertFalse(column['details']['raw_metadata']['nullable'])
        expression = next(e for e in result['expressions'] if e['text'] == "  SELECT 'unchanged';\n")
        self.assertEqual(expression['evidence']['locator'], '$["operation"]["config"]["preSQL"]')
        self.assertEqual(expression['evidence']['sha256'], hashlib.sha256(next(iter(files.values())).encode()).hexdigest())
        self.assertEqual(len(result['component_sha256']), 64)
        self.assertEqual(CAPABILITY['acquisition'], 'supplied_exports')
        self.assertFalse(result['execution_performed'])
        self.assertEqual(result['native_validation'], 'not_run')
        self.assertEqual(result['export_completeness'], 'not_established')

    def test_column_node_alias_and_named_dependencies_are_independently_bound(self):
        source, target = node(), node('target-id', 'STG_ORDERS', 'WORK', 'target-column')
        target['operation']['type'] = 'sql'
        target['operation']['sqlType'] = 'Stage'
        metadata = target['operation']['metadata']
        metadata['columns'][0]['sourceColumnReferences'] = [{'columnReferences': [
            {'stepCounter': 'source-id', 'columnCounter': 'source-column'}], 'transform': '"ORDERS"."ORDER_ID" + 1'}]
        metadata['sourceMapping'] = [{'name': 'STG_ORDERS', 'aliases': {'ORDERS': 'source-id'},
            'dependencies': [{'locationName': 'RAW', 'nodeName': 'ORDERS'}], 'noLinkRefs': [],
            'customSQL': {'customSQL': 'SELECT "ORDER_ID" FROM "ORDERS"'},
            'join': {'joinCondition': 'FROM {{ ref("RAW", "ORDERS") }} "ORDERS"'}}]
        files = files_for(source, target)
        files['nested/project/nodeTypes/Stage-Stage/definition.yml'] = json.dumps({
            'fileVersion': 1, 'type': 'NodeType', 'id': 'Stage', 'name': 'Stage',
            'metadata': {'nodeMetadataSpec': 'capitalized: Stage\n'}})
        result = checked(files)
        deps = {d['details']['kind']: d for d in result['dependencies'] if d['details']['kind'] != 'node_type_reference'}
        for kind in ('column_reference', 'mapping_alias', 'declared_dependency'):
            self.assertEqual(deps[kind]['details']['resolution'], 'bound_in_supplied_project')
        self.assertEqual(deps['column_reference']['target'], 'source-column')
        self.assertEqual(deps['column_reference']['details']['node_id'], 'source-id')
        self.assertEqual(deps['column_reference']['details']['source_mapping_index'], 0)
        self.assertEqual(deps['declared_dependency']['details']['location_name'], 'RAW')
        stage = next(d for d in result['dependencies'] if d['target'] == 'Stage')
        self.assertEqual(stage['details']['resolution'], 'bound_in_supplied_project')
        self.assertIn('coalesce.template_context_unresolved', codes(result))
        self.assertTrue(any(e['text'] == '"ORDERS"."ORDER_ID" + 1' for e in result['expressions']))
        transform = next(e for e in result['expressions'] if e['text'] == '"ORDERS"."ORDER_ID" + 1')
        self.assertEqual(transform['object_id'], deps['column_reference']['source_id'])
        self.assertEqual(transform['evidence']['locator'], '$["operation"]["metadata"]["columns"][0]["sourceColumnReferences"][0]["transform"]')
        for text in ('FROM {{ ref("RAW", "ORDERS") }} "ORDERS"', 'SELECT "ORDER_ID" FROM "ORDERS"'):
            expression = next(e for e in result['expressions'] if e['text'] == text)
            self.assertEqual(expression['object_id'], deps['declared_dependency']['source_id'])
        self.assertTrue(all(e['object_id'] is None for e in result['expressions'] if e['evidence']['locator'] == '$raw'))

    def test_invalid_mapping_names_have_explicit_unbound_labels(self):
        for name in ('', '  ', None, 17, {}, []):
            with self.subTest(name=name):
                row = node()
                row['operation']['metadata']['sourceMapping'] = [{'name': name}]
                result = checked(files_for(row))
                mapping = next(o for o in result['objects'] if o['kind'] == 'coalesce_source_mapping')
                self.assertEqual(mapping['name'], 'Unbound source mapping [0]')
                self.assertEqual(mapping['details']['native_name'], name)
                self.assertEqual(mapping['details']['name_binding'], 'unresolved')
                self.assertEqual(mapping['details']['raw_metadata']['name'], name)
                self.assertIn('coalesce.invalid_mapping_name', codes(result))
        result = checked({'p/environments/env.yml': json.dumps({'fileVersion': 1, 'id': 'env',
            'name': 'Environment', 'type': 'Environment', 'mappingDefinitions': {
                '': {'database': 'DB', 'schema': 'S'}, '  ': {'database': 'DB', 'schema': 'S'}}})})
        mappings = [o for o in result['objects'] if o['kind'] == 'coalesce_storage_mapping']
        self.assertEqual([o['name'] for o in mappings], ['Unbound storage mapping [0]', 'Unbound storage mapping [1]'])
        self.assertEqual([o['details']['native_location'] for o in mappings], ['', '  '])
        self.assertTrue(all(o['details']['name_binding'] == 'unresolved' for o in mappings))
        self.assertIn('coalesce.invalid_storage_location_name', codes(result))

    def test_coordinator_retains_declared_inputs_for_each_expression_owner(self):
        from plan_specialists import plan_repository
        from extract_specialist_task import extract
        from verify_specialist_results import verify
        source, target = node(), node('target', 'STG_ORDERS', 'WORK', 'target-col')
        transform = '"ORDERS"."ORDER_ID" + 1'
        join = 'FROM {{ ref("RAW", "ORDERS") }}'
        custom = 'SELECT "ORDER_ID" FROM "ORDERS"'
        target['operation']['metadata']['sourceMapping'] = [{'name': '', 'aliases': {'src': 'source-id'},
            'dependencies': [{'locationName': 'RAW', 'nodeName': 'ORDERS'}],
            'join': {'joinCondition': join}, 'customSQL': {'customSQL': custom}}]
        target['operation']['metadata']['columns'][0]['sourceColumnReferences'] = [{
            'columnReferences': [{'stepCounter': 'source-id', 'columnCounter': 'source-column'}], 'transform': transform}]
        files = files_for(source, target)
        files['nested/project/data.yml'] = 'fileVersion: 3\ndefaultStorageMapping: RAW\n'
        files['nested/project/environments/env.yml'] = json.dumps({'fileVersion': 1, 'type': 'Environment',
            'id': 'env', 'name': 'Env', 'mappingDefinitions': {'': {'database': 'DB', 'schema': 'SCHEMA'}}})
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).resolve()
            root, run = base / 'source', base / 'plan'
            for path, text in files.items():
                destination = root / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(text)
            plan = plan_repository(root, run, inspect_git=False, require_source_adapters=True)
            self.assertEqual(len(plan['tasks']), 1)
            task = plan['tasks'][0]
            result = extract(run / 'dispatch-plan.json', task['task_id'])
            (run / 'results').mkdir(exist_ok=True)
            (run / task['result_path']).write_text(json.dumps(result))
            self.assertEqual(verify(run / 'dispatch-plan.json')['errors'], [])
        rules = {r['expression']: r for r in result['rules']}
        self.assertEqual(rules[transform]['input_refs'], [{'reference': 'source-column', 'status': 'unresolved'}])
        expected_refs = [{'reference': '["RAW", "ORDERS"]', 'status': 'unresolved'},
                         {'reference': 'source-id', 'status': 'unresolved'}]
        self.assertEqual(rules[join]['input_refs'], expected_refs)
        self.assertEqual(rules[custom]['input_refs'], expected_refs)
        self.assertNotEqual(rules[transform]['output_object_id'], rules[join]['output_object_id'])
        self.assertTrue(all(o['name'].strip() for o in result['objects']))

    def test_project_scopes_prevent_cross_repo_binding_and_short_name_fallback(self):
        target = node('target', 'TARGET', 'WORK', 'target-col')
        target['operation']['metadata']['sourceMapping'] = [{'dependencies': [
            {'locationName': 'RAW', 'nodeName': 'ORDERS'}], 'aliases': {'x': 'source-id'}}]
        files = {'project_a/nodes/source.yml': json.dumps(node()),
                 'project_b/nodes/target.yml': json.dumps(target)}
        result = checked(files)
        self.assertTrue(all(d['details']['resolution'] == 'unresolved' for d in result['dependencies']))
        self.assertIn('coalesce.dependency_unresolved', codes(result))

    def test_duplicate_native_identity_keeps_both_and_does_not_select_one(self):
        target = node('target', 'TARGET', 'WORK', 'target-col')
        target['operation']['metadata']['sourceMapping'] = [{'aliases': {'x': 'source-id'}}]
        files = files_for(node(), target)
        files['nested/project/nodes/duplicate.yml'] = json.dumps(node())
        result = checked(files)
        alias = next(d for d in result['dependencies'] if d['details']['kind'] == 'mapping_alias')
        self.assertEqual(alias['details']['resolution'], 'unresolved')
        self.assertIn('coalesce.duplicate_native_identity', codes(result))
        self.assertEqual(len([o for o in result['objects'] if o['native_id'] == 'source-id']), 2)

    def test_conflicting_node_names_do_not_bind_by_name_and_hash_lineage_is_unmodeled(self):
        source, target = node(), node('target', 'TARGET', 'WORK', 'target-col')
        source['operation']['name'] = 'OTHER_NAME'
        source['operation']['metadata']['columns'][0]['hashDetails'] = {
            'hashedColumns': [{'stepCounter': 'hash-source', 'columnCounter': 'hash-input'}]}
        target['operation']['metadata']['sourceMapping'] = [{'dependencies': [
            {'locationName': 'RAW', 'nodeName': 'ORDERS'}]}]
        result = checked(files_for(source, target))
        named = next(d for d in result['dependencies'] if d['details']['kind'] == 'declared_dependency')
        self.assertEqual(named['details']['resolution'], 'unresolved')
        self.assertTrue({'coalesce.node_name_mismatch', 'coalesce.hash_lineage_unmodeled'} <= codes(result))

    def test_native_project_locations_and_environment_mapping_are_distinct(self):
        files = {'nested/p/data.yml': 'fileVersion: 3\ndefaultStorageMapping: RAW\n',
                 'nested/p/locations.yml': 'fileVersion: 1\ndefaultStorageMapping: RAW\nlocations: [RAW, WORK]\n',
                 'nested/p/environments/prod.yml': json.dumps({'fileVersion': 1, 'type': 'Environment',
                     'id': 'env-9', 'name': 'Production', 'mappingDefinitions': {
                         'RAW': {'database': 'Warehouse.One', 'schema': 'Landing'},
                         'WORK': {'database': 'WH', 'schema': 'silver'}}})}
        result = checked(files)
        mapping = next(o for o in result['objects'] if o['kind'] == 'coalesce_storage_mapping')
        self.assertEqual(mapping['details']['raw_metadata'], {'database': 'Warehouse.One', 'schema': 'Landing'})
        self.assertEqual(mapping['details']['environment_id'], 'env-9')
        self.assertEqual(mapping['details']['physical_binding'], 'not_verified')
        self.assertEqual(result['dependencies'], [])
        self.assertIn('coalesce.environment_security_unverified', codes(result))

    def test_security_custom_config_and_sql_are_evidence_not_enforcement(self):
        row = node()
        row['operation']['config'] = {'grants': {'SELECT': ['ANALYST']},
            'masking_policy': 'GOV.MASK_EMAIL', 'preSQL': 'GRANT SELECT ON T TO ROLE R',
            'futureOption': {'enabled': True}}
        result = checked(files_for(row))
        declarations = {o['name']: o for o in result['objects'] if o['kind'] == 'coalesce_security_declaration'}
        self.assertEqual(declarations['masking_policy']['details']['declaration'], 'GOV.MASK_EMAIL')
        self.assertEqual(declarations['grants']['details']['enforcement'], 'not_verified')
        self.assertTrue({'coalesce.effective_security_unverified', 'coalesce.security_sql_unverified',
                         'coalesce.runtime_unverified'} <= codes(result))
        self.assertFalse(result['execution_performed'])

    def test_no_link_refs_remain_separate_from_execution_dependency(self):
        row = node()
        row['operation']['metadata']['sourceMapping'] = [{'noLinkRefs': [
            {'locationName': 'ARCHIVE', 'nodeName': 'OLD_ORDERS'}]}]
        result = checked(files_for(row))
        dep = next(d for d in result['dependencies'] if d['details']['kind'] == 'no_link_reference')
        self.assertEqual(dep['details']['resolution'], 'unresolved')
        self.assertIn('coalesce.no_link_runtime_unverified', codes(result))

    def test_unknown_versions_and_invented_envelopes_have_no_interpreted_objects(self):
        base = node()
        cases = [dict(base, fileVersion=99), dict(base, fileVersion=True),
                 dict(base, operation=dict(base['operation'], version=2)),
                 {'nodes': [base], 'version': 1}, {'steps': {base['id']: base}, 'fileVersion': 1}]
        for row in cases:
            with self.subTest(row=row):
                result = checked({'nested/nodes/input.yml': json.dumps(row)})
                self.assertEqual(result['objects'], [])
                self.assertEqual(result['source_files'][0]['status'], 'unsupported')
                self.assertEqual(result['expressions'][0]['text'], json.dumps(row))

    def test_malformed_shapes_unknown_fields_and_misaligned_mappings(self):
        row = node()
        metadata = row['operation']['metadata']
        metadata['columns'][0]['columnReference']['stepCounter'] = 'wrong-owner'
        metadata['columns'][0]['nullable'] = 'false'
        metadata['columns'][0]['futureColumnFeature'] = 8
        metadata['columns'][0]['sourceColumnReferences'] = [{'columnReferences': [None], 'transform': []}]
        metadata['sourceMapping'] = [{'aliases': {'broken': 14}, 'dependencies': [{}]}, None]
        result = checked(files_for(row))
        self.assertTrue({'coalesce.invalid_column_identity', 'coalesce.invalid_column_shape',
            'coalesce.unknown_fields', 'coalesce.mapping_alignment_unresolved', 'coalesce.invalid_column_dependency',
            'coalesce.invalid_source_mapping', 'coalesce.invalid_aliases', 'coalesce.invalid_mapping_dependency',
            'coalesce.invalid_expression'} <= codes(result))
        self.assertFalse(any(d['details']['kind'] == 'column_reference' for d in result['dependencies']))

    def test_yaml_rejects_duplicate_keys_aliases_tags_and_invalid_root(self):
        cases = [('name: one\nname: two', 'source.duplicate_key'),
                 ('x: &anchor [1]\ny: *anchor', 'source.yaml_alias'),
                 ('!!python/object/apply:os.system [echo unsafe]', 'source.invalid_yaml'),
                 ('[1, 2]', 'coalesce.unsupported_yaml_shape'),
                 ('x: [', 'source.invalid_yaml')]
        for content, code in cases:
            with self.subTest(code=code):
                result = checked({'nested/node.yml': content})
                self.assertIn(code, codes(result))
                self.assertEqual(result['source_files'][0]['status'], 'unsupported')

    def test_macros_and_definition_bodies_are_preserved_without_evaluation(self):
        text = '{% macro risky() %}{{ modules.os.system("never") }}{% endmacro %}'
        files = {'p/macros/test.yml': json.dumps({'fileVersion': 1, 'type': 'Macro',
                  'id': 'macro-1', 'name': 'macro', 'macroString': text})}
        result = checked(files)
        self.assertTrue(any(e['text'] == text for e in result['expressions']))
        self.assertIn('coalesce.macro_behavior_unverified', codes(result))
        self.assertEqual(result['dependencies'], [])


class CoalesceBoundaryTests(unittest.TestCase):
    def test_optional_yaml_absence_retains_source_and_imports_no_runtime(self):
        original = builtins.__import__
        def unavailable(name, *args, **kwargs):
            if name == 'yaml':
                raise ImportError('simulated optional dependency absence')
            if name in ('jinja2', 'requests', 'sqlglot'):
                self.fail('Coalesce evidence extraction must not import template/API runtimes')
            return original(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=unavailable):
            result = checked({'nested/nodes/a.yml': 'fileVersion: 1'})
        self.assertIn('coalesce.parser_dependency_missing', codes(result))
        self.assertEqual(result['expressions'][0]['text'], 'fileVersion: 1')
        self.assertEqual(result['objects'], [])

    def test_sql_nodes_and_templates_preserved_without_invented_annotation_identity(self):
        sql = '-- @id("unqualified")\nSELECT * FROM {{ ref("RAW", "ORDERS") }}'
        result = checked({'p/nodes/WORK-ORDERS.sql': sql, 'p/nodeTypes/Stage/create.sql.j2': 'GRANT SELECT ON {{ this }} TO ROLE r'})
        self.assertEqual(result['objects'], [])
        self.assertEqual(result['dependencies'], [])
        self.assertEqual(result['expressions'][0]['text'], 'GRANT SELECT ON {{ this }} TO ROLE r')
        self.assertIn('coalesce.sql_node_or_template_unmodeled', codes(result))
        self.assertIn('coalesce.security_sql_unverified', codes(result))

    def test_api_json_job_and_opaque_files_are_explicitly_outside_slice(self):
        files = {'node.json': json.dumps({'id': 'api-id', 'name': 'T', 'nodeType': 'Stage'}),
                 'malformed.json': '{broken', 'README.txt': 'opaque'}
        result = checked(files)
        self.assertEqual(len(result['source_files']), 3)
        self.assertTrue(all(f['status'] == 'unsupported' for f in result['source_files']))
        self.assertEqual(result['objects'], [])


if __name__ == '__main__':
    unittest.main()
