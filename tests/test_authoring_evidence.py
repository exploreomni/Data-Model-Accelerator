"""Authoring evidence is additive; unresolved context is a first-class result."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
from authoring_evidence import validate_contract, make_receipt, finding, capture


def contract():
    return {'schema_version': 1, 'kind': 'authoring_contract', 'mode': 'provisional',
            'bindings': {'source_sha256': 'a'*64, 'design_sha256': 'b'*64, 'catalogue_sha256': None},
            'models': [{'id': 'orders', 'path': 'orders.sql', 'depends_on': None, 'columns': ['id']}],
            'assumptions': [{'id': 'binding', 'model_ids': ['orders'], 'fields': ['id'],
                'category': 'physical', 'status': 'unresolved', 'required_check': 'Confirm catalogue binding', 'evidence_refs': []}],
            'provenance': []}


class AuthoringEvidenceTests(unittest.TestCase):
    def test_unresolved_provisional_contract_is_valid_and_not_approved(self):
        value = contract()
        self.assertEqual(validate_contract(value), value)
        receipt = make_receipt(value, {'orders.sql': 'c'*64}, [finding('binding_unknown', 'not_run')], checker_sha256='d'*64)
        self.assertEqual(receipt['status'], 'not_run')
        self.assertEqual(receipt['assumptions'][0]['status'], 'unresolved')
        self.assertNotIn('approval', receipt)

    def test_false_resolution_and_invalid_version_rejected(self):
        for edit in ('resolved', 'version', 'scope', 'path'):
            value = contract()
            if edit == 'resolved': value['assumptions'][0]['status'] = 'resolved'
            if edit == 'version': value['schema_version'] = True
            if edit == 'scope': value['assumptions'][0]['model_ids'] = ['absent']
            if edit == 'path': value['models'][0]['path'] = '../outside.sql'
            with self.subTest(edit=edit), self.assertRaises(ValueError): validate_contract(value)

    def test_unknown_mapping_is_preserved_and_duplicate_mapping_rejected(self):
        value = contract(); value['models'][0]['path'] = None
        self.assertIsNone(validate_contract(value)['models'][0]['path'])
        value = contract(); other = copy.deepcopy(value['models'][0]); other['id'] = 'other'
        value['models'].append(other)
        with self.assertRaises(ValueError): validate_contract(value)

    def test_capture_rejects_symlink_and_receipt_preserves_denominator(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root).resolve(); (p/'one.sql').write_text('select 1'); (p/'alias.sql').symlink_to(p/'one.sql')
            self.assertEqual(len(capture(p, ['one.sql'])), 1)
            with self.assertRaises(ValueError): capture(p, ['alias.sql'])
        receipt = make_receipt(contract(), {}, [finding('ok', 'passed'), finding('parse', 'unsupported'), finding('bad', 'failed')], checker_sha256='d'*64)
        self.assertEqual(receipt['total'], 4)
        self.assertEqual(receipt['status'], 'failed')

    def test_unresolved_assumption_cannot_disappear_behind_a_static_pass(self):
        result = make_receipt(contract(), {}, [finding('syntax', 'passed')], checker_sha256='d'*64)
        self.assertEqual(result['status'], 'not_run')
        self.assertEqual(result['counts']['passed'], 1)
        self.assertEqual(result['counts']['not_run'], 1)


if __name__ == '__main__': unittest.main()
