"""RAW coverage is separate, exact and never inferred from a modeled name."""
import copy
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
from data_dictionary_v2 import validate_dictionary
from metadata_contract import build_contract
from test_metadata_contract import dictionary, configuration


def with_source():
    value = dictionary()
    source = copy.deepcopy(value['models'][0])
    source['source_id'] = 'source.raw.customer'
    del source['model_id']
    source['columns'][0]['column_id'] = 'source-column:customer-id'
    value['sources'] = [source]
    value['source_inventory_sha256'] = 'd' * 64
    return value


class SourceMetadataTests(unittest.TestCase):
    def test_sources_stay_out_of_model_inventory(self):
        value = with_source()
        self.assertEqual(validate_dictionary(value), [])
        self.assertEqual(len(value['models']), 1)
        value['sources'][0]['column_id'] = 'does-not-hide-column-collision'
        value['sources'][0]['columns'][0]['column_id'] = value['models'][0]['columns'][0]['column_id']
        self.assertTrue(any('duplicate column identity' in e for e in validate_dictionary(value)))

    def test_source_inventory_needs_binding_and_unique_identity(self):
        value = with_source()
        del value['source_inventory_sha256']
        self.assertTrue(validate_dictionary(value))
        value['source_inventory_sha256'] = 'd'*64
        value['sources'][0]['source_id'] = value['models'][0]['model_id']
        self.assertTrue(any('duplicate resource' in e for e in validate_dictionary(value)))

    def test_source_writes_need_explicit_scope_and_catalogue_lineage(self):
        value = with_source()
        config = configuration()
        binding = copy.deepcopy(config['resources'][0])
        binding.update(resource_id='source.raw.customer', resource_type='source', layer='raw')
        binding['relation']['namespace'][-1] = 'raw'
        config['resources'].append(binding)
        result = build_contract(value, config)
        self.assertEqual(len(result['blockers']), 2)
        config['metadata_policy'].update(raw_comments=True, source_ids=['source.raw.customer'])
        binding['source_write_decision'] = 'source-owner-review:1'
        ref = {'object_id': 'source.raw.customer', 'column_path': ['CustomerId'],
               'catalogue_sha256': config['catalogue_sha256']}
        value['sources'][0]['columns'][0]['source_refs'] = [ref]
        self.assertEqual(build_contract(value, config)['blockers'], [])
        ref['catalogue_sha256'] = 'e'*64
        self.assertTrue(build_contract(value, config)['blockers'])

    def test_every_source_requires_an_explicit_disposition(self):
        with self.assertRaisesRegex(ValueError, 'explicit disposition'):
            build_contract(with_source(), configuration())


if __name__ == '__main__':
    unittest.main()
