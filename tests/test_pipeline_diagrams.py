"""Pipeline inventory and geometric invariants; browser rendering is separate QA."""
import base64
import copy
import json
from pathlib import Path
import random
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import pipeline_diagrams as pipelines
import portal_checks


def model(identifier, layer='silver', **values):
    return dict({'id':identifier, 'name':identifier, 'layer':layer}, **values)


def edge(source, target, **values):
    return dict({'from': source, 'to': target, 'kind': 'lineage'}, **values)


def fixture():
    models = [model('raw.orders', 'bronze', object_kind='source'),
              model('raw.customers', 'bronze', object_kind='source'),
              model('stg.orders', depends_on=['raw.orders'], disposition='create', keys=['order_id']),
              model('stg.customers', depends_on=['raw.customers'], disposition='reuse'),
              model('int.orders', depends_on=['stg.orders','stg.customers']),
              model('gold.fact_orders','gold',depends_on=['int.orders'],disposition='create',
                    columns=[dict(name='order_id',key='PK'),dict(name='customer_id',key='FK')]),
              model('gold.dim_customers','gold',depends_on=['stg.customers'],disposition='reuse')]
    relationships = [edge('gold.fact_orders','gold.dim_customers',kind='relationship',cardinality='many_to_one')]
    return models, relationships


class PipelineDiagramTests(unittest.TestCase):
    def assertGeometry(self, layout):
        boxes = {node['id']: node for node in layout['nodes']}
        for node in boxes.values():
            self.assertGreaterEqual(node['x'], 0); self.assertGreaterEqual(node['y'], 0)
            self.assertLessEqual(node['x']+node['width'],layout['width']);self.assertLessEqual(node['y']+node['height'],layout['height'])
        for i, a in enumerate(boxes.values()):
            for b in list(boxes.values())[i+1:]:
                overlap = min(a['x']+a['width'],b['x']+b['width'])>max(a['x'],b['x']) and min(a['y']+a['height'],b['y']+b['height'])>max(a['y'],b['y'])
                self.assertFalse(overlap,(a['id'],b['id']))
        segments=[]
        for route in layout['edges']:
            for a,b in zip(route['points'],route['points'][1:]):
                self.assertTrue(a[0]==b[0] or a[1]==b[1])
                for p in (a,b):
                    self.assertTrue(0<=p[0]<=layout['width'] and 0<=p[1]<=layout['height'],p)
                if a==b:continue
                segments.append((route['id'],a,b))
                for identifier,box in boxes.items():
                    if a[0]==b[0]:
                        hits=box['x']<a[0]<box['x']+box['width'] and min(a[1],b[1])<box['y']+box['height'] and max(a[1],b[1])>box['y']
                    else:
                        hits=box['y']<a[1]<box['y']+box['height'] and min(a[0],b[0])<box['x']+box['width'] and max(a[0],b[0])>box['x']
                    self.assertFalse(hits,(route['id'],identifier,a,b))
        for i,(identifier,a,b) in enumerate(segments):
            for other,c,d in segments[i+1:]:
                if identifier==other:continue
                if a[0]==b[0]==c[0]==d[0]:
                    self.assertLessEqual(min(max(a[1],b[1]),max(c[1],d[1])),max(min(a[1],b[1]),min(c[1],d[1])),(identifier,other,'vertical overlap'))
                elif a[1]==b[1]==c[1]==d[1]:
                    self.assertLessEqual(min(max(a[0],b[0]),max(c[0],d[0])),max(min(a[0],b[0]),min(c[0],d[0])),(identifier,other,'horizontal overlap'))

    def test_one_upstream_pipeline_per_gold_and_join_is_not_dependency(self):
        models,relationships=fixture();views=pipelines.pipeline_views(models,relationships)
        self.assertEqual(len(views),2)
        by_target={v['target_model_id']:v for v in views}
        fact=by_target['gold.fact_orders'];dimension=by_target['gold.dim_customers']
        self.assertEqual(set(fact['model_ids']),{m['id'] for m in models}-{'gold.dim_customers'})
        self.assertEqual(set(dimension['model_ids']),{'raw.customers','stg.customers','gold.dim_customers'})
        self.assertTrue(all(e['kind']=='lineage' for e in fact['edges']))
        self.assertEqual(len(fact['join_relationships']),1)
        self.assertEqual(fact['join_relationships'][0]['occurrences'][0]['cardinality'],'many_to_one')
        layout=pipelines.pipeline_layout(models,relationships,target_model_id='gold.fact_orders')
        self.assertEqual([row['label'] for row in layout['rows']],['Raw / sources','Staging / preparation','Intermediate','Gold output'])
        for e in layout['edges']:
            nodes={n['id']:n for n in layout['nodes']};self.assertLess(nodes[e['from']]['y'],nodes[e['to']]['y'])
        self.assertGeometry(layout)

    def test_exact_canonical_group_and_name_identity_coverage(self):
        models,relationships=fixture()
        for view in pipelines.pipeline_views(models,relationships):
            svg=base64.b64decode(view['base64']);root=ET.fromstring(svg)
            self.assertEqual(portal_checks.svg_model_coverage(svg,view['model_ids'])['model_count'],len(view['model_ids']))
            labels={node.get('data-model-id') for node in root.iter() if node.tag.endswith('text') and node.get('data-model-id')}
            self.assertEqual(labels,set(view['model_ids']))
            paths=[node for node in root.iter() if node.get('data-edge-id')]
            self.assertEqual({node.get('data-edge-id') for node in paths},{e['id'] for e in view['edges']})
            self.assertEqual(float(root.get('width')),float(view['width']))

    def test_silver_labels_do_not_invent_staging_from_dependency_depth(self):
        for name, expected in (('int_orders', 'Intermediate'),
                               ('warehouse.int_orders', 'Intermediate'),
                               ('stg_orders', 'Staging / preparation'),
                               ('orders_prepared', 'Silver / transformations')):
            with self.subTest(name=name):
                models = [model('raw', 'bronze'), model(name, depends_on=['raw']),
                          model('gold', 'gold', depends_on=[name])]
                layout = pipelines.pipeline_layout(models, [], target_model_id='gold')
                self.assertEqual(layout['rows'][1]['label'], expected)
        mixed = [model('raw', 'bronze'), model('stg_orders', depends_on=['raw']),
                 model('int_customers', depends_on=['raw']),
                 model('gold', 'gold', depends_on=['stg_orders', 'int_customers'])]
        self.assertEqual(pipelines.pipeline_layout(mixed, [], target_model_id='gold')['rows'][1]['label'],
                         'Silver / transformations')

    def test_duplicate_declarations_deduplicate_path_but_keep_provenance(self):
        models=[model('raw','bronze'),model('gold','gold',depends_on=['raw'])]
        edges=[edge('raw','gold',occurrence_id='one',label='First recorded declaration'),edge('raw','gold',occurrence_id='two',label='Second recorded declaration')]
        layout=pipelines.pipeline_layout(models,edges,target_model_id='gold')
        self.assertEqual(len(layout['edges']),1);record=layout['edges'][0]
        self.assertEqual(record['occurrence_count'],3)
        self.assertEqual({r['evidence_origin'] for r in record['occurrences']},{'relationship_record','depends_on'})
        self.assertTrue({'one','two'} <= {r['pipeline_occurrence_id'] for r in record['occurrences']})
        supplied=copy.deepcopy(edges);supplied[0]['evidence_origin']='authored_proposal'
        preserved=pipelines.pipeline_layout(models,supplied,target_model_id='gold')['edges'][0]['occurrences']
        self.assertIn('authored_proposal',{r['evidence_origin'] for r in preserved})

    def test_missing_exact_endpoint_is_reference_only_and_never_fuzzy_matched(self):
        models=[model('customers','bronze'),model('gold','gold')]
        views=pipelines.pipeline_views(models,[edge('RAW.customers','gold')])
        primary=views[0]
        self.assertEqual(primary['model_ids'],['gold']);self.assertEqual(primary['reference_ids'],['RAW.customers'])
        root=ET.fromstring(base64.b64decode(primary['base64']))
        self.assertEqual({n.get('data-reference-id') for n in root if n.get('data-reference-id')},{'RAW.customers'})
        self.assertIn('Reference only',ET.tostring(root).decode());self.assertNotIn('data-model-id="RAW.customers"',ET.tostring(root).decode())
        self.assertEqual(set().union(*(set(v['model_ids']) for v in views)),{'customers','gold'})

    def test_isolated_interfaces_and_no_gold_preserve_every_input(self):
        models=[model('raw','bronze'),model('stage',depends_on=['raw']),model('isolated'),
                model('outside','gold',object_kind='interface'),model('join_only')]
        views=pipelines.pipeline_views(models,[edge('isolated','join_only',kind='relationship')])
        self.assertTrue(all(v['kind']=='supplemental_pipeline' for v in views))
        self.assertEqual(set().union(*(set(v['model_ids']) for v in views)),{m['id'] for m in models})
        self.assertTrue(all(v['target_model_id'] is None for v in views))
        self.assertIn('implementation unresolved',''.join(base64.b64decode(v['base64']).decode() for v in views))
        self.assertEqual(pipelines.pipeline_views([],[]),[])
        ET.fromstring(pipelines.pipeline_svg([],[]))

    def test_long_names_brief_declared_keys_and_safe_svg(self):
        name='warehouse.schema.'+'long_model_name_'*20+'<untrusted>'
        columns=[dict(name='column_'+str(i)) for i in range(30)]
        models=[model('gold','gold',name=name,keys=['supplied_key'],columns=columns),model('keys_only',keys=['declared_without_column'])]
        layout=pipelines.pipeline_layout(models,[])
        gold=next(n for n in layout['nodes'] if n['id']=='gold')
        self.assertEqual(''.join(line for line,kind in gold['lines'] if kind=='name'),name)
        self.assertFalse(any('column_29' in line for line,_ in gold['lines']))
        svg=pipelines.pipeline_svg(models,[]);root=ET.fromstring(svg)
        self.assertIn('type unverified',''.join(root.itertext()));self.assertIn('Declared key',''.join(root.itertext()))
        self.assertFalse(any(node.tag.split('}')[-1]=='untrusted' for node in root.iter()))
        self.assertNotIn('PK: supplied_key',svg);self.assertGeometry(layout)

    def test_cycles_and_self_loop_do_not_drop_edges_or_invent_order(self):
        models=[model('a'),model('b'),model('c','gold'),model('self','gold')]
        edges=[edge('a','b'),edge('b','a'),edge('b','c'),edge('self','self')]
        for view in pipelines.pipeline_views(models,edges):
            layout=pipelines.pipeline_layout(models,edges,target_model_id=view['target_model_id'])
            self.assertTrue(layout['cycles']);self.assertIn('CYCLE',pipelines.pipeline_svg(models,edges,target_model_id=view['target_model_id']))
            self.assertGeometry(layout)
        layouts=[pipelines.pipeline_layout(models,edges,target_model_id='c'),pipelines.pipeline_layout(models,edges,target_model_id='self')]
        self.assertEqual(sum(len(l['edges']) for l in layouts),4)
        self.assertEqual(sum(e['cycle'] for l in layouts for e in l['edges']),3)

    def test_skipped_rows_dense_fan_in_and_fan_out_do_not_cross_cards_or_overlap_routes(self):
        models=[model('raw'+str(i),'bronze') for i in range(4)]+[model('stg'+str(i)) for i in range(4)]+[model('int'+str(i)) for i in range(3)]+[model('gold','gold')]
        edges=[edge('raw'+str(i),'stg'+str(j)) for i in range(4) for j in range(4) if (i+j)%2==0]
        edges += [edge('stg'+str(i),'int'+str(j)) for i in range(4) for j in range(3)]
        edges += [edge('int'+str(i),'gold') for i in range(3)]+[edge('raw0','gold'),edge('raw1','int2')]
        layout=pipelines.pipeline_layout(models,edges,target_model_id='gold');self.assertGeometry(layout)
        self.assertGreaterEqual(layout['width'],1400);self.assertLessEqual(layout['width'],1800)

    def test_semantic_links_only_from_explicit_bindings_and_outside_bindings_retained(self):
        models,edges=fixture()
        semantic=dict(views=[dict(id='orders',name='Order semantic view',warehouse_model_ids=['gold.fact_orders','gold.dim_customers']),
                             dict(id='other',name='Other view',warehouse_model_ids=['raw.orders'])],
                      topics=[dict(id='commerce',name='Commerce topic',view_ids=['orders','other'])])
        views=pipelines.pipeline_views(models,edges,semantic=semantic)
        fact=next(v for v in views if v['target_model_id']=='gold.fact_orders')
        self.assertEqual(set(fact['semantic_ids']),{'@semantic/view/orders','@semantic/topic/commerce'})
        self.assertTrue(any(e['from']=='gold.dim_customers' for e in fact['external_connections']))
        self.assertTrue(any('@semantic/view/other' in v['semantic_ids'] for v in views))
        svg=base64.b64decode(fact['base64']);root=ET.fromstring(svg)
        self.assertEqual({n.get('data-semantic-id') for n in root if n.get('data-semantic-id')},{'orders','commerce'})
        self.assertEqual(portal_checks.svg_model_coverage(svg,fact['model_ids'])['model_count'],len(fact['model_ids']))
        self.assertGeometry(pipelines.pipeline_layout(models,edges,target_model_id='gold.fact_orders',semantic=semantic))
        for invalid in (dict(views=[dict(id='bad',name='Bad',warehouse_model_ids=['outside'])]),dict(topics=[dict(id='bad',name='Bad',view_ids=['unknown'])]),dict(views=[dict(id='bad',name='Bad',warehouse_model_ids=['gold.fact_orders'],sql='secret')])):
            with self.assertRaises(ValueError):pipelines.pipeline_views(models,edges,semantic=invalid)

    def test_deterministic_order_immutable_inputs_and_wide_natural_size(self):
        models,edges=fixture();original=copy.deepcopy((models,edges))
        first=pipelines.pipeline_views(models,edges)
        random.Random(17).shuffle(models);edges.reverse()
        self.assertEqual(first,pipelines.pipeline_views(models,edges))
        self.assertEqual(sorted(models,key=lambda m:m['id']),sorted(original[0],key=lambda m:m['id']))
        models=[model('raw'+str(i),'bronze') for i in range(12)]+[model('gold','gold')]
        layout=pipelines.pipeline_layout(models,[edge(m['id'],'gold') for m in models[:-1]],target_model_id='gold')
        self.assertEqual({n['width'] for n in layout['nodes']},{300});self.assertGreater(layout['width'],4000);self.assertGeometry(layout)

    def test_long_chain_avoids_recursion_and_supplied_gold_ancestor_is_preserved(self):
        models=[model('node-'+str(i), 'gold' if i in (900,1100) else 'silver',depends_on=['node-'+str(i-1)] if i else []) for i in range(1101)]
        views=pipelines.pipeline_views(models,[])
        self.assertEqual([v['target_model_id'] for v in views],['node-1100','node-900'])
        self.assertEqual(len(views[0]['model_ids']),1101);self.assertEqual(len(views[0]['edges']),1100)
        self.assertIn('node-900',views[0]['model_ids'])

    def test_invalid_inputs_fail_instead_of_silently_losing_models(self):
        for models,edges in (([model('one','unknown')],[]),([model('same'),model('same')],[]),([model('one',depends_on='two')],[]),([model('one')],[edge('one','two',kind='guessed_join')])):
            with self.assertRaises(ValueError):pipelines.pipeline_views(models,edges)

    def test_seeded_mixed_graphs_have_clear_routes_and_complete_edge_inventory(self):
        for seed in range(40):
            rng=random.Random(seed)
            models=[model('n'+str(i),rng.choice(['bronze','silver','gold'])) for i in range(12)]
            pairs={(rng.randrange(12),rng.randrange(12)) for _ in range(25)}
            edges=[edge('n'+str(a),'n'+str(b)) for a,b in sorted(pairs)]
            with self.subTest(seed=seed):
                layout=pipelines.pipeline_layout(models,edges)
                self.assertEqual(len(layout['edges']),len(pairs))
                self.assertGeometry(layout)
                views=pipelines.pipeline_views(models,edges)
                self.assertEqual(set().union(*(set(v['model_ids']) for v in views)),{m['id'] for m in models})
                self.assertEqual({(e['from'],e['to']) for v in views for e in v['edges']},{(e['from'],e['to']) for e in edges})


if __name__=='__main__':unittest.main()
