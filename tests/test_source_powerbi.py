"""Independent synthetic model fixtures plus compatibility with the existing PBIP case."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

SKILL = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator'
sys.path.insert(0, str(SKILL / 'scripts'))
from source_adapters.powerbi import parse
from source_adapters.registry import validate

OPTIONAL = all(importlib.util.find_spec(x) for x in ('jsonschema', 'referencing', 'sqlglot'))


def model():
    # Invented domain and IDs; metadata shape follows Microsoft's public TMSL docs.
    return {'name': 'Workshop', 'compatibilityLevel': 1600, 'model': {
        'tables': [{'name': 'Tickets', 'lineageTag': 'synthetic-tickets',
                    'columns': [{'name': 'Region', 'dataType': 'string', 'sourceColumn': 'region'},
                                {'name': 'Cost', 'dataType': 'int64', 'sourceColumn': 'cost'}],
                    'measures': [{'name': 'Total cost', 'expression': 'SUM(Tickets[Cost])'}],
                    'partitions': [{'name': 'Ticket feed', 'mode': 'import', 'source': {
                        'type': 'm', 'expression': ['let', '  Source = ExternalConnector("synthetic")', 'in Source']}}]},
                   {'name': 'Regions', 'columns': [{'name': 'Region', 'dataType': 'string', 'sourceColumn': 'region'}]}],
        'relationships': [{'name': 'Region relationship', 'fromTable': 'Tickets', 'fromColumn': 'Region',
                           'toTable': 'Regions', 'toColumn': 'Region', 'isActive': False,
                           'crossFilteringBehavior': 'bothDirections', 'securityFilteringBehavior': 'bothDirections'}],
        'roles': [{'name': 'Regional reader', 'modelPermission': 'read', 'members': [],
                   'tablePermissions': [{'name': 'Tickets', 'filterExpression': 'Tickets[Region] = USERPRINCIPALNAME()',
                                         'columnPermissions': [{'name': 'Cost', 'metadataPermission': 'none'}]}]}],
        'expressions': [{'name': 'Region parameter', 'kind': 'm', 'expression': '"west"'}]}}


class MalformedPartitionTests(unittest.TestCase):
    def test_malformed_relationship_endpoints_remain_unresolved(self):
        for side in ('fromTable', 'toTable', 'fromColumn', 'toColumn'):
            for invalid in ([], {}, True, None, 1, ''):
                value = model()
                value['model']['relationships'][0][side] = invalid
                files = {'Workshop.SemanticModel/model.bim': json.dumps(value)}
                result = parse(files)
                validate(result, files)
                self.assertIn('unresolved_reference', {g['code'] for g in result['gaps']})
                relationship = next(o for o in result['objects'] if o['kind'] == 'relationship')
                self.assertEqual(relationship['details']['native'][side], invalid)

    def test_invalid_native_identity_is_retained_only_as_raw_metadata(self):
        for invalid in ([], {}, [1], {'bad': 1}, True, False, 0, 42, ''):
            value = model()
            value['model']['tables'][0]['lineageTag'] = invalid
            result = parse({'model.bim': json.dumps(value)})
            table = next(o for o in result['objects'] if o['kind'] == 'table')
            self.assertIsNone(table['native_id'])
            self.assertEqual(table['details']['native']['lineageTag'], invalid)
            self.assertIn('invalid_native_identity', {g['code'] for g in result['gaps']})

    def test_invalid_partition_source_type_is_preserved_without_crash(self):
        for invalid in ([], {}, True, None, 1):
            value = model()
            value['model']['tables'][0]['partitions'][0]['source']['type'] = invalid
            files = {'Workshop.SemanticModel/model.bim': json.dumps(value)}
            result = parse(files)
            validate(result, files)
            self.assertIn('invalid_partition', {g['code'] for g in result['gaps']})
            partition = next(o for o in result['objects'] if o['kind'] == 'partition')
            self.assertEqual(partition['details']['native']['source']['type'], invalid)


def tmdl():
    return {
        'Workshop.SemanticModel/definition/model.tmdl': 'model Workshop\n\tref table Tickets\n\tref table Regions\n',
        'Workshop.SemanticModel/definition/tables/Tickets.tmdl': (
            "table Tickets\n\tlineageTag: synthetic-tickets\n"
            "\tcolumn Region\n\t\tdataType: string\n\t\tsourceColumn: region\n"
            "\tcolumn Cost\n\t\tdataType: int64\n\t\tsourceColumn: cost\n"
            "\tmeasure 'Total cost' = SUM(Tickets[Cost])\n\t\tformatString: #,0\n"
            "\tpartition 'Ticket feed' = m\n\t\tmode: import\n\t\tsource =\n"
            "\t\t\tlet\n\t\t\t    Source = ExternalConnector(\"synthetic\")\n\t\t\tin Source\n"),
        'Workshop.SemanticModel/definition/tables/Regions.tmdl': (
            'table Regions\n\tcolumn Region\n\t\tdataType: string\n\t\tsourceColumn: region\n'),
        'Workshop.SemanticModel/definition/relationships.tmdl': (
            "relationship 'Region relationship'\n\tfromColumn: Tickets.Region\n\ttoColumn: Regions.Region\n"
            '\tisActive: false\n\tcrossFilteringBehavior: bothDirections\n\tsecurityFilteringBehavior: bothDirections\n'),
        'Workshop.SemanticModel/definition/roles/Regional.tmdl': (
            "role 'Regional reader'\n\tmodelPermission: read\n"
            '\ttablePermission Tickets = Tickets[Region] = USERPRINCIPALNAME()\n'),
    }


class PowerBIAdapterTests(unittest.TestCase):
    def test_tmsl_retains_raw_m_dax_security_and_relationship_behavior(self):
        source = model()
        raw = json.dumps(source)
        result = parse({'model.bim': raw})
        self.assertEqual({x['language'] for x in result['expressions']}, {'m', 'dax'})
        self.assertIn('let\n  Source = ExternalConnector("synthetic")\nin Source', [x['text'] for x in result['expressions']])
        rls = next(x for x in result['expressions'] if x['details'].get('purpose') == 'row_level_security')
        self.assertEqual(rls['text'], 'Tickets[Region] = USERPRINCIPALNAME()')
        relation = next(x for x in result['objects'] if x['kind'] == 'relationship')
        self.assertFalse(relation['details']['native']['isActive'])
        self.assertEqual(relation['details']['native']['securityFilteringBehavior'], 'bothDirections')
        permission = next(x for x in result['objects'] if x['kind'] == 'tablePermission')
        self.assertEqual(permission['details']['native']['columnPermissions'][0]['metadataPermission'], 'none')
        self.assertTrue(all(x['details']['resolution'] == 'resolved' for x in result['dependencies']))
        self.assertFalse(result['execution_performed'])
        self.assertEqual(result['native_validation'], 'not_run')
        self.assertEqual(result['export_completeness'], 'not_established')
        self.assertEqual(result['source_files'][0]['sha256'], hashlib.sha256(raw.encode()).hexdigest())

    def test_tmdl_cross_file_refs_and_raw_expressions(self):
        files = tmdl()
        result = parse(files)
        self.assertEqual(len([x for x in result['objects'] if x['kind'] == 'table']), 2)
        self.assertEqual(len(result['expressions']), 3)
        self.assertTrue(all(x['details']['resolution'] == 'resolved' for x in result['dependencies']))
        self.assertTrue(all(x['status'] == 'partial' for x in result['source_files']))
        self.assertEqual({g['code'] for g in result['gaps']}, {'bounded_tmdl'})
        security = next(x for x in result['expressions'] if x['details']['purpose'] == 'row_level_security')
        self.assertIn('USERPRINCIPALNAME()', security['text'])
        m = next(x for x in result['expressions'] if x['language'] == 'm')
        self.assertIn('\t\t\t    Source = ExternalConnector("synthetic")', m['text'])
        self.assertIn('source =\n', m['details']['raw_tmdl'])
        root_parts = {p.removeprefix('Workshop.SemanticModel/'): value for p, value in files.items()}
        root_result = parse(root_parts)
        self.assertTrue(all(x['details']['resolution'] == 'resolved' for x in root_result['dependencies']))
        validate(root_result, root_parts)

    def test_tmdl_quoted_names_fenced_expression_and_unknown_fragment(self):
        raw = ("table 'Sales.With''Quote'\n"
               "\tcolumn 'Item cost'\n\t\tdataType: decimal\n"
               "\tmeasure 'Multiline' = ```\n"
               "  VAR x = \"table Rogue\"  \n\n  RETURN x\n\t\t```\n"
               "\tcalculationGroup\n\t\tcalculationItem Fake = 7\n")
        result = parse({'definition/tables/one.tmdl': raw})
        self.assertEqual([x['name'] for x in result['objects']], ["Sales.With'Quote", 'Item cost', 'Multiline'])
        self.assertEqual(result['expressions'][0]['text'], '  VAR x = "table Rogue"  \n\n  RETURN x\n')
        self.assertIn('unsupported_tmdl_fragment', {x['code'] for x in result['gaps']})

    def test_tmdl_invalid_indent_fence_or_duplicate_property_never_claims_model(self):
        for raw in ('table Tickets\n  column ID\n', 'table Tickets\n\tmeasure x = ```\nabc',
                    'table Tickets\n\tlineageTag: x\n\tlineageTag: y\n',
                    'table Tickets\n\tmeasure x =\n\t\tSUM(1)\n'):
            with self.subTest(raw=raw):
                result = parse({'bad.tmdl': raw})
                self.assertEqual([x['kind'] for x in result['objects']], ['unparsed_tmdl'])
                self.assertEqual(result['objects'][0]['details']['raw_text'], raw)
                self.assertIn('malformed_or_unsupported_tmdl', {x['code'] for x in result['gaps']})

    def test_missing_and_ambiguous_references_are_unresolved(self):
        files = tmdl()
        del files['Workshop.SemanticModel/definition/tables/Regions.tmdl']
        result = parse(files)
        self.assertTrue(any(x['details']['resolution'] == 'unresolved' for x in result['dependencies']))
        self.assertIn('unresolved_reference', {x['code'] for x in result['gaps']})
        files = tmdl()
        files['Workshop.SemanticModel/definition/tables/Duplicate.tmdl'] = 'table Regions\n\tcolumn Region\n'
        result = parse(files)
        self.assertIn('duplicate_identity', {x['code'] for x in result['gaps']})
        self.assertIn('unresolved_reference', {x['code'] for x in result['gaps']})

    def test_invalid_json_and_malformed_collections_are_reported(self):
        for raw in ('{"model":{},"model":{}}', '{', 'NaN', '[1,2]'):
            result = parse({'model.bim': raw})
            self.assertTrue(result['gaps'])
        source = model()
        source['model']['tables'] = [{'name': ['bad'], 'columns': []}, 4]
        result = parse({'model.bim': json.dumps(source)})
        self.assertIn('missing_identity', {x['code'] for x in result['gaps']})
        self.assertIn('invalid_object', {x['code'] for x in result['gaps']})

    def test_unsafe_paths_and_collisions_rejected(self):
        for files in ({'../escape.bim': '{}'}, {'a.bim': '{}', 'A.bim': '{}'},
                      {'a': 'x', 'a/model.bim': '{}'}):
            with self.subTest(files=files), self.assertRaises(ValueError):
                parse(files)

    def test_source_is_never_executed(self):
        files = {'payload.py': 'raise RuntimeError("MUST NOT RUN")',
                 'model.bim': json.dumps(model())}
        with patch('subprocess.run', side_effect=AssertionError('No subprocess')):
            result = parse(files)
        self.assertEqual(next(x for x in result['source_files'] if x['path'] == 'payload.py')['status'], 'unsupported')
        self.assertFalse(result['execution_performed'])

    @unittest.skipUnless(OPTIONAL, 'Existing PBIP profile requires optional source dependencies')
    def test_existing_pbip_baseline_uses_legacy_profile(self):
        case = SKILL / 'examples/powerbi-omni-e2e/input/repo'
        files = {p.relative_to(case).as_posix(): p.read_text() for p in case.rglob('*') if p.is_file()}
        result = parse(files)
        kinds = [x['kind'] for x in result['objects']]
        self.assertEqual(kinds.count('table'), 3)
        self.assertEqual(kinds.count('measure'), 9)
        self.assertEqual(kinds.count('page'), 1)
        self.assertEqual(kinds.count('visual'), 3)
        self.assertEqual(kinds.count('filter'), 5)
        self.assertEqual(len([x for x in result['expressions'] if x['details'].get('purpose') == 'row_level_security']), 4)
        self.assertTrue(any(x['details'].get('basis') == 'legacy_static_inventory' for x in result['dependencies']))
        self.assertEqual({x['code'] for x in result['gaps']}, {'bounded_tmsl', 'legacy_native_runtime_unverified', 'legacy_bounded_semantics'})
        self.assertNotIn('dma-powerbi-', json.dumps(result))
        validate(result, files)

    @unittest.skipUnless(OPTIONAL, 'Existing PBIP profile requires optional source dependencies')
    def test_remote_model_and_escaping_reference_do_not_fetch_or_hide_model(self):
        case = SKILL / 'examples/powerbi-omni-e2e/input/repo'
        original = {p.relative_to(case).as_posix(): p.read_text() for p in case.rglob('*') if p.is_file()}
        path = 'Billing.Report/definition.pbir'
        for reference in ({'byConnection': {'connectionString': 'Data Source=https://example.invalid'}},
                          {'byPath': {'path': '../../outside'}}):
            files = dict(original)
            doc = json.loads(files[path])
            doc['datasetReference'] = reference
            files[path] = json.dumps(doc)
            result = parse(files)
            self.assertIn('legacy_native_binding_error', {x['code'] for x in result['gaps']})
            self.assertEqual(len([x for x in result['objects'] if x['kind'] == 'measure']), 9)
            self.assertEqual(len([x for x in result['expressions'] if x['details'].get('purpose') == 'row_level_security']), 4)


if __name__ == '__main__':
    unittest.main()
