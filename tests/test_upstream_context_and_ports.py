"""Bounded synthetic context and port decisions; never execute source projects."""
import copy
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import upstream_context as context
import staging_ports as ports
import domain_workflow as domains
from source_adapters.registry import parse
from engagement_stages import DIMENSIONS


@unittest.skipUnless(importlib.util.find_spec('yaml'), 'Pinned PyYAML required for authored-source binding')
class ContextAndPortTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'legacy'; self.source.mkdir()
        self.target = self.root / 'target'; self.target.mkdir()
        self.state = {'inputs': {'source': {'path': str(self.source), 'roots': [{'id': 'target', 'path': str(self.target)}]}},
                      'workflow': {'design': {'entities': [
                          {'id': 'gold', 'domain': 'sales', 'source_paths': ['models/gold.sql'], 'depends_on': []},
                          {'id': 'other', 'domain': 'other', 'source_paths': ['models/other.sql'], 'depends_on': []}],
                          'existing_models': []}, 'tasks': [], 'approvals': [{'unchanged': True}]}}
        domains.register(self.state, {'schema_version': 1, 'domains': [
            {'id': 'sales', 'name': 'Sales', 'description': 'Synthetic scope', 'asset_ids': [],
             'source_paths': ['models/gold.sql'], 'shared_dependency_ids': []}]})
        domains.ledger(self.state)['active_domain_id'] = 'sales'
        self.report = self.make_report(self.source, [('stage', "select * from {{ source('raw', 'events') }}", ['source.p.raw.events']),
            ('gold', "select * from {{ ref('stage') }}", ['model.p.stage']), ('other', 'select 2 as id', [])])
        self.target_report = self.make_report(self.target, [])
        self.register()

    def make_report(self, root, models):
        files = {'dbt_project.yml': 'name: p\nconfig-version: 2\n',
                 'models/schema.yml': 'version: 2\nsources:\n  - name: raw\n    tables:\n      - name: events\n',
                 'macros/helper.sql': '{% macro helper() %}1{% endmacro %}'}
        nodes = {}
        for name, sql, dependencies in models:
            path = 'models/' + name + '.sql'; files[path] = sql
            uid = 'model.p.' + name
            nodes[uid] = {'resource_type': 'model', 'unique_id': uid, 'package_name': 'p', 'name': name,
                          'original_file_path': path, 'raw_code': sql, 'depends_on': {'nodes': dependencies, 'macros': []}, 'columns': {}}
        source = {'resource_type': 'source', 'unique_id': 'source.p.raw.events', 'package_name': 'p', 'name': 'events',
                  'source_name': 'raw', 'original_file_path': 'models/schema.yml', 'columns': {}}
        files['manifest.json'] = json.dumps({'metadata': {'dbt_schema_version': 'https://schemas.getdbt.com/dbt/manifest/v12.json',
              'adapter_type': 'snowflake'}, 'nodes': nodes, 'sources': {source['unique_id']: source}})
        for name, content in files.items():
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content)
        return parse('dbt', files)

    def register(self):
        return context.register(self.state, {'schema_version': 1, 'extracts': [
            {'id': 'legacy', 'root_id': 'primary', 'result': self.report},
            {'id': 'target', 'root_id': 'target', 'result': self.target_report}],
            'bindings': [{'entity_id': 'gold', 'root_id': 'primary', 'native_ids': ['model.p.gold']}]})

    def node(self, native, root='primary'):
        return next(n for n in context.graph(context.read(self.state))[0].values()
                    if n['root_id'] == root and n['native_id'] == native)

    def pin(self, path):
        files = context.graph(context.read(self.state))[1]
        return {'reference': path, 'sha256': files[path]['sha256']}

    def policy(self, preference='compatible_target'):
        return ports.configure(self.state, {'schema_version': 1, 'domain_id': 'sales', 'target_root_id': 'target',
            'source_root_ids': ['primary'], 'candidate_model_ids': ['gold'], 'missing_staging': 'propose_port',
            'staging_object_ids': [self.node('model.p.stage')['id']],
            'version_preference': preference, 'request_reference': 'synthetic://user/staging-policy'})

    def row(self):
        return {'id': 'port-stage', 'model_ids': ['gold'], 'source_object_id': self.node('model.p.stage')['id'],
                'target_native_ids': ['model.p.stage'], 'decision': 'port_missing', 'candidate_path': 'models/staging/stage.sql',
                'rationale': 'Required upstream candidate; missing only in supplied target inventory.',
                'evidence_refs': [self.pin('models/stage.sql')],
                'support_files': [{**self.pin('models/schema.yml'), 'kind': 'yaml'},
                                  {**self.pin('macros/helper.sql'), 'kind': 'macro'},
                                  {**self.pin('dbt_project.yml'), 'kind': 'configuration'}]}

    def record_port(self, row):
        return ports.register(self.state, {'schema_version': 1, 'domain_id': 'sales', 'rows': [row]})

    def test_upstream_closure_does_not_expand_generation_or_rescan(self):
        before = copy.deepcopy(self.state['workflow']['design'])
        with patch('os.scandir', side_effect=AssertionError('No scan')), patch('source_adapters.registry.parse', side_effect=AssertionError('No repeated parse')):
            result = context.packet(self.state, ['gold'])
        self.assertEqual(result['generation_entity_ids'], ['gold'])
        self.assertEqual({n['native_id'] for n in result['nodes']}, {'model.p.gold', 'model.p.stage', 'source.p.raw.events'})
        self.assertEqual(before, self.state['workflow']['design'])
        self.assertEqual(domains.scope(self.state), {'gold'})
        self.assertEqual(self.state['workflow']['tasks'], [])
        self.assertIn('models/stage.sql', {f['reference'] for f in result['files']})
        domains.guard_dispatch(self.state, {'role': 'warehouse_architect', 'scope_ids': ['sales'], 'source_paths': ['models/stage.sql']})
        with self.assertRaises(ValueError):
            domains.guard_dispatch(self.state, {'role': 'warehouse_architect', 'scope_ids': ['sales'], 'source_paths': ['models/other.sql']})

    def test_cross_repository_identity_requires_explicit_link(self):
        self.target_report = self.make_report(self.target, [('stage', 'select 4 as id', [])]); self.register()
        self.assertNotEqual(self.node('model.p.stage')['id'], self.node('model.p.stage', 'target')['id'])
        result = context.derive(self.state, ['gold'])
        self.assertNotIn('target', {n['root_id'] for n in result['nodes']})
        context.register(self.state, {'schema_version': 1, 'extracts': [], 'links': [{
            'source': {'root_id': 'primary', 'native_id': 'model.p.gold'},
            'target': {'root_id': 'target', 'native_id': 'model.p.stage'}, 'evidence_refs': [self.pin('models/gold.sql')]}]})
        self.assertEqual(len([n for n in context.derive(self.state, ['gold'])['nodes'] if n['native_id'] == 'model.p.stage']), 2)

    def test_missing_and_dynamic_references_remain_gaps(self):
        self.report = self.make_report(self.source, [('gold', "select * from {{ ref(var('model_name')) }}", ['model.p.missing'])]); self.register()
        result = context.derive(self.state, ['gold'])
        self.assertIn('dependency_unresolved', {g['code'] for g in result['gaps']})
        self.assertTrue(any('dynamic' in g['code'] for g in result['gaps']))
        self.assertNotIn('model.p.missing', {n['native_id'] for n in result['nodes']})
        public = context.public_projection(self.state, ['gold'])
        self.assertTrue(any(e['status'] == 'unresolved' for e in public['edges']))
        self.assertNotIn('model_name', json.dumps(public))

    def test_public_graph_has_complete_scoped_identity_and_safe_svg(self):
        public = context.public_projection(self.state, ['gold'])
        actual = {n['id'] for n in context.derive(self.state, ['gold'])['nodes']}
        self.assertEqual({n['id'] for n in public['nodes']}, actual)
        self.assertEqual(public['generation_entity_ids'], ['gold'])
        self.assertEqual(public['entity_roots'], [{'entity_id': 'gold',
            'root_object_ids': [self.node('model.p.gold')['id']], 'context_object_ids': sorted(actual)}])
        stage, gold = self.node('model.p.stage')['id'], self.node('model.p.gold')['id']
        self.assertTrue(any(e['upstream_id'] == stage and e['consumer_id'] == gold for e in public['edges']))
        for private in ('models/gold.sql', 'manifest.json', 'select * from', str(self.source)):
            self.assertNotIn(private, json.dumps(public))
        svg = context.render_svg(public); tree = ET.fromstring(svg)
        self.assertEqual({e.get('data-source-node-id') for e in tree.iter() if e.get('data-source-node-id')}, actual)
        self.assertNotIn('<style', svg); self.assertNotIn('<script', svg)
        rows = list(csv.DictReader(io.StringIO(context.csv_export(self.state, ['gold']))))
        self.assertEqual({r['object_id'] for r in rows if r['record_type'] == 'object'}, actual)
        self.assertNotIn('model.p.other', context.csv_export(self.state, ['gold']))
        both = context.public_projection(self.state, ['gold', 'other'])
        self.assertEqual(len(next(a for a in both['entity_roots'] if a['entity_id'] == 'other')['context_object_ids']), 1)

    def test_cycles_remain_explicit_without_dropping_graph_nodes(self):
        self.report = self.make_report(self.source, [
            ('gold', "select * from {{ ref('stage') }}", ['model.p.stage']),
            ('stage', "select * from {{ ref('gold') }}", ['model.p.gold'])]); self.register()
        public = context.public_projection(self.state, ['gold'])
        self.assertIn('dependency_cycle', {g['code'] for g in public['gaps']})
        self.assertEqual(len(public['nodes']), 2)
        self.assertEqual(context.render_svg(public).count('data-source-node-id='), 2)

    def test_context_freshness_and_packet_bounds(self):
        before = context.scope_bindings(self.state)['gold']
        with self.assertRaisesRegex(ValueError, 'packet exceeds'):
            context.packet(self.state, ['gold'], max_bytes=1024)
        (self.source / 'models/stage.sql').write_text('select 9 as changed')
        with self.assertRaisesRegex(ValueError, 'bytes changed'):
            context.packet(self.state, ['gold'])
        self.assertNotEqual(before, context.scope_bindings(self.state)['gold'])

    def test_registration_additive_identity_safe_and_contains_no_sql(self):
        original = copy.deepcopy(context.read(self.state))
        context.register(self.state, {'schema_version': 1, 'extracts': []})
        self.assertEqual(original, context.read(self.state))
        with self.assertRaisesRegex(ValueError, 'cannot be reassigned'):
            context.register(self.state, {'schema_version': 1, 'extracts': [{'id': 'legacy', 'root_id': 'target', 'result': self.target_report}]})
        self.assertNotIn('select * from', json.dumps(context.read(self.state)))

    def test_missing_staging_proposal_retains_support_and_does_not_copy(self):
        self.policy(); result = self.record_port(self.row())
        self.assertEqual(result['rows'][0]['status'], 'candidate')
        self.assertEqual(result['rows'][0]['support_file_count'], 3)
        self.assertEqual(result['rows'][0]['target_presence'], 'absent_from_supplied_identity_inventory')
        self.assertFalse((self.target / 'models/staging/stage.sql').exists())
        ports.register(self.state, {'schema_version': 1, 'domain_id': 'sales', 'rows': []})
        self.assertEqual(len(ports.summarize(self.state)['rows']), 1)
        self.assertNotIn('models/schema.yml', ports.csv_export(self.state))
        self.assertEqual(ports.summarize(self.state, ['other'])['rows'], [])
        self.target_report = self.make_report(self.target, [('stage', 'select 1 as id', [])]); self.register()
        self.assertEqual(ports.summarize(self.state)['rows'][0]['status'], 'stale')

    def test_compatible_target_preferred_and_requires_all_dimensions(self):
        self.target_report = self.make_report(self.target, [('stage', 'select 1 as id', [])]); self.register(); self.policy()
        row = self.row()
        with self.assertRaisesRegex(ValueError, 'present target is not missing'):
            self.record_port(row)
        target = self.node('model.p.stage', 'target')['id']
        row.update(decision='reuse_target', target_object_id=target)
        row.pop('candidate_path')
        with self.assertRaisesRegex(ValueError, 'compatible target'):
            self.record_port(row)
        row['comparisons'] = {target: {d: {'status': 'compatible', 'evidence_refs': [self.pin('@sources/target/models/stage.sql')]} for d in DIMENSIONS}}
        public = self.record_port(row)['rows'][0]
        self.assertEqual(public['compatibility'], 'evidence_recorded')
        self.assertEqual((public['target_root_id'], public['target_native_id']), ('target', 'model.p.stage'))
        self.assertIn('target_native_id', ports.csv_export(self.state))

    def test_newer_uses_explicit_ordered_evidence(self):
        self.target_report = self.make_report(self.target, [('stage_v1', 'select 1 as id', []), ('stage_v2', 'select 2 as id', [])]); self.register(); self.policy('explicit_order')
        row = self.row(); row.pop('candidate_path'); row['decision'] = 'reuse_target'
        row['target_native_ids'] = ['model.p.stage_v1', 'model.p.stage_v2']
        targets = [self.node(n, 'target')['id'] for n in row['target_native_ids']]
        row['target_object_id'] = targets[1]
        row['comparisons'] = {k: {d: {'status': 'compatible', 'evidence_refs': [self.pin('@sources/target/models/stage_v%d.sql' % (i + 1))]} for d in DIMENSIONS} for i, k in enumerate(targets)}
        with self.assertRaisesRegex(ValueError, 'explicit ordered evidence'):
            self.record_port(row)
        row['version_order'] = [{'object_id': k, 'rank': i, 'evidence_refs': [self.pin('@sources/target/models/stage_v%d.sql' % (i + 1))]} for i, k in enumerate(targets)]
        self.assertEqual(self.record_port(row)['rows'][0]['version_status'], 'explicit_order_recorded')
        row['target_object_id'] = targets[0]
        with self.assertRaisesRegex(ValueError, 'newer compatible'):
            self.record_port(row)

    def test_public_port_csv_neutralizes_leading_whitespace_formulas(self):
        self.policy(); row = self.row(); row['id'] = ' \t =1+1'
        self.record_port(row)
        result = list(csv.DictReader(io.StringIO(ports.csv_export(self.state))))
        self.assertEqual(result[0]['id'], "' \t =1+1")

    def test_outside_scope_and_stale_port_evidence_are_rejected(self):
        self.policy(); row = self.row(); row['model_ids'] = ['other']
        with self.assertRaises(ValueError): self.record_port(row)
        row = self.row(); row['source_object_id'] = self.node('model.p.gold')['id']
        with self.assertRaisesRegex(ValueError, 'exact staging object'):
            self.record_port(row)
        self.record_port(self.row())
        (self.source / 'models/schema.yml').write_text('version: 2\nmodels: []\n')
        self.assertEqual(ports.summarize(self.state)['rows'][0]['status'], 'stale')
        with self.assertRaisesRegex(ValueError, 'bytes changed'):
            self.record_port(self.row())

    def test_old_engagement_is_unchanged_without_companions(self):
        self.state['workflow'].pop('upstream_context'); before = copy.deepcopy(self.state)
        self.assertEqual(context.derive(self.state, ['gold'])['status'], 'unassessed')
        self.assertEqual(context.scope_bindings(self.state), {})
        self.assertEqual(ports.summarize(self.state)['status'], 'unassessed')
        self.assertEqual(ports.scope_bindings(self.state), {})
        self.assertEqual(self.state, before)


if __name__ == '__main__': unittest.main()
