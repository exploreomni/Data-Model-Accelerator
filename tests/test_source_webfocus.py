"""Independent structural expectations for the bounded WebFOCUS recognizer."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
from source_adapters import webfocus
from source_adapters.registry import validate, parse as registry_parse


class WebFOCUSSourceTests(unittest.TestCase):
    def inspect(self, files):
        report = webfocus.parse(files)
        validate(report, files)
        self.assertFalse(report['execution_performed'])
        self.assertEqual(report['export_completeness'], 'not_established')
        self.assertEqual(report['native_validation'], 'not_run')
        return report

    def test_literal_fex_preserves_stages_keys_and_exact_source(self):
        fex = """-* Synthetic declaration fixture, not customer or native execution evidence.
JOIN CUSTOMER_ID IN sales TO ALL ID IN customers AS J_CUSTOMER
DEFINE FILE sales
NET/D12.2 = REVENUE - REFUNDS;
END
TABLE FILE sales
 SUM NET BY REGION
COMPUTE MARGIN/D12.4 = NET / REVENUE;
WHERE REGION EQ 'North BY West';
END
"""
        out = self.inspect({'projects/team-a/apps/report.fex': fex})
        self.assertEqual([(o['kind'], o['name']) for o in out['objects']], [
            ('procedure', 'projects/team-a/apps/report.fex'),
            ('join_declaration', 'J_CUSTOMER'), ('define_block', 'sales'),
            ('virtual_field', 'NET'), ('report_request', 'sales'),
            ('calculated_field', 'MARGIN')])
        self.assertEqual([d['target'] for d in out['dependencies']], ['sales', 'customers', 'sales', 'sales'])
        self.assertTrue(all(d['details']['resolution'] == 'unresolved' for d in out['dependencies']))
        join = out['objects'][1]
        self.assertEqual(join['native_id'], 'J_CUSTOMER')
        self.assertEqual(join['details']['source_key'], 'CUSTOMER_ID')
        self.assertEqual(join['details']['target_key'], 'ID')
        self.assertTrue(join['details']['all_declared'])
        stages = {o['name']: o['details'].get('evaluation_stage') for o in out['objects']}
        self.assertEqual((stages['NET'], stages['MARGIN']), ('record', 'report'))
        expressions = out['expressions']
        self.assertEqual(expressions[0]['text'], fex)
        self.assertIn("REGION EQ 'North BY West';", [e['text'] for e in expressions])
        self.assertIn('REVENUE - REFUNDS', [e['text'] for e in expressions])
        self.assertEqual([e['details']['native_fields'] for e in expressions if 'native_fields' in e['details']], [['NET'], ['REGION']])
        self.assertEqual(join['evidence']['locator'], 'line:2')
        self.assertEqual(out['source_files'][0]['status'], 'partial')
        self.assertNotIn('webfocus.unsupported_command', {g['code'] for g in out['gaps']})

    def test_master_access_records_preserve_native_formats_and_quoted_values(self):
        files = {
            'nested/model/sales.mas': "FILENAME=sales, SUFFIX=SQLORA, $\nSEGMENT=SALES, SEGTYPE=S0, $\nFIELDNAME=REGION, ALIAS=region_name, USAGE=A30, ACTUAL=A30, TITLE='Region, Area', $\nFIELDNAME=NET, ALIAS=net, USAGE=D12.2, ACTUAL=D8, MISSING=ON, $\n",
            'nested/model/sales.acx': "SEGNAME=SALES, TABLENAME='DW.SALES', CONNECTION=warehouse, KEYS=1, $\n",
        }
        out = self.inspect(files)
        field = next(o for o in out['objects'] if o['kind'] == 'column' and o['name'] == 'REGION')
        self.assertEqual(field['native_id'], 'REGION')
        self.assertEqual(field['details']['native_attributes'], {'FIELDNAME': 'REGION', 'ALIAS': 'region_name', 'USAGE': 'A30', 'ACTUAL': 'A30', 'TITLE': "'Region, Area'"})
        physical = next(d for d in out['dependencies'] if d['details']['kind'] == 'physical_relation')
        self.assertEqual(physical['target'], 'DW.SALES')
        self.assertEqual(physical['details']['native_connection'], 'warehouse')
        self.assertEqual(physical['details']['resolution'], 'unresolved')
        self.assertTrue(field['evidence']['locator'].startswith('chars:'))
        self.assertEqual({x['path'] for x in out['source_files']}, set(files))

    def test_nested_same_names_never_merge(self):
        fex = 'TABLE FILE sales\nPRINT ID\nEND\n'
        files = {'project-one/app/report.fex': fex, 'project-two/app/report.fex': fex}
        out = registry_parse('webfocus', files)
        validate(out, files)
        self.assertEqual(len(out['objects']), 4)
        self.assertEqual(len({o['id'] for o in out['objects']}), 4)
        self.assertEqual(len(out['component_sha256']), 64)
        self.assertEqual(out, registry_parse('webfocus', dict(reversed(list(files.items())))))

    def test_dynamic_include_session_security_and_unknown_are_explicit(self):
        fex = "-INCLUDE secure/profile\n-SET &FILE='sales';\nTABLE FILE &FILE\nSET ALL=ON\nSQL SQLORA SELECT * FROM PRIVATE;\n-RUN\nUNKNOWN NEXT\n"
        files = {'report.fex': fex, 'secure.mas': 'FILENAME=s, SUFFIX=SQLORA, FILTER=TENANT_RULE, $'}
        with patch('builtins.eval', side_effect=AssertionError('execution attempted')):
            out = self.inspect(files)
        codes = {g['code'] for g in out['gaps']}
        self.assertTrue({'webfocus.dialogue_manager', 'webfocus.dynamic', 'webfocus.session_or_execution', 'webfocus.unsupported_command', 'webfocus.opaque_attributes', 'webfocus.runtime_context_unverified'} <= codes)
        self.assertEqual([(d['target'], d['details']['kind']) for d in out['dependencies']], [('secure/profile', 'include')])
        self.assertFalse(any(o['kind'] == 'report_request' for o in out['objects']))

    def test_malformed_records_and_incomplete_blocks_are_gaps(self):
        cases = [
            ('a.mas', 'FILENAME=a, FILENAME=b, SUFFIX=FIX,$', 'webfocus.duplicate_attribute'),
            ('a.mas', 'FILENAME=a, SUFFIX=FIX', 'webfocus.unterminated_record'),
            ('a.mas', "FILENAME='a, SUFFIX=FIX,$", 'webfocus.unterminated_quote'),
            ('a.mas', 'FILENAME=a,garbage,$', 'webfocus.invalid_attribute'),
            ('a.fex', 'TABLE FILE a\nSUM SALES\n', 'webfocus.missing_end'),
            ('a.fex', 'TABLE FILE a\nCOMPUTE N/I9 = 1\nEND', 'webfocus.unsupported_formula'),
            ('a.fex', "TABLE FILE a\nWHERE REGION EQ 'West\nEND", 'webfocus.unterminated_quote'),
            ('a.fex', 'TABLE FILE a\x00\nEND', 'webfocus.invalid_text'),
        ]
        for path, source, expected in cases:
            with self.subTest(expected=expected):
                out = self.inspect({path: source})
                self.assertIn(expected, {g['code'] for g in out['gaps']})
                self.assertEqual(out['expressions'][0]['text'], source)

    def test_unsupported_modifiers_are_not_field_names(self):
        out = self.inspect({'a.fex': "TABLE FILE a\nSUM SALES AS REVENUE\nBY HIGHEST REGION\nON TABLE RECOMPUTE SALES\nEND"})
        self.assertFalse(any('native_fields' in e['details'] for e in out['expressions']))
        self.assertIn('webfocus.unsupported_projection', {g['code'] for g in out['gaps']})
        self.assertIn('webfocus.unsupported_command', {g['code'] for g in out['gaps']})

    def test_metadata_duplicates_parameterization_and_unknown_types(self):
        out = self.inspect({'a.mas': 'FILENAME=a,SUFFIX=FIX,$SEGMENT=A,SEGTYPE=S0,$FIELDNAME=X,USAGE=I9,$FIELDNAME=X,USAGE=I9,$GROUP=G,USAGE=A10,$',
                            'a.acx': "SEGNAME=A,TABLENAME=&TABLE,CONNECTION=C,$"})
        self.assertTrue({'webfocus.duplicate_declaration', 'webfocus.unsupported_metadata', 'webfocus.dynamic'} <= {g['code'] for g in out['gaps']})
        self.assertFalse(out['dependencies'])

    def test_structure_limits_preserve_raw_without_silent_truncation(self):
        source = 'TABLE FILE a\n' + 'PRINT X\n' * (webfocus.MAX_UNITS + 1) + 'END\n'
        out = self.inspect({'a.fex': source})
        self.assertIn('webfocus.structure_limit', {g['code'] for g in out['gaps']})
        self.assertEqual(out['expressions'][0]['text'], source)
        huge_line = 'PRINT ' + 'A' * (webfocus.MAX_UNIT_CHARS + 1)
        out = self.inspect({'a.fex': huge_line})
        self.assertIn('webfocus.structure_limit', {g['code'] for g in out['gaps']})

    def test_orphan_fragments_and_amplification_limits_still_validate(self):
        out = self.inspect({'field.mas': 'FIELDNAME=X,USAGE=I9,$',
                            'segment.mas': 'SEGMENT=X,SEGTYPE=S0,$',
                            'binding.acx': 'SEGNAME=X,KEYS=1,$'})
        self.assertTrue({'webfocus.incomplete_field', 'webfocus.incomplete_segment',
                         'webfocus.master_header_missing', 'webfocus.access_binding_missing'}
                        <= {g['code'] for g in out['gaps']})
        sources = [
            ('a.mas', 'FILENAME=a,SUFFIX=FIX,$' * (webfocus.MAX_UNITS + 1)),
            ('a.mas', 'FILENAME=a,' + ','.join('K%d=X' % i for i in range(40)) + ',$'),
            ('a.fex', 'TABLE FILE a\nPRINT ' + ' '.join('X%d' % i for i in range(129)) + '\nEND'),
        ]
        for path, source in sources:
            with self.subTest(path=path):
                out = self.inspect({path: source})
                self.assertIn('webfocus.structure_limit', {g['code'] for g in out['gaps']})
                self.assertEqual(out['expressions'][0]['text'], source)

    def test_file_bounds_and_unsupported_files(self):
        with self.assertRaisesRegex(ValueError, 'source.unsafe_path'):
            webfocus.parse({'../a.fex': 'TABLE FILE a'})
        with self.assertRaisesRegex(ValueError, 'source.byte_limit'):
            webfocus.parse({'a.fex': 'a' * (8 * 1024 * 1024 + 1)})
        out = self.inspect({'bundle.zip': 'opaque', 'empty.fex': ''})
        self.assertEqual({x['path']: x['status'] for x in out['source_files']}, {'bundle.zip': 'unsupported', 'empty.fex': 'partial'})
        self.assertIn('webfocus.empty_source', {g['code'] for g in out['gaps']})


if __name__ == '__main__':
    unittest.main()
