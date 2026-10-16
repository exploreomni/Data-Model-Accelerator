"""Registry-wide availability, honest coverage, and dependency boundaries."""
import builtins
import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

SKILL = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator'
sys.path.insert(0, str(SKILL / 'scripts'))
from source_adapters.registry import SOURCES, capability, parse


class SourceCatalogueTests(unittest.TestCase):
    def test_every_advertised_adapter_has_a_maintained_contract_without_optional_imports(self):
        original_import = builtins.__import__
        def core_only(name, *args, **kwargs):
            if name.split('.')[0] in ('sqlglot', 'yaml', 'lkml', 'jsonschema'):
                raise ImportError('Optional dependencies unavailable')
            return original_import(name, *args, **kwargs)
        for source in SOURCES:
            with self.subTest(source=source), patch('builtins.__import__', side_effect=core_only):
                importlib.reload(importlib.import_module('source_adapters.' + source))
                info = capability(source)
                self.assertTrue(info['formats'])
                self.assertTrue(info['limitations'])
                self.assertEqual(info['acquisition'], 'supplied_exports')
                self.assertEqual(info['native_validation'], 'not_qualified')
                self.assertTrue((SKILL / info['documentation']).is_file())

    def test_unknown_and_malformed_inputs_never_claim_native_or_complete_coverage(self):
        for source in SOURCES:
            for files in ({}, {'opaque.unsupported': 'unrecognized'}, {'malformed.json': '{"broken":'}):
                with self.subTest(source=source, files=list(files)):
                    result = parse(source, files)
                    self.assertEqual(result['native_validation'], 'not_run')
                    self.assertEqual(result['export_completeness'], 'not_established')
                    self.assertFalse(result['execution_performed'])
                    self.assertEqual(len(result['component_sha256']), 64)
                    self.assertTrue(all(f['status'] != 'parsed' for f in result['source_files']))


if __name__ == '__main__':
    unittest.main()
