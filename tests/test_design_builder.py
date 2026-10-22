"""Canonical assembly preserves architectural meaning; it grants no authority."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import design_builder as builder
from design_consistency import project_review


def request():
    return {'schema_version': 1, 'kind': 'design_assembly', 'id': 'commerce', 'revision': 1,
            'nodes': [{'id': 'raw_orders', 'name': 'raw.orders', 'domain': 'sales', 'layer': 'bronze'},
                      {'id': 'orders', 'name': 'fct_orders', 'domain': 'sales', 'layer': 'gold',
                       'grain': 'One row per order', 'keys': ['order_id'],
                       'columns': [{'name': 'order_id', 'type': 'integer'}],
                       'depends_on': ['raw_orders', 'customers'], 'disposition': 'create'},
                      {'id': 'customers', 'name': 'Customer interface', 'domain': 'shared',
                       'layer': 'gold', 'object_kind': 'interface'}],
            'edges': [{'from': 'raw_orders', 'to': 'orders', 'kind': 'lineage'},
                      {'from': 'orders', 'to': 'customers', 'kind': 'relationship',
                       'cardinality': 'unknown', 'status': 'proposed'}]}


class BuilderTests(unittest.TestCase):
    def test_incomplete_draft_and_direct_source_gold_are_retained(self):
        value = request(); before = copy.deepcopy(value)
        design = builder.assemble(value)
        self.assertEqual(value, before)
        self.assertEqual(len(design['entities']), 3)
        self.assertEqual(design['entities'][0]['keys'], [])
        self.assertEqual(design['entities'][0]['grain'], 'unknown')
        self.assertEqual(design['entities'][2]['columns'], [])
        self.assertEqual(design['relationships'], value['edges'])

    def test_counts_exclude_interfaces_and_sources_from_models(self):
        total = builder.counts(builder.assemble(request())['entities'])
        self.assertEqual((total['models'], total['sources'], total['interfaces']), (1, 1, 1))
        self.assertEqual(total['by_layer'], {'bronze': 0, 'silver': 0, 'gold': 1})

    def test_unknown_dependencies_are_not_silently_dropped(self):
        value = request(); value['nodes'][1]['depends_on'].append('missing_intermediate')
        with self.assertRaisesRegex(ValueError, 'Unknown identifier'):
            builder.assemble(value)
        self.assertIn('missing_intermediate', value['nodes'][1]['depends_on'])

    def test_relationship_direction_and_composite_keys_survive_projection(self):
        value = request()
        value['edges'][1].update(cardinality='one_to_one', from_columns=['order_id', 'tenant_id'],
                                 to_columns=['customer_id', 'tenant_id'], role='owner',
                                 predicate='orders.tenant_id = customers.tenant_id')
        design = builder.assemble(value)
        self.assertEqual(project_review(design)['relationships'], value['edges'])
        self.assertIn('one_to_one', builder.narrative(design))

    def test_no_default_cardinality_and_no_join_assertions_on_lineage(self):
        value = request(); value['edges'][1].pop('cardinality')
        self.assertNotIn('cardinality', builder.assemble(value)['relationships'][1])
        value['edges'][0]['cardinality'] = 'one_to_many'
        with self.assertRaisesRegex(ValueError, 'separate edges'):
            builder.assemble(value)

    def test_invalid_keys_duplicates_cycles_and_unknown_fields_fail(self):
        mutations = [lambda r: r['nodes'][1]['keys'].append('fabricated'),
                     lambda r: r['nodes'].append(copy.deepcopy(r['nodes'][0])),
                     lambda r: r['nodes'][0].update(depends_on=['orders']),
                     lambda r: r['nodes'][0].update(unrecognized=True)]
        for mutate in mutations:
            value = request(); mutate(value)
            with self.assertRaises(ValueError):
                builder.assemble(value)

    def test_interface_cannot_be_declared_executable(self):
        value = request(); value['nodes'][2]['disposition'] = 'create'
        with self.assertRaisesRegex(ValueError, 'external interface'):
            builder.assemble(value)

    def test_no_existing_baseline_is_synthesized_from_the_proposal(self):
        value = request(); value['nodes'][1]['disposition'] = 'reuse'
        with self.assertRaises(ValueError):
            builder.assemble(value)

    def test_export_matches_canonical_ids_relationships_and_file_hashes(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder).resolve() / 'design'
            design = builder.assemble(request())
            manifest = builder.export_design(design, dest)
            self.assertEqual(json.loads((dest / 'design.json').read_text()), design)
            self.assertEqual(json.loads((dest / 'model-graph.json').read_text())['relationships'], design['relationships'])
            self.assertEqual(manifest['model_ids'], [e['id'] for e in design['entities']])
            for name, digest in manifest['files'].items():
                self.assertEqual(hashlib.sha256((dest / name).read_bytes()).hexdigest(), digest)
            for entity in design['entities']:
                self.assertIn(entity['id'], (dest / 'DESIGN.md').read_text())
                self.assertIn(entity['id'], (dest / 'ERD.svg').read_text())
            with self.assertRaisesRegex(ValueError, 'immutable'):
                builder.export_design(design, dest)

    def test_export_quotes_spreadsheet_formulas_and_escapes_svg(self):
        value = request(); value['nodes'][1]['columns'][0]['description'] = '=1+1'
        value['nodes'][1]['name'] = '<script>unsafe</script>'
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder).resolve() / 'export'
            builder.export_design(builder.assemble(value), dest)
            self.assertIn("'=1+1", (dest / 'DICTIONARY.csv').read_text())
            self.assertNotIn('<script>', (dest / 'ERD.svg').read_text())


if __name__ == '__main__':
    unittest.main()


class PipelineExportTests(unittest.TestCase):
    def test_new_pipeline_export_preserves_inventory_without_whole_domain_svg(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder).resolve() / 'pipelines'
            design = builder.assemble(request())
            manifest = builder.export_design(design, dest, diagram_mode='pipelines')
            self.assertFalse((dest / 'ERD.svg').exists())
            self.assertTrue((dest / 'PIPELINES.md').is_file())
            self.assertEqual(len(list((dest / 'Pipelines').glob('*.svg'))), 1)
            self.assertEqual(json.loads((dest / 'design.json').read_text()), design)
            for name, digest in manifest['files'].items():
                self.assertEqual(hashlib.sha256((dest / name).read_bytes()).hexdigest(), digest)
