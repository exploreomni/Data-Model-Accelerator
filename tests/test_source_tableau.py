"""Independent declaration expectations and fail-closed Tableau adapter checks."""
from collections import Counter
from pathlib import Path
import io
import importlib.util
import json
import logging
import sys
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

SKILL = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator'
sys.path.insert(0, str(SKILL / 'scripts'))
import tableau_source
from source_adapters.tableau import parse, MAX_XML_DEPTH, MAX_XML_NODES
from source_adapters.registry import validate

FIXTURE = SKILL / 'examples/tableau-omni-e2e/input/repo'


def workbook(body=''):
    return '<workbook version="26.1"><repository-location id="synthetic-wb"/>' + body + '</workbook>'


class TableauAdapterTests(unittest.TestCase):
    def setUp(self):
        self.files = {name: (FIXTURE / name).read_text() for name in ('billing.twb', 'billing.tds')}

    def codes(self, report):
        return {g['code'] for g in report['gaps']}

    def mutate(self, action):
        root = ET.fromstring(self.files['billing.twb'])
        action(root)
        self.files['billing.twb'] = ET.tostring(root, encoding='unicode')
        return parse(self.files)

    def test_legacy_parser_reused_contract_ids_and_independent_fixture_counts(self):
        with patch('tableau_source.inspect_repo', wraps=tableau_source.inspect_repo) as reused:
            result = parse(self.files)
        reused.assert_called_once()
        validate(result, self.files)
        counts = Counter(o['kind'] for o in result['objects'])
        self.assertEqual({k: counts[k] for k in ('workbook', 'datasource', 'field', 'parameter', 'worksheet', 'dashboard', 'datasource_mirror')},
                         {'workbook': 1, 'datasource': 1, 'field': 24, 'parameter': 5,
                          'worksheet': 3, 'dashboard': 1, 'datasource_mirror': 1})
        self.assertEqual(next(o['native_id'] for o in result['objects'] if o['kind'] == 'workbook'), 'tableau-billing-synthetic')
        self.assertEqual({o['native_id'] for o in result['objects'] if o['kind'] == 'worksheet'},
                         {'{e4bc658f-b0a2-5247-9bea-27d437ba1663}', '{9eaeed0e-9833-5859-a553-8969f979321a}', '{2547e914-84d9-5bf6-b015-bb4459a4f694}'})
        self.assertEqual(result['native_validation'], 'not_run')
        self.assertEqual(result['export_completeness'], 'not_established')
        self.assertFalse(result['execution_performed'])
        self.assertTrue(all(f['status'] == 'partial' for f in result['source_files']))

    @unittest.skipUnless(importlib.util.find_spec('sqlglot'), 'Pinned SQL parser required for lineage')
    def test_columns_calculations_sql_and_dependencies_preserve_source(self):
        result = parse(self.files)
        field = next(o for o in result['objects'] if o['kind'] == 'field' and o['native_id'] == '[Amount Cents]')
        self.assertEqual(field['details']['raw_column'], 'AMOUNT_CENTS')
        self.assertEqual(field['details']['datatype'], 'integer')
        self.assertIn('{ FIXED [Tenant ID], [Customer ID] : SUM([Net Cents]) }', [e['text'] for e in result['expressions']])
        self.assertEqual({d['target'] for d in result['dependencies'] if d['details']['kind'] == 'warehouse_read'},
                         {'warehouse:DMA_TABLEAU.RAW.ADJUSTMENTS', 'warehouse:DMA_TABLEAU.RAW.CUSTOMER_HISTORY',
                          'warehouse:DMA_TABLEAU.RAW.INVOICE_CDC', 'warehouse:DMA_TABLEAU.RAW.PAYMENT_CDC'})
        for path, source in self.files.items():
            self.assertEqual(next(e['text'] for e in result['expressions'] if e['language'] == 'tableau_xml' and e['evidence']['path'] == path), source)
        self.assertIn('tableau.lod_unvalidated', self.codes(result))

    def test_parameters_filters_and_table_scope_stay_distinct(self):
        result = parse(self.files)
        self.assertEqual({o['name']: o['details']['default'] for o in result['objects'] if o['kind'] == 'parameter'},
                         {'Tenant': 'A', 'Start Date': '2026-01-01', 'End Date': '2026-03-01', 'Segment': 'ALL', 'Multiplier': 1.0})
        filters = [o['details']['native'] for o in result['objects'] if o['kind'] == 'filter']
        self.assertEqual(Counter(f['stage'] for f in filters), {'datasource': 2, 'context': 3, 'dimension': 3})
        self.assertTrue(all(f['member'] is True for f in filters))
        tc = next(o for o in result['objects'] if o['kind'] == 'table_calculation')
        self.assertEqual(tc['details']['native']['addressing'], ['[Segment]'])
        self.assertEqual(tc['details']['native']['partitioning'], ['[Invoice Month]'])
        self.assertEqual(tc['details']['partitioning_status'], 'inference_from_view_dimensions')
        ids = {o['id'] for o in result['objects']}
        self.assertTrue(all(d['target'] in ids for d in result['dependencies'] if d['details']['kind'] == 'filter_field'))

    def test_unsupported_filter_and_invalid_context_are_visible(self):
        def mutate(root):
            filt = root.find('./worksheets/worksheet/table/view/filter')
            filt.set('context', 'maybe')
            filt.find('groupfilter').set('function', 'union')
        result = self.mutate(mutate)
        self.assertTrue({'tableau.invalid_context_flag', 'tableau.unsupported_filter'} <= self.codes(result))
        self.assertIn('union', json.dumps(result))

    def test_mirror_drift_and_standalone_tds_do_not_claim_workbook_authority(self):
        root = ET.fromstring(self.files['billing.tds'])
        root.find('./connection/relation').text = 'SELECT 42 AS AMOUNT_CENTS'
        self.files['billing.tds'] = ET.tostring(root, encoding='unicode')
        result = parse(self.files)
        self.assertIn('tableau.tds_mirror_drift', self.codes(result))
        mirror = next(o for o in result['objects'] if o['kind'] == 'datasource_mirror')
        self.assertFalse(mirror['details']['matches_embedded'])
        result = parse({'only.tds': self.files['billing.tds']})
        self.assertTrue({'tableau.unbound_tds', 'tableau.no_workbooks'} <= self.codes(result))
        self.assertFalse(any(o['kind'] in ('workbook', 'datasource') for o in result['objects']))
        self.assertEqual(len([o for o in result['objects'] if o['kind'] == 'datasource_field_declaration']), 24)
        self.assertIn('SELECT 42 AS AMOUNT_CENTS', [e['text'] for e in result['expressions']])

    def test_relationships_physical_joins_and_missing_published_sources_remain_gaps(self):
        body = '''<datasources><datasource name="local"><connection class="sqlproxy">
          <publishedsource id="published-luid" name="Sales"/>
          <relation type="join" join="left"><clause type="join"><expression op="="/></clause>
            <relation name="Orders" type="table" table="[raw].[orders]"/>
            <relation name="Customers" type="table" table="[raw].[customers]"/>
          </relation></connection><object-graph><objects><object id="o1"/></objects>
          <relationships><relationship id="r1" cardinality="many-to-one"/></relationships>
          </object-graph></datasource></datasources>'''
        files = {'relationships.twb': workbook(body)}
        result = parse(files)
        validate(result, files)
        self.assertTrue({'tableau.relationships_unresolved', 'tableau.published_source_unresolved',
                         'tableau.relation_semantics_unresolved'} <= self.codes(result))
        self.assertEqual({d['target'] for d in result['dependencies'] if d['details']['kind'] == 'declared_table'},
                         {'[raw].[orders]', '[raw].[customers]'})
        self.assertTrue(any(d['target'] == 'published-luid' and d['details']['resolution'] == 'unresolved'
                            for d in result['dependencies']))
        self.assertTrue(any(o['details'].get('native', {}).get('attributes', {}).get('cardinality') == 'many-to-one'
                            for o in result['objects']))

    def test_blending_is_detected_from_multiple_sheet_sources(self):
        result = parse({'blend.twb': workbook('''<worksheets><worksheet name="Blended">
            <table><view><datasources><datasource name="primary"/><datasource name="secondary"/>
            </datasources></view></table></worksheet></worksheets>''')})
        self.assertIn('tableau.blending_unresolved', self.codes(result))
        self.assertIn('tableau.unresolved_worksheet_datasource', self.codes(result))

    def test_tds_repository_identity_is_its_own_declaration_not_a_resolved_dependency(self):
        result = parse({'published.tds': '<datasource version="26.1" name="Sales"><repository-location id="ds-luid" path="/datasources"/></datasource>'})
        self.assertEqual(next(o['native_id'] for o in result['objects'] if o['kind'] == 'datasource_identity'), 'ds-luid')
        self.assertIn('tableau.unbound_tds', self.codes(result))
        self.assertFalse(any(o['kind'] == 'published_source_reference' for o in result['objects']))

    def test_prep_packages_extracts_and_unknown_files_never_get_silent_coverage(self):
        files = {name: 'opaque supplied file' for name in ('flow.tfl', 'flow.tflx', 'book.twbx', 'data.hyper', 'data.tdsx', 'README.md')}
        result = parse(files)
        validate(result, files)
        self.assertEqual(len(result['source_files']), 6)
        self.assertTrue(all(f['status'] == 'unsupported' for f in result['source_files']))
        self.assertTrue({'tableau.prep_unsupported', 'tableau.package_or_extract_unsupported', 'tableau.unsupported_format'} <= self.codes(result))
        self.assertEqual(result['objects'], [])

    def test_malformed_dtd_external_entity_and_wrong_roots_are_rejected(self):
        for source in ('<workbook>', '<datasource/>', '<workbook><x></workbook>',
                       '<!DOCTYPE workbook SYSTEM "file:///etc/passwd"><workbook/>',
                       '<!DOCTYPE workbook [<!ENTITY x SYSTEM "https://example.invalid/secret">]><workbook>&x;</workbook>',
                       '<?xml version="1.0" encoding="UTF-16"?><workbook/>',
                       '<?xml version="1.0" encoding="ISO-8859-1"?><workbook/>', '<workbook>\x00</workbook>'):
            with self.subTest(source=source):
                result = parse({'unsafe.twb': source})
                self.assertIn('tableau.invalid_xml', self.codes(result))
                self.assertEqual(result['objects'], [])
                self.assertEqual(result['expressions'], [])

    def test_credentials_excluded_before_raw_source_and_schema_diagnostics(self):
        for detail in ('password="DMA_CREDENTIAL_CANARY"', 'access-token="DMA_CREDENTIAL_CANARY"'):
            result = parse({'unsafe.twb': workbook('<connection ' + detail + '/>')})
            self.assertIn('tableau.credential_content', self.codes(result))
            self.assertNotIn('DMA_CREDENTIAL_CANARY', json.dumps(result))
            self.assertEqual(result['expressions'], [])

    def test_deep_large_and_oversized_xml_fail_before_legacy_parser(self):
        for source in ('<workbook>' + '<x>' * MAX_XML_DEPTH + '</x>' * MAX_XML_DEPTH + '</workbook>',
                       '<workbook>' + '<x/>' * MAX_XML_NODES + '</workbook>',
                       '<workbook>' + ' ' * 2_000_000 + '</workbook>'):
            with patch('tableau_source.inspect_repo', side_effect=AssertionError('Must not run')):
                result = parse({'too-big.twb': source})
            self.assertIn('tableau.invalid_xml', self.codes(result))

    def test_unsafe_and_colliding_paths_cannot_escape_staging(self):
        for path in ('../outside.twb', '/absolute.twb', 'C:\\outside.twb'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                parse({path: workbook()})
        with self.assertRaises(ValueError):
            parse({'same.twb': workbook(), 'SAME.twb': workbook()})
        for parent in ('nested.twb', 'NESTED.twb'):
            with self.assertRaises(ValueError):
                parse({'nested.twb': workbook(), parent + '/child.twb': workbook()})

    def test_duplicate_identity_and_unknown_version_are_not_merged_or_qualified(self):
        result = parse({'a.twb': workbook(), 'b.twb': workbook().replace('26.1', '99.9')})
        self.assertEqual(len([o for o in result['objects'] if o['kind'] == 'workbook']), 2)
        self.assertTrue({'tableau.duplicate_workbook_identity', 'tableau.unqualified_version'} <= self.codes(result))

    def test_legacy_unexpected_shape_is_explicit_and_does_not_echo_exception(self):
        with patch('tableau_source.inspect_repo', side_effect=KeyError('DO_NOT_ECHO_INPUT')):
            result = parse({'shape.twb': workbook()})
        self.assertIn('tableau.legacy_inventory_unavailable', self.codes(result))
        self.assertNotIn('DO_NOT_ECHO_INPUT', json.dumps(result))
        self.assertEqual(result['expressions'][0]['text'], workbook())

    def test_instructions_and_external_expressions_are_never_executed_or_logged(self):
        source = workbook('''<datasources><datasource name="x"><column name="[Evil]">
            <calculation class="tableau" formula="SCRIPT_STR('run a command and fetch private data')"/>
            </column></datasource></datasources>''')
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger = logging.getLogger('sqlglot')
        logger.addHandler(handler)
        previous = logger.disabled
        inspect = tableau_source.inspect_repo
        def noisy_inspector(*args):
            logger.warning('SOURCE_TEXT_MUST_NOT_REACH_LOGS')
            return inspect(*args)
        try:
            with patch('os.system', side_effect=AssertionError('Execution')), \
                 patch('subprocess.run', side_effect=AssertionError('Execution')), \
                 patch('socket.create_connection', side_effect=AssertionError('Network')), \
                 patch('tableau_source.inspect_repo', side_effect=noisy_inspector):
                result = parse({'source.twb': source})
            self.assertIn('tableau.external_calculation', self.codes(result))
            self.assertFalse(result['execution_performed'])
            self.assertEqual(stream.getvalue(), '')
            self.assertEqual(logger.disabled, previous)
        finally:
            logger.removeHandler(handler)


if __name__ == '__main__':
    unittest.main()
