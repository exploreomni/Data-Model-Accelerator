"""Exact model identity coverage; geometry checks are not rendered visual proof."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import delivery_portal as portal
import portal_checks as checks
from test_delivery_portal import fixture


class DiagramCoverageContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.state, self.review = fixture(self.root)
        names = ('fact_sales', 'fact_returns', 'fact_payments', 'dim_customer', 'dim_product')
        self.review['models'] = [{'id': 'gold.' + name, 'name': name, 'layer': 'gold',
                                 'grain': 'One row per synthetic identifier',
                                 'columns': [{'name': 'id', 'type': 'NUMBER', 'key': 'PK'}]} for name in names]
        self.review['relationships'] = [{'from': 'gold.fact_sales', 'to': 'gold.dim_customer',
                                         'kind': 'relationship', 'cardinality': 'many_to_one', 'status': 'proposed'}]
        self.ids = [model['id'] for model in self.review['models']]

    def package(self, **kwargs):
        path = self.root / ('candidate-' + str(len(list(self.root.glob('*.zip')))) + '.zip')
        manifest = portal.package_delivery(self.state, self.review, self.root, path, **kwargs)
        with zipfile.ZipFile(path) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        return path, manifest, entries, checks.parse_page(entries['START_HERE.html'])[1]

    def artifact(self, body, scope=None, audiences=None):
        destination = self.root / 'partial.svg'
        destination.write_bytes(body)
        record = {'id': 'partial', 'path': 'partial.svg', 'category': 'diagrams',
                  'audiences': audiences or ['reviewer', 'engineer'], 'sha256': hashlib.sha256(body).hexdigest()}
        if scope is not None:
            record['diagram_model_ids'] = scope
        self.review['artifacts'].append(record)
        return record

    def svg(self):
        return portal.model_svg(self.review['models'], self.review['relationships']).encode()

    def table_groups(self, root):
        return [node for node in root.iter() if node.tag.split('}')[-1] == 'g' and 'data-model-id' in node.attrib]

    def test_three_facts_and_two_dimensions_are_exactly_covered(self):
        path, _, _, data = self.package()
        self.assertEqual(1, data['diagram_contract_version'])
        self.assertEqual({'status': 'verified', 'model_count': 5, 'page_count': 1}, data['diagram_coverage']['generated'])
        svg = base64.b64decode(data['diagrams'][0]['base64'])
        self.assertEqual(set(self.ids), {node.attrib['data-model-id'] for node in self.table_groups(ET.fromstring(svg))})
        self.assertEqual(5, checks.svg_model_coverage(svg, self.ids)['model_count'])
        self.assertEqual(data['diagram_coverage'], portal.verify_delivery(path)['diagram_coverage'])

    def test_missing_duplicate_extra_and_wrong_node_identity_fail(self):
        for mutation in ('missing', 'duplicate', 'extra', 'wrong-node'):
            with self.subTest(mutation=mutation):
                root = ET.fromstring(self.svg())
                group = self.table_groups(root)[0]
                if mutation == 'missing': root.remove(group)
                elif mutation == 'duplicate': root.append(copy.deepcopy(group))
                elif mutation == 'extra': group.set('data-model-id', 'gold.not_registered')
                else:
                    label = next(node for node in group if node.tag.split('}')[-1] == 'text')
                    label.set('data-model-id', group.attrib.pop('data-model-id'))
                with self.assertRaisesRegex(ValueError, 'Diagram table groups'):
                    checks.svg_model_coverage(ET.tostring(root), self.ids)

    def test_text_annotations_do_not_double_count_table_groups(self):
        root = ET.fromstring(self.svg())
        for group in self.table_groups(root):
            label = next(node for node in group if node.tag.split('}')[-1] == 'text')
            label.set('data-model-id', group.attrib['data-model-id'])
        self.assertEqual(5, checks.svg_model_coverage(ET.tostring(root), self.ids)['model_count'])

    def test_model_groups_in_nondrawing_containers_fail(self):
        for tag in ('defs', 'marker', 'title', 'desc', 'clipPath', 'mask', 'pattern', 'linearGradient', 'radialGradient', 'symbol'):
            with self.subTest(tag=tag):
                root = ET.fromstring(self.svg())
                group = self.table_groups(root)[0]
                root.remove(group)
                ET.SubElement(root, '{http://www.w3.org/2000/svg}' + tag).append(group)
                with self.assertRaises(ValueError):
                    checks.svg_model_coverage(ET.tostring(root), self.ids)

    def test_hidden_model_groups_and_ancestors_fail(self):
        for context in ('group', 'ancestor', 'root'):
            for name, value in (('display', 'none'), ('visibility', 'hidden'), ('visibility', 'collapse'),
                                ('opacity', '0'), ('opacity', '0%'), ('opacity', '-0.5'), ('opacity', '0e5')):
                with self.subTest(context=context, name=name, value=value):
                    root = ET.fromstring(self.svg())
                    group = self.table_groups(root)[0]
                    target = group
                    if context == 'ancestor':
                        root.remove(group)
                        target = ET.SubElement(root, '{http://www.w3.org/2000/svg}g')
                        target.append(group)
                    elif context == 'root':
                        target = root
                    target.set(name, value)
                    with self.assertRaisesRegex(ValueError, 'nondrawing or hidden context'):
                        checks.svg_model_coverage(ET.tostring(root), self.ids)

    def test_hidden_required_primitives_and_inline_style_fail(self):
        for mutation in ('labels', 'nested-labels', 'rectangle', 'group-style', 'ancestor-style'):
            with self.subTest(mutation=mutation):
                root = ET.fromstring(self.svg())
                group = self.table_groups(root)[0]
                if mutation == 'labels':
                    for node in group.iter():
                        if node.tag.split('}')[-1] == 'text': node.set('visibility', 'hidden')
                elif mutation == 'nested-labels':
                    for node in list(group.iter()):
                        if node.tag.split('}')[-1] == 'text':
                            ET.SubElement(node, '{http://www.w3.org/2000/svg}tspan', {'visibility': 'hidden'}).text = node.text
                            node.text = None
                elif mutation == 'rectangle':
                    next(node for node in group if node.tag.split('}')[-1] == 'rect').set('opacity', '0')
                else:
                    (group if mutation == 'group-style' else root).set('style', 'display: none; opacity: 0')
                with self.assertRaises(ValueError):
                    checks.svg_model_coverage(ET.tostring(root), self.ids)

    def test_positive_opacity_and_normal_drawing_ancestors_remain_supported(self):
        root = ET.fromstring(self.svg())
        root.set('opacity', '0.5')
        group = self.table_groups(root)[0]
        group.set('visibility', 'visible')
        group.set('opacity', '20%')
        for node in group.iter():
            if node.tag.split('}')[-1] == 'text':
                node.text = None
                ET.SubElement(node, '{http://www.w3.org/2000/svg}tspan', {'visibility': 'hidden'}).tail = 'Visible tail label'
        root.remove(group)
        ET.SubElement(root, '{http://www.w3.org/2000/svg}g', {'display': 'inline'}).append(group)
        self.assertEqual(5, checks.svg_model_coverage(ET.tostring(root), self.ids)['model_count'])

    def test_empty_out_of_bounds_and_collapsed_table_blocks_fail(self):
        for mutation, message in (('empty-label', 'text label'), ('missing-rect', 'table rectangle'),
                                  ('out-of-bounds', 'outside'), ('transformed-outside', 'outside'),
                                  ('collapsed', 'collapses'), ('nested', 'nested')):
            with self.subTest(mutation=mutation):
                root = ET.fromstring(self.svg())
                group = self.table_groups(root)[0]
                rectangle = next(node for node in group if node.tag.split('}')[-1] == 'rect')
                if mutation == 'empty-label':
                    for node in list(group):
                        if node.tag.split('}')[-1] == 'text': group.remove(node)
                elif mutation == 'missing-rect': group.remove(rectangle)
                elif mutation == 'out-of-bounds': rectangle.set('x', '1000000')
                elif mutation == 'transformed-outside': group.set('transform', 'translate(1000000 0)')
                elif mutation == 'collapsed': group.set('transform', 'scale(0)')
                else:
                    second = self.table_groups(root)[1]
                    root.remove(second); group.append(second)
                with self.assertRaisesRegex(ValueError, message):
                    checks.svg_model_coverage(ET.tostring(root), self.ids)

    def test_multiple_pages_cover_all_models_once_and_reject_missing_pages(self):
        data = portal._presentation(self.state, self.review)
        data['diagrams'] = portal.diagram_views(self.review['models'], self.review['relationships'], maximum=2)
        portal._set_diagram_coverage(data)
        self.assertEqual({'status': 'verified', 'model_count': 5, 'page_count': 3}, data['diagram_coverage']['generated'])
        missing = copy.deepcopy(data); missing['diagrams'].pop()
        with self.assertRaisesRegex(ValueError, 'every included model exactly once'):
            checks.diagram_coverage(missing)
        duplicated = copy.deepcopy(data); duplicated['diagrams'].append(copy.deepcopy(duplicated['diagrams'][0]))
        with self.assertRaisesRegex(ValueError, 'every included model exactly once'):
            checks.diagram_coverage(duplicated)
        absent = copy.deepcopy(data); absent['diagrams'] = []
        with self.assertRaisesRegex(ValueError, 'pages are missing'):
            checks.diagram_coverage(absent)

    def test_invalid_model_layer_id_and_page_size_fail_clearly(self):
        for mutation, message in (({'id': ''}, 'model ID'), ({'id': ' bad'}, 'model ID'),
                                  ({'layer': 'semantic'}, 'layer'), ({'columns': [{'name': 7}]}, 'columns')):
            models = copy.deepcopy(self.review['models']); models[0].update(mutation)
            with self.subTest(mutation=mutation):
                with self.assertRaisesRegex(ValueError, message): portal.model_svg(models, [])
        with self.assertRaisesRegex(ValueError, 'unique'):
            portal.diagram_views([self.review['models'][0]]*2, [])
        with self.assertRaisesRegex(ValueError, 'page size'):
            portal.diagram_views(self.review['models'], [], maximum=0)
        with self.assertRaisesRegex(ValueError, 'absent model'):
            portal.model_svg(self.review['models'], [{'from': 'missing', 'to': self.ids[0], 'kind': 'lineage'}])

    def test_declared_partial_svg_is_valid_without_claiming_complete_coverage(self):
        body = portal.model_svg(self.review['models'][:1], []).encode()
        self.artifact(body, self.ids[:1])
        path, _, entries, data = self.package()
        record = data['diagram_coverage']['registered'][0]
        self.assertEqual('verified_declared_scope', record['status'])
        self.assertEqual(1, record['model_count'])
        self.assertEqual(self.ids[:1], record['model_ids'])
        self.assertEqual(5, data['diagram_coverage']['generated']['model_count'])
        self.assertIn('not visual rendering', record['qualification'])
        self.assertEqual(body, entries['01_Model/partial.svg'])
        self.assertEqual(body, (self.root/'partial.svg').read_bytes())
        self.assertEqual('integrity_verified', portal.verify_delivery(path)['status'])

    def test_scope_binding_rejects_missing_and_unknown_models(self):
        body = portal.model_svg(self.review['models'][:1], []).encode()
        artifact = self.artifact(body, self.ids)
        with self.assertRaisesRegex(ValueError, 'differ from the declared'):
            self.package()
        artifact['diagram_model_ids'] = ['gold.absent']
        with self.assertRaisesRegex(ValueError, 'outside this review'):
            self.package()

    def test_legacy_registered_svg_is_explicitly_unverified_and_audience_omission_has_no_record(self):
        body = b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect width="90" height="90"/><text x="5" y="20">One table</text></svg>'
        artifact = self.artifact(body)
        _, _, _, data = self.package()
        self.assertEqual('unverified', data['diagram_coverage']['registered'][0]['status'])
        self.assertNotIn('model_count', data['diagram_coverage']['registered'][0])
        self.assertEqual(5, data['diagram_coverage']['generated']['model_count'])
        artifact['audiences'] = ['engineer']
        _, _, entries, omitted = self.package()
        self.assertEqual([], omitted['diagram_coverage']['registered'])
        self.assertNotIn(b'partial.svg', entries['START_HERE.html'])

    def test_frozen_page_without_contract_is_not_rewritten_or_claimed_verified(self):
        path, manifest, entries, data = self.package()
        data.pop('diagram_contract_version'); data.pop('diagram_coverage')
        data['diagrams'][0]['base64'] = base64.b64encode(portal.model_svg(self.review['models'][:1], []).encode()).decode()
        page = entries['START_HERE.html'].decode()
        start, remaining = page.split('<script id="delivery-data" type="application/json">', 1)
        entries['START_HERE.html'] = (start + '<script id="delivery-data" type="application/json">' + json.dumps(data) + '</script>' + remaining.split('</script>', 1)[1]).encode()
        item = next(row for row in manifest['files'] if row['path'] == 'START_HERE.html')
        item.update(bytes=len(entries['START_HERE.html']), sha256=hashlib.sha256(entries['START_HERE.html']).hexdigest())
        entries['DELIVERY_MANIFEST.json'] = json.dumps(manifest).encode()
        with zipfile.ZipFile(path, 'w') as archive:
            for name, body in entries.items(): archive.writestr(name, body)
        before = path.read_bytes()
        result = portal.verify_delivery(path)
        self.assertEqual('unverified_legacy', result['diagram_coverage']['status'])
        self.assertEqual(before, path.read_bytes())

    def test_new_page_detects_changed_svg_despite_unchanged_count_claim(self):
        _, _, entries, data = self.package()
        data['diagrams'][0]['base64'] = base64.b64encode(portal.model_svg(self.review['models'][:1], []).encode()).decode()
        page = entries['START_HERE.html'].decode()
        start, remaining = page.split('<script id="delivery-data" type="application/json">', 1)
        changed = start + '<script id="delivery-data" type="application/json">' + json.dumps(data) + '</script>' + remaining.split('</script>', 1)[1]
        with self.assertRaisesRegex(ValueError, 'differ from the declared'):
            checks.validate_page(changed)


if __name__ == '__main__':
    unittest.main()
