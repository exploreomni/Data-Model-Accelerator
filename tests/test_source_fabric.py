"""Independent, synthetic native Fabric snapshots: no tenant or SDK required."""
import base64
import builtins
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
from source_adapters.fabric import parse, CAPABILITY
from source_adapters.registry import parse as registry_parse, validate, component_fingerprint

SCHEMA = 'https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json'
ID = '11111111-2222-3333-4444-555555555555'
OTHER_ID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'


def platform(kind='Notebook', identity=ID):
    return json.dumps({'$schema': SCHEMA, 'metadata': {'type': kind, 'displayName': 'Synthetic item'},
                       'config': {'version': '2.0', 'logicalId': identity}})


def envelope(parts, format_name=None):
    value = {'definition': {'parts': [
        {'path': p, 'payloadType': 'InlineBase64', 'payload': base64.b64encode(raw.encode()).decode()}
        for p, raw in parts.items()]}}
    if format_name is not None:
        value['definition']['format'] = format_name
    return json.dumps(value)


def git(parts, root='nested/repo/Item.Notebook'):
    return {root + '/' + p: v for p, v in parts.items()}


def codes(result):
    return {g['code'] for g in result['gaps']}


def checked(files):
    result = parse(files)
    validate(result, files)
    return result


def semantic():
    return {'.platform': platform('SemanticModel'), 'definition.pbism': '{"version":"4.0"}',
            'definition/model.tmdl': 'model Synthetic\n\tref table Orders\n',
            'definition/tables/Orders.tmdl': 'table Orders\n\tcolumn Amount\n\t\tdataType: int64\n\tmeasure Total = SUM(Orders[Amount])\n'}


class FabricAdapterTests(unittest.TestCase):
    def test_dotfile_native_identity_nested_repo_and_raw_code(self):
        raw = '# Fabric notebook source\n# CELL ********************\nraise RuntimeError("do not run")\n'
        files = git({'.platform': platform(), 'notebook-content.py': raw})
        result = registry_parse('fabric', files)
        item = next(o for o in result['objects'] if o['kind'] == 'fabric_item')
        self.assertEqual(item['native_id'], ID)
        self.assertEqual(item['details']['identity_kind'], 'git_logical_id')
        self.assertIsNone(item['details']['service_item_id'])
        expression = result['expressions'][0]
        self.assertEqual(expression['text'], raw)
        self.assertEqual(expression['evidence']['path'], 'nested/repo/Item.Notebook/notebook-content.py')
        self.assertEqual(expression['evidence']['sha256'], hashlib.sha256(raw.encode()).hexdigest())
        self.assertEqual(CAPABILITY['acquisition'], 'supplied_exports')
        self.assertFalse(result['execution_performed'])
        self.assertEqual(result['native_validation'], 'not_run')
        self.assertEqual(result['export_completeness'], 'not_established')
        self.assertEqual(len(result['component_sha256']), 64)

    def test_api_parent_and_decoded_hashes_and_native_locator(self):
        raw = '# Fabric notebook source\r\nprint("synthetic")\r\n'
        original = envelope({'.platform': platform(), 'notebook-content.py': raw}, 'FabricGitSource')
        result = checked({'exports/native.json': original})
        expression = result['expressions'][0]
        self.assertEqual(expression['text'], raw)
        self.assertEqual(expression['evidence']['sha256'], hashlib.sha256(original.encode()).hexdigest())
        self.assertEqual(expression['evidence']['path'], 'exports/native.json')
        self.assertEqual(expression['evidence']['locator'], '$["definition"]["parts"][1]["payload"]::decoded:$source')
        provenance = expression['details']['decoded_provenance']
        self.assertEqual(provenance['part_path'], 'notebook-content.py')
        self.assertEqual(provenance['decoded_sha256'], hashlib.sha256(raw.encode()).hexdigest())
        self.assertEqual(provenance['parent_sha256'], hashlib.sha256(original.encode()).hexdigest())
        self.assertEqual(len(result['source_files']), 1)
        self.assertEqual(result['source_files'][0]['status'], 'partial')
        source = next(o for o in result['objects'] if o['kind'] == 'fabric_source_snapshot')
        self.assertEqual(source['details']['raw_text'], original)

    def test_ipynb_fragments_cell_ids_and_no_execution_claims(self):
        notebook = {'nbformat': 4, 'nbformat_minor': 5, 'metadata': {'language_info': {'name': 'python'}},
                    'cells': [{'id': 'cell-1', 'cell_type': 'code', 'source': ['print(', '"hello")\n'],
                               'execution_count': 9, 'outputs': [{'output_type': 'stream', 'text': 'stale'}]},
                              {'cell_type': 'markdown', 'source': 'some note'}]}
        files = {'export.json': envelope({'.platform': platform(), 'artifact.content.ipynb': json.dumps(notebook)}, 'ipynb')}
        result = checked(files)
        cells = [o for o in result['objects'] if o['kind'] == 'fabric_notebook_cell']
        self.assertEqual(cells[0]['native_id'], 'cell-1')
        self.assertIsNone(cells[1]['native_id'])
        self.assertEqual(result['expressions'][0]['text'], 'print("hello")\n')
        self.assertEqual(result['expressions'][0]['details']['original_fragments'], ['print(', '"hello")\n'])
        self.assertIn('fabric.notebook_runtime_unresolved', codes(result))

    def test_pipeline_control_dependencies_are_distinct_from_service_ids(self):
        pipeline = {'properties': {'activities': [
            {'name': 'Pause', 'type': 'Wait', 'typeProperties': {'waitTimeInSeconds': 1}},
            {'name': 'Run', 'type': 'TridentNotebook', 'typeProperties': {'notebookId': ID, 'workspaceId': OTHER_ID,
              'parameters': {'region': {'type': 'Expression', 'value': '@pipeline().parameters.region'}}},
             'dependsOn': [{'activity': 'Pause', 'dependencyConditions': ['Succeeded']}]}]}}
        result = checked(git({'.platform': platform('DataPipeline'), 'pipeline-content.json': json.dumps(pipeline)}))
        control = next(d for d in result['dependencies'] if d['details']['kind'] == 'activity_control_dependency')
        service = next(d for d in result['dependencies'] if d['details']['kind'] == 'notebook_item_reference')
        self.assertEqual(control['details']['resolution'], 'bound_in_supplied_item')
        self.assertIn(control['details']['target_object_id'], {o['id'] for o in result['objects']})
        self.assertEqual(service['target'], ID)
        self.assertEqual(service['details']['workspace_id'], OTHER_ID)
        self.assertEqual(service['details']['resolution'], 'unresolved')
        self.assertIn('fabric.dynamic_content', codes(result))
        self.assertEqual(result['expressions'][0]['text'], '@pipeline().parameters.region')

    def test_duplicate_and_missing_activity_refs_are_not_bound(self):
        value = {'properties': {'activities': [
            {'name': 'same', 'type': 'Wait', 'typeProperties': {}},
            {'name': 'same', 'type': 'Wait', 'typeProperties': {}},
            {'name': 'consumer', 'type': 'Wait', 'typeProperties': {}, 'dependsOn': [
                {'activity': 'same', 'dependencyConditions': ['Succeeded']},
                {'activity': 'missing', 'dependencyConditions': ['Failed']}]}]}}
        result = checked(git({'.platform': platform('DataPipeline'), 'pipeline-content.json': json.dumps(value)}))
        self.assertTrue(all(d['details']['resolution'] == 'unresolved' for d in result['dependencies']))
        self.assertIn('fabric.duplicate_activity_identity', codes(result))

    def test_lakehouse_shortcuts_roles_and_alm_preserved_without_access_claims(self):
        shortcut = [{'name': 'orders', 'path': '/Tables/dbo', 'target': {'type': 'OneLake',
                     'oneLake': {'workspaceId': OTHER_ID, 'itemId': ID, 'path': 'Tables/dbo/orders'}}}]
        roles = [{'id': OTHER_ID, 'name': 'Readers', 'decisionRules': [{'effect': 'Permit',
                  'constraints': {'rows': [{'tablePath': '/Tables/dbo/orders', 'value': 'region = 7'}]}}]}]
        files = git({'.platform': platform('Lakehouse'), 'lakehouse.metadata.json': '{"defaultSchema":"dbo"}',
                     'shortcuts.metadata.json': json.dumps(shortcut), 'data-access-roles.json': json.dumps(roles),
                     'alm.settings.json': '{"version":"1.0.1","objectTypes":[{"name":"DataAccessRoles","state":"Disabled"}]}'} )
        result = checked(files)
        role = next(o for o in result['objects'] if o['kind'] == 'fabric_data_access_role')
        self.assertEqual(role['native_id'], OTHER_ID)
        self.assertEqual(role['details']['raw_metadata'], roles[0])
        self.assertEqual(role['details']['enforcement'], 'not_verified')
        self.assertEqual(result['dependencies'][0]['details']['resolution'], 'unresolved')
        self.assertIn('fabric.effective_security_unverified', codes(result))

    def test_semantic_model_delegation_preserves_ids_and_double_provenance(self):
        raw = envelope(semantic(), 'TMDL')
        result = checked({'model-definition.json': raw})
        self.assertEqual([o['name'] for o in result['objects'] if o['kind'] == 'table'], ['Orders'])
        self.assertEqual(result['expressions'][0]['text'], 'SUM(Orders[Amount])')
        self.assertTrue(all(o['id'].startswith('fabric:') for o in result['objects']))
        dependency = result['dependencies'][0]
        self.assertIn(dependency['source_id'], {o['id'] for o in result['objects']})
        self.assertIn(dependency['target'], {o['id'] for o in result['objects']})
        self.assertEqual(dependency['evidence']['sha256'], hashlib.sha256(raw.encode()).hexdigest())
        self.assertEqual(dependency['details']['decoded_provenance']['part_path'], 'definition/model.tmdl')
        self.assertIn('bounded_tmdl', codes(result))

    def test_powerbi_component_changes_invalidate_fabric_fingerprint(self):
        first = component_fingerprint('fabric')
        original = Path.read_bytes
        def changed(path):
            return original(path) + (b'\n# fingerprint test' if path.name == 'powerbi.py' else b'')
        with patch.object(Path, 'read_bytes', changed):
            self.assertNotEqual(first, component_fingerprint('fabric'))

    def test_missing_semantic_dependency_is_explicit(self):
        original = builtins.__import__
        def blocked(name, *args, **kwargs):
            if name == 'powerbi':
                raise ImportError('synthetic unavailable dependency')
            return original(name, *args, **kwargs)
        with patch('builtins.__import__', blocked):
            result = checked(git(semantic()))
        self.assertIn('fabric.parser_dependency_missing', codes(result))
        self.assertFalse(any(o['kind'] == 'table' for o in result['objects']))

    def test_unknown_type_version_and_missing_identity_never_interpret_body(self):
        for mutate, expected in [
            (lambda p: p['metadata'].update(type='FutureItem'), 'fabric.unsupported_item_type'),
            (lambda p: p['metadata'].update(type='notebook'), 'fabric.unsupported_item_type'),
            (lambda p: p['config'].update(version='99.0'), 'fabric.unsupported_platform_version'),
            (lambda p: p['config'].pop('logicalId'), 'fabric.missing_item_identity'),
            (lambda p: p.update({'$schema': 'https://untrusted.invalid/schema'}), 'fabric.unsupported_platform_version')]:
            source = json.loads(platform())
            mutate(source)
            result = checked(git({'.platform': json.dumps(source), 'notebook-content.py': 'raise RuntimeError()'}))
            self.assertIn(expected, codes(result))
            self.assertEqual(result['expressions'], [])
        result = checked({'response.json': envelope({'notebook-content.py': 'x'})})
        self.assertIn('fabric.missing_item_identity', codes(result))

    def test_unknown_formats_and_mutually_exclusive_semantic_parts(self):
        for bad in ('FutureFormat', ['ipynb'], {'format': 'ipynb'}):
            raw = json.loads(envelope({'.platform': platform(), 'notebook-content.py': 'x'}))
            raw['definition']['format'] = bad
            result = checked({'x.json': json.dumps(raw)})
            self.assertIn('fabric.unsupported_definition_format', codes(result))
        parts = semantic()
        parts['model.bim'] = '{}'
        result = checked(git(parts))
        self.assertIn('fabric.missing_or_conflicting_semantic_format', codes(result))
        self.assertFalse(any(o['kind'] == 'table' for o in result['objects']))

    def test_malformed_json_and_native_shapes_fail_closed(self):
        for raw in ('{', '{"definition":{},"definition":{}}', 'NaN'):
            self.assertIn('fabric.invalid_json', codes(checked({'bad.json': raw})))
        for value in ({'parts': []}, {'value': []}, {'status': 'Succeeded'}, {'definition': {'parts': []}},
                      {'definition': {'parts': []}, 'itemType': 'Notebook'}):
            result = checked({'x.json': json.dumps(value)})
            self.assertTrue(result['gaps'])
            self.assertFalse(any(o['kind'] == 'fabric_item' for o in result['objects']))
        for raw in ('null', '[]', '{"properties":{"activities":{}}}'):
            result = checked(git({'.platform': platform('DataPipeline'), 'pipeline-content.json': raw}))
            self.assertIn('fabric.malformed_pipeline', codes(result))

    def test_base64_path_traversal_case_unicode_and_directory_collisions(self):
        for path in ('../x.py', '/absolute', 'a/../x', 'a\\x', 'https://example.invalid/file', 'a//b', 'a\x00b'):
            value = json.loads(envelope({'.platform': platform(), 'notebook-content.py': 'x'}))
            value['definition']['parts'][1]['path'] = path
            result = checked({'x.json': json.dumps(value)})
            self.assertIn('fabric.invalid_definition_parts', codes(result))
            self.assertFalse(any(o['kind'] == 'fabric_item' for o in result['objects']))
        for paths in (('a', 'A'), ('café/x', 'cafe\u0301/y'), ('a', 'a/b'), ('same', 'same')):
            value = json.loads(envelope({'.platform': platform()}))
            value['definition']['parts'].extend({'path': p, 'payloadType': 'InlineBase64', 'payload': 'eA=='} for p in paths)
            result = checked({'x.json': json.dumps(value)})
            self.assertIn('fabric.invalid_definition_parts', codes(result))

    def test_invalid_payload_remote_encoding_binary_and_limits(self):
        for replacement in ({'payload': '!!!!'}, {'payload': '/w=='}, {'payloadType': 'Uri', 'payload': 'https://untrusted.invalid'},
                            {'payload': 'eB=='}, {'payload': 'eA'}, {'payload': 2}):
            value = json.loads(envelope({'.platform': platform(), 'notebook-content.py': 'x'}))
            value['definition']['parts'][1].update(replacement)
            result = checked({'x.json': json.dumps(value)})
            self.assertIn('fabric.invalid_definition_parts', codes(result))
        raw = envelope({'.platform': platform(), 'notebook-content.py': 'x'})
        with patch('source_adapters.fabric.MAX_FILES', 1):
            self.assertIn('fabric.invalid_definition_parts', codes(checked({'x.json': raw})))
        with patch('source_adapters.fabric.MAX_TOTAL_BYTES', 8):
            self.assertIn('fabric.invalid_definition_parts', codes(checked({'x.json': raw})))

    def test_original_unsafe_paths_rejected_and_no_runtime_or_remote_fetch(self):
        for files in ({'../x.json': '{}'}, {'a/.platform': '{}', 'A/x': 'x'}, {'a': 'x', 'a/b': 'y'}):
            with self.assertRaises(ValueError):
                parse(files)
        with patch('subprocess.run', side_effect=AssertionError('No subprocess')), patch('urllib.request.urlopen', side_effect=AssertionError('No HTTP')):
            result = checked(git({'.platform': platform(), 'notebook-content.py': 'import os\nos.system("touch /tmp/must-not-exist")'}))
        self.assertFalse(result['execution_performed'])

    def test_legacy_conflicts_unsupported_warehouse_and_unknown_parts_visible(self):
        files = git({'.platform': platform(), 'notebook-content.py': 'x', 'item.config.json': '{}'})
        result = checked(files)
        self.assertIn('fabric.conflicting_system_files', codes(result))
        self.assertEqual(result['expressions'], [])
        result = checked(git({'.platform': platform('Warehouse'), 'dbo/Tables/orders.sql': 'CREATE TABLE orders(id int);'}))
        self.assertIn('fabric.unsupported_item_type', codes(result))
        sql = next(o for o in result['objects'] if o['name'] == 'dbo/Tables/orders.sql')
        self.assertEqual(sql['details']['raw_text'], 'CREATE TABLE orders(id int);')
        self.assertEqual(result['expressions'], [])

    def test_nested_item_ownership_is_nearest_explicit_platform(self):
        files = {'.platform': platform(), 'notebook-content.py': 'print("outer")',
                 'a/.platform': platform('Notebook', OTHER_ID), 'a/notebook-content.py': 'print("inner")'}
        result = checked(files)
        self.assertEqual(len([o for o in result['objects'] if o['kind'] == 'fabric_item']), 2)
        self.assertEqual({e['text'] for e in result['expressions']}, {'print("outer")', 'print("inner")'})
        self.assertNotIn('fabric.missing_or_ambiguous_notebook', codes(result))

    def test_same_named_items_and_repeated_native_ids_keep_separate_provenance(self):
        parts = {'.platform': platform(), 'notebook-content.py': 'x'}
        files = dict(git(parts, 'branch1/Item.Notebook'), **git(parts, 'branch2/Item.Notebook'))
        result = checked(files)
        self.assertEqual(len([o for o in result['objects'] if o['kind'] == 'fabric_item']), 2)
        self.assertEqual(len({e['id'] for e in result['expressions']}), 2)
        self.assertIn('fabric.repeated_logical_identity', codes(result))


if __name__ == '__main__':
    unittest.main()
