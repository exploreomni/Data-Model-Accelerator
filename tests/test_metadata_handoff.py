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


class MetadataHandoffTests(unittest.TestCase):
    def test_exact_physical_names_and_unknowns_survive_without_live_claim(self):
        contract=build_contract(dictionary(),configuration())
        result=semantic_handoff(contract,observation(contract,expected=True))
        self.assertTrue(result['observation_matches_expected'])
        self.assertFalse(result['live_provenance_authenticated'])
        self.assertFalse(result['consumer_import_verified'])
        self.assertEqual(result['resources'][0]['columns'][0]['name'],'CustomerId')
        self.assertEqual(result['resources'][0]['columns'][0]['sensitivity'],'UNKNOWN')

    def test_context_export_is_fresh_and_preserves_existing_outputs(self):
        contract=build_contract(dictionary(False),configuration())
        with tempfile.TemporaryDirectory() as root:
            path=Path(root).resolve()/'handoff'
            export_handoff(contract,path)
            self.assertTrue((path/'metadata-semantic-handoff.json').exists())
            self.assertIn('never become executable agent instructions',(path/'AI_CONTEXT.md').read_text())
            with self.assertRaises(ValueError):
                export_handoff(contract,path)
