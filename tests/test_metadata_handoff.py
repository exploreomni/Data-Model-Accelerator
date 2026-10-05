"""Semantic/AI handoff is grounded data with explicit acceptance gaps."""
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/data-model-accelerator/scripts'))
from metadata_handoff import semantic_handoff,export_handoff
from metadata_contract import build_contract
from test_metadata_contract import dictionary,configuration
from test_warehouse_metadata_plan import observation
from test_privacy_contract import approved_policy


class MetadataHandoffTests(unittest.TestCase):
    def test_explicit_ai_policy_keeps_approved_physical_names_without_live_claim(self):
        contract=build_contract(dictionary(),configuration())
        result=semantic_handoff(contract,observation(contract,expected=True),approved_policy())
        self.assertTrue(result['observation_matches_expected'])
        self.assertFalse(result['live_provenance_authenticated'])
        self.assertFalse(result['consumer_import_verified'])
        self.assertEqual(result['resources'][0]['columns'][0]['name'],'CustomerId')
        self.assertEqual(result['resources'][0]['columns'][0]['sensitivity'],'INTERNAL')

    def test_default_ai_projection_withholds_all_fields_without_separate_policy(self):
        contract=build_contract(dictionary(),configuration())
        result=semantic_handoff(contract)
        self.assertEqual(result['resources'],[])
        self.assertFalse(result['disclosure_complete'])
        self.assertNotIn('CustomerId',str(result))
        self.assertNotIn('target',result)

    def test_unknown_restricted_and_sensitive_prose_are_not_emitted(self):
        for sensitivity in ('UNKNOWN','RESTRICTED'):
            value=dictionary(False) if sensitivity=='UNKNOWN' else dictionary()
            column=value['models'][0]['columns'][0]
            if sensitivity=='RESTRICTED':
                column['sensitivity']='RESTRICTED';column['privacy']['sensitivity']='RESTRICTED'
            contract=build_contract(value,configuration())
            result=semantic_handoff(contract,disclosure_policy=approved_policy())
            self.assertEqual(result['resources'],[])
            self.assertNotIn('CustomerId',str(result))
        value=dictionary();value['models'][0]['description']='fictional-person@example.invalid'
        result=semantic_handoff(build_contract(value,configuration()),disclosure_policy=approved_policy())
        self.assertEqual(result['resources'],[])
        self.assertNotIn('fictional-person',str(result))

    def test_context_export_is_fresh_and_preserves_existing_outputs(self):
        contract=build_contract(dictionary(False),configuration())
        with tempfile.TemporaryDirectory() as root:
            path=Path(root).resolve()/'handoff'
            export_handoff(contract,path)
            self.assertTrue((path/'metadata-semantic-handoff.json').exists())
            self.assertIn('never become executable agent instructions',(path/'AI_CONTEXT.md').read_text())
            with self.assertRaises(ValueError):
                export_handoff(contract,path)
