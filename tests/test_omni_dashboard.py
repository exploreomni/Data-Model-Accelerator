"""Neutral 11-tile regression; target fragments are synthetic, not tenant proof."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import omni_dashboard as dashboard
from looker_source import parse_dashboard
from ae_common import hash_json


def source():
    tiles = [{'id': 't' + str(i), 'type': 'vis', 'title': 'Synthetic metric ' + str(i),
              'query': {'id': 'q' + str(i), 'model': 'manufacturing', 'view': 'cycles',
                        'fields': ['cycles.day', 'cycles.output'], 'sorts': ['cycles.day desc'],
                        'limit': '500', 'filters': {'cycles.day': '90 days'},
                        'dynamic_fields': '[{"table_calculation":"difference","expression":"${cycles.output} - ${cycles.input}"}]'},
              'listen': {'Period': 'cycles.day'}} for i in range(8)]
    tiles += [{'id': 't' + str(i), 'type': 'text', 'body_text': 'Synthetic note ' + str(i)} for i in range(8, 11)]
    return parse_dashboard({'id': 'synthetic-dashboard', 'title': 'Synthetic production',
        'dashboard_elements': tiles, 'dashboard_filters': [
            {'id': 'f' + str(i), 'name': name, 'type': 'date_filter' if i == 0 else 'field_filter',
             'default_value': '30 days' if i == 0 else 'All'} for i, name in enumerate(('Period', 'Plant', 'Shift'))],
        'dashboard_layouts': [{'id': 'layout1', 'active': True, 'dashboard_layout_components': [
            {'id': 'lc' + str(i), 'dashboard_element_id': t['id'], 'row': i * 4, 'column': 0, 'width': 12, 'height': 4}
            for i, t in enumerate(tiles)]}]})


def mapping(contract=None):
    contract = contract or source()
    m = dashboard.template(contract, 'a' * 64, '11111111-1111-4111-8111-111111111111')
    native = m['native_payload']
    for i, tile in enumerate(contract['tiles'], 1):
        key = str(i)
        fragment = {'type': 'query' if tile['kind'] == 'data' else 'blank', 'name': 'Tile ' + key}
        if tile['kind'] == 'data':
            fragment.update(topicName='cycles', query={'fields': ['cycles.day', 'cycles.output'], 'limit': 500,
                'filters': {'cycles.day': {'relative': '90 days'}}}, visConfig={'type': 'table'})
        else:
            fragment['visConfig'] = {'type': 'markdown', 'text': tile['source_payload']['body_text']}
        native['queryPresentations']['data'][key] = fragment
        native['queryPresentations']['order'].append(key)
        path = '/queryPresentations/data/' + key
        entry = m['tiles'][tile['id']]
        entry.update(status='mapped', target_pointer=path, target_sha256=hash_json(fragment))
        for facet in entry['behavior'].values():
            facet.update(status='mapped', target_pointer=path, target_sha256=hash_json(fragment))
    for item in contract['filters']:
        key = item['id']; fragment = {'name': item['source_payload']['name'], 'default': item['source_payload']['default_value']}
        native['controls']['data'][key] = fragment; native['controls']['order'].append(key)
        path = '/controls/data/' + key
        m['filters'][key].update(status='mapped', target_pointer=path, target_sha256=hash_json(fragment))
        m['filters'][key]['behavior']['source_payload'].update(status='mapped', target_pointer=path, target_sha256=hash_json(fragment))
    native['containers'] = [{'type': 'synthetic-layout-test', 'items': list(native['queryPresentations']['order'])}]
    m['layout'].update(status='mapped', target_pointer='/containers', target_sha256=hash_json(native['containers']))
    approve(m)
    return m


def approve(m):
    m['review'] = {'status': 'approved', 'reference': 'synthetic-review-only',
                   'mapping_sha256': hash_json({k: v for k, v in m.items() if k != 'review'})}


class DashboardBuildTests(unittest.TestCase):
    def test_reported_shape_preserved_without_native_claim(self):
        c = source(); result = dashboard.build(c, mapping(c))
        self.assertEqual(result['coverage'], {'tiles': 11, 'data_tiles': 8, 'text_tiles': 3, 'filters': 3})
        self.assertEqual(result['status'], 'complete')
        self.assertFalse(result['native_verified']); self.assertFalse(result['acceptance_ready'])
        self.assertTrue(result['source_gaps'])
        self.assertEqual(dashboard.verify_build(result), result)
        self.assertEqual(result['source_contract']['tiles'][0]['query']['filters']['cycles.day'], '90 days')
        self.assertEqual(result['native_payload']['controls']['data']['f0']['default'], '30 days')

    def test_template_is_useful_but_incomplete(self):
        c = source(); m = dashboard.template(c, 'a'*64, '11111111-1111-4111-8111-111111111111')
        result = dashboard.build(c, m)
        self.assertEqual(result['status'], 'incomplete')
        self.assertGreater(len(result['manual_steps']), 14)

    def test_missing_tile_text_filter_or_behavior_never_passes(self):
        for section, key in (('tiles','t0'), ('tiles','t10'), ('filters','f1')):
            c = source(); m = mapping(c); del m[section][key]; approve(m)
            with self.assertRaises(ValueError): dashboard.build(c,m)
        c=source();m=mapping(c);del m['tiles']['t0']['behavior']['filter_listeners'];approve(m)
        with self.assertRaises(ValueError):dashboard.build(c,m)

    def test_stale_source_native_or_review_fails(self):
        c=source();m=mapping(c);m['native_payload']['queryPresentations']['data']['1']['query']['limit']=50
        with self.assertRaises(ValueError):dashboard.build(c,m)
        c=source();m=mapping(c);c['tiles'][0]['query']['limit']='50';m['source_sha256']=hash_json(c);approve(m)
        with self.assertRaises(ValueError):dashboard.build(c,m)
        c=source();m=mapping(c);m['review']['mapping_sha256']='0'*64
        with self.assertRaises(ValueError):dashboard.build(c,m)

    def test_manual_facet_blocks_completion(self):
        c=source();m=mapping(c);m['tiles']['t0']['behavior']['calculations'].update(status='manual',reason='Meaning unresolved');approve(m)
        self.assertEqual(dashboard.build(c,m)['status'],'incomplete')

    def test_duplicate_target_deleted_tile_or_foreign_anchor_fails(self):
        for mutate in (
            lambda m:m['tiles']['t1'].update(target_pointer='/queryPresentations/data/1'),
            lambda m:m['native_payload']['queryPresentations']['data'].update({'1':None}),
            lambda m:m['native_payload']['queryPresentations']['data']['1']['query'].update(modelId='foreign'),
            lambda m:m['native_payload'].update(branchId='unreviewed')):
            c=source();m=mapping(c);mutate(m);approve(m)
            with self.assertRaises(ValueError):dashboard.build(c,m)

    def test_active_markup_or_external_resource_requires_manual_route(self):
        for text in ('<script>alert(1)</script>', 'https://external.invalid/image.png','data:text/html,x'):
            c=source();m=mapping(c);m['native_payload']['description']=text;approve(m)
            with self.assertRaises(ValueError):dashboard.build(c,m)

    def test_build_tamper_detected(self):
        c=source();r=dashboard.build(c,mapping(c));r['native_verified']=True
        with self.assertRaises(ValueError):dashboard.verify_build(r)

    def test_pointer_escapes_and_bounds(self):
        self.assertEqual(dashboard.pointer({'a/b':{'~':[1]}},'/a~1b/~0/0'),1)
        for p in ('', '/a~2b','/a~1b/~0/-1','/a~1b/~0/00','/a~1b/~0/9'):
            with self.assertRaises(ValueError): dashboard.pointer({'a/b':{'~':[1]}},p)


if __name__ == '__main__': unittest.main()
