"""Domain review page: page-data contract, projection, rendering and the review folder layout."""
from contextlib import redirect_stdout
import copy
import io
import csv
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import domain_review_page as page_module

HAS_SQLGLOT = importlib.util.find_spec('sqlglot') is not None
HAS_YAML = importlib.util.find_spec('yaml') is not None
NODE = shutil.which('node')


def review(domain='orders', other='customers'):
    """A small synthetic review: one owned pipeline, one shared dimension, one legacy change."""
    gold_fct, gold_dim, shared = f'wh_{domain}__{domain}_fct', f'wh_{domain}__channel_dim', f'wh_{other}__{other}_dim'
    return {
        'schema_version': 1, 'title': f'{domain.capitalize()} data model review',
        'target': {'framework': 'dbt', 'warehouse': 'duckdb'},
        'omni_warehouse_bindings': [{'view_id': n, 'model_ids': [n]} for n in (gold_fct, shared)],
        'review_meta': {'domain_position': f'{domain.capitalize()} domain',
                        'repositories': [{'role': 'Tooling', 'name': 'accelerator', 'commit': 'abcdef1234567', 'fingerprint': None}]},
        'models': [
            {'id': f'stg_shop__{domain}', 'layer': 'bronze', 'domain': domain, 'status': 'new', 'grain': 'one row per source row',
             'columns': [{'name': f'{domain}_id', 'type': 'string', 'key': 'primary', 'description': 'Source key.'}]},
            {'id': f'int_{domain}__{domain}', 'layer': 'silver', 'domain': domain, 'disposition': 'create',
             'depends_on': [f'stg_shop__{domain}'], 'columns': [{'name': f'{domain}_natural_key'}]},
            {'id': gold_fct, 'layer': 'gold', 'domain': domain, 'status': 'changed', 'grain': 'one row per order',
             'depends_on': [f'int_{domain}__{domain}'],
             'columns': [{'name': f'{domain}_pk', 'key': 'primary', 'description': 'Primary key.'},
                         {'name': 'customer_fk', 'key': 'foreign', 'description': 'Customer.'},
                         {'name': 'channel_fk', 'key': 'foreign', 'description': 'Channel.'}]},
            {'id': gold_dim, 'layer': 'gold', 'domain': domain, 'status': 'reused',
             'columns': [{'name': 'channel_pk', 'key': 'primary'}]},
            {'id': shared, 'layer': 'gold', 'domain': other, 'status': 'reused',
             'columns': [{'name': 'customer_pk', 'key': 'primary'}]}],
        'relationships': [
            {'from': f'stg_shop__{domain}', 'to': f'int_{domain}__{domain}', 'kind': 'lineage'},
            {'from': gold_fct, 'to': shared, 'kind': 'relationship', 'label': 'customer_fk = customer_pk (many_to_one)'},
            {'from': gold_fct, 'to': gold_dim, 'kind': 'relationship', 'from_columns': ['channel_fk'],
             'to_columns': ['channel_pk'], 'cardinality': 'many_to_one'}],
        'changes': [{'id': 'CH-01', 'source': f'legacy: mart__{domain}', 'disposition': 'reuse_existing', 'target': gold_fct,
                     'rationale': 'Same grain.'},
                    {'id': 'CH-02', 'source': f'legacy: mart__{domain}_daily', 'disposition': 'unresolved', 'rationale': 'No definition.'}],
        'decisions': [{'id': 'D-01', 'question': 'Placement', 'status': 'recorded', 'answer': 'Channels stay in this domain.'},
                      {'id': 'OQ-01', 'question': 'Who owns the new models?', 'status': 'open', 'answer': None}],
        'validation': [{'id': 'V-01', 'label': 'Every YAML file parses', 'scope': 'static', 'status': 'pass', 'expected': 'pass', 'actual': 'pass'},
                       {'id': 'V-02', 'label': 'Row counts reconcile', 'scope': 'warehouse', 'status': 'pending', 'actual': 'not run'}],
        'assets': [{'id': 'A-dashboard_7', 'name': 'dashboard 7: Order health', 'kind': 'bi_dashboard', 'mapping_status': 'partly_served',
                    'topics': [domain]},
                   {'id': 'A-look_9', 'name': 'look 9: Old list', 'kind': 'bi_look', 'mapping_status': 'out_of_scope'}]}


def files(domain='orders', other='customers'):
    gold_fct, gold_dim, shared = f'wh_{domain}__{domain}_fct', f'wh_{domain}__channel_dim', f'wh_{other}__{other}_dim'
    base = '02_dbt/project/models/'
    return [
        {'path': base + f'staging/stg_shop__{domain}.sql', 'status': 'new',
         'content': f"select * from {{{{ source('shop', '{domain}') }}}}\n"},
        {'path': base + f'integration/int_{domain}__{domain}.sql', 'status': 'new',
         'content': f"select * from {{{{ ref('stg_shop__{domain}') }}}}\n"},
        {'path': base + f'warehouse/{gold_fct}.sql', 'status': 'changed', 'content': f"select * from {{{{ ref('int_{domain}__{domain}') }}}}\n"},
        {'path': base + f'_{domain}_schema.yml', 'status': 'new', 'content': 'version: 2\nmodels:\n'
         + ''.join(f'  - name: {n}\n' for n in (f'stg_shop__{domain}', f'int_{domain}__{domain}', gold_fct))},
        {'path': f'03_omni/model/views/{gold_fct}.view', 'status': 'new',
         'content': f'table_name: {gold_fct}\ndimensions:\n  {domain}_pk:\n    primary_key: true\n'},
        {'path': f'03_omni/model/views/{shared}.view', 'status': 'new', 'content': f'table_name: {shared}\n'},
        {'path': '03_omni/model/views/unbound_lookup.view', 'status': 'new', 'content': 'table_name: not_in_review\n'},
        {'path': '03_omni/model/relationships/relationships.yaml', 'status': 'new',
         'content': f'- join_from_view: {gold_fct}\n  join_to_view: {shared}\n  relationship_type: many_to_one\n  join_type: left\n'
                    f'  on_sql: ${{{gold_fct}.customer_fk}} = ${{{shared}.customer_pk}}\n'},
        {'path': f'03_omni/model/topics/{domain}.topic', 'status': 'new',
         'content': f'base_view: {gold_fct}\nlabel: {domain.capitalize()}\ndescription: One row per order.\n'
                    f'joins:\n  {shared}: {{}}\n  unbound_lookup: {{}}\n# TODO owners: not supplied\n'}]


def semantic_context(domain='orders', other='customers'):
    from test_omni_contract import context
    value = context(); value['bindings'] = {}
    for name in (f'wh_{domain}__{domain}_fct', f'wh_{other}__{other}_dim'):
        value['bindings'][name] = {'namespace': {'database': 'ANALYTICS', 'schema': 'GOLD', 'table': name},
                                   'columns': {domain + '_pk': 'number', 'customer_fk': 'number', 'customer_pk': 'number'},
                                   'evidence_sha256': 'b' * 64}
    return value


@unittest.skipUnless(HAS_YAML, 'Optional YAML parser unavailable')
class DomainReviewPageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.page = page_module.project(review(), files(), model_context=semantic_context())

    @unittest.skipUnless(HAS_SQLGLOT, 'Pinned SQL runtime required for resolved semantic bindings')
    def test_projection_derives_counts_areas_and_bindings_from_the_review(self):
        page = self.page
        self.assertEqual(page['meta']['domain'], 'orders')
        self.assertEqual(page['cards']['layers']['gold'], {'create': 0, 'extend': 1, 'reuse': 2, 'unassessed': 0})
        self.assertEqual(page['cards']['code'], {'new': 3, 'changed': 1, 'new_sql': 2, 'changed_sql': 1, 'unassessed': 0})
        own, shared = page['areas']
        self.assertEqual(own['gold'], ['wh_orders__channel_dim', 'wh_orders__orders_fct'])
        self.assertTrue(set(own['gold']) <= set(own['pipeline']))
        self.assertIn('stg_shop__orders', own['pipeline'])
        self.assertTrue(shared['shared'])
        self.assertEqual(shared['pipeline'], [])
        topic = page['topics'][0]
        self.assertEqual(topic['base_model_ids'], ['wh_orders__orders_fct'])
        self.assertEqual(topic['area'], own['id'])
        self.assertEqual({n['view_id'] for n in topic['nodes']},
                         {'wh_orders__orders_fct', 'wh_customers__customers_dim', 'unbound_lookup'})
        self.assertEqual(next(j for j in topic['joins'] if j['to'] == next(n['id'] for n in topic['nodes']
                         if n['view_id'] == 'wh_customers__customers_dim'))['card'], 'many_to_one')
        self.assertEqual(next(n for n in topic['nodes'] if n['view_id'] == 'unbound_lookup')['binding_status'], 'gap')
        self.assertEqual(page['apply']['new_sources'], ['shop.orders'])
        self.assertEqual([p['label'] for p in page['apply']['placeholders']], ['TODO owners'])
        rel = next(r for r in page['rels'] if r['to'] == 'wh_customers__customers_dim')
        self.assertEqual((rel['key'], rel['card']), ('customer_fk = customer_pk', 'many_to_one'))

    def test_gold_relationships_include_declared_tests_and_key_names(self):
        value, packaged = review(), files()
        value['models'].append({'id': 'wh_orders__orders_daily_xa', 'layer': 'gold', 'domain': 'orders', 'status': 'new',
                                'columns': [{'name': 'orders_daily_pk', 'key': 'primary'},
                                            {'name': 'customer_fk', 'key': 'foreign'}, {'name': 'channel_fk', 'key': 'foreign'},
                                            {'name': 'region_fk', 'key': 'foreign'}]})
        packaged.append({'path': '02_dbt/project/models/warehouse/_orders_daily_schema.yml', 'status': 'new', 'content': (
            'version: 2\nmodels:\n  - name: wh_orders__orders_daily_xa\n    columns:\n      - name: customer_fk\n'
            '        data_tests:\n          - common.relationships_in_past_time_window:\n              arguments:\n'
            "                to: ref('wh_customers__customers_dim')\n                field: customer_pk\n")})
        page = page_module.project(value, packaged)
        daily = {(r['to'], r['basis']) for r in page['rels'] if r['from'] == 'wh_orders__orders_daily_xa'}
        # The declared test wins over the matching key name; region_fk has no gold owner and stays unjoined.
        self.assertEqual(daily, {('wh_customers__customers_dim', 'declared test'), ('wh_orders__channel_dim', 'key name match')})
        fact = {(r['to'], r['basis']) for r in page['rels'] if r['from'] == 'wh_orders__orders_fct'}
        self.assertEqual(fact, {('wh_customers__customers_dim', 'review'), ('wh_orders__channel_dim', 'review')})
        own = page['areas'][0]
        self.assertIn('wh_orders__orders_daily_xa', own['erd'])
        self.assertEqual(page['cards']['semantic']['relationships'], 1)
        warehouse_review = copy.deepcopy(value)
        warehouse_review['assets'] = []
        no_semantic = page_module.project(warehouse_review, [f for f in packaged if f['path'].startswith('02_dbt/')])
        self.assertEqual(no_semantic['cards']['semantic']['relationships'], 0)
        without = page_module.project(value, packaged, infer_keys=False)
        self.assertNotIn('key name match', {r['basis'] for r in without['rels']})
        bad = copy.deepcopy(page)
        bad['rels'][0]['basis'] = 'guess'
        with self.assertRaisesRegex(ValueError, 'Relationship basis'):
            page_module.normalise(bad)

    def test_dashboards_legacy_decisions_and_open_items(self):
        page = self.page
        self.assertEqual([(d['asset_type'], d['asset_id'], d['title'], d['status']) for d in page['dashboards']],
                         [('dashboard', '7', 'Order health', 'partly_served')])
        self.assertEqual(page['topics'][0]['dashboards'], [{'id': '7', 'title': 'Order health', 'status': 'partly_served'}])
        self.assertEqual({r['legacy']: r['status'] for r in page['legacy']}, {'mart__orders': 'covered', 'mart__orders_daily': 'unresolved'})
        self.assertEqual({d['id']: d['status'] for d in page['decisions']}, {'D-01': 'assumed', 'OQ-01': 'open'})
        kinds = sorted((o['kind'], o['id']) for o in page['open'])
        self.assertEqual(kinds, [('Question', 'OQ-01'), ('Semantic gap', 'orders'), ('Unresolved legacy model', 'mart__orders_daily'), ('Unverified', 'V-02')])
        self.assertTrue(all(o['owner'] == 'Not assigned' for o in page['open']))
        self.assertEqual([s['count'] for s in page['static']], [0, 0, 0, 0, 0])

    def test_semantics_never_bind_by_matching_view_or_table_name(self):
        value = review(); value.pop('omni_warehouse_bindings')
        page = page_module.project(value, files(), model_context=semantic_context())
        topic = page['topics'][0]
        self.assertEqual(topic['base_model_ids'], [])
        self.assertTrue(all(n['binding_status'] == 'gap' for n in topic['nodes']))
        self.assertIn('Semantic gap', [o['kind'] for o in page['open']])
        # Missing catalogue/context leaves a usable provisional package, never an implicit binding.
        provisional = page_module.project(review(), files())
        self.assertEqual(provisional['topics'][0]['base_model_ids'], [])
        page_module.write_package(provisional, self.root / 'provisional')

    @unittest.skipUnless(HAS_SQLGLOT, 'Pinned SQL runtime required for resolved semantic bindings')
    def test_semantic_projection_matches_canonical_aliases_and_reverse_rules(self):
        from test_omni_contract import context, files as omni_files
        from omni_topic_trees import build_topic_trees
        import yaml
        candidate = omni_files()
        candidate['events.view.yaml'] = candidate.pop('events.view')
        candidate['activity.topic'] = yaml.safe_dump({'base_view': 'buyer', 'joins': {'events': {}},
            'views': {'buyer': {'extends': ['events']}}, 'relationships': [
                {'join_from_view': 'events', 'join_to_view': 'buyer', 'relationship_type': 'many_to_one',
                 'join_type': 'left', 'reversible': True, 'on_sql': '${events.id} = ${buyer.id}'}]})
        models = {'gold.events': {'id': 'gold.events', 'layer': 'gold', 'domain': 'activity'}}
        bindings = [{'view_id': 'events', 'model_ids': ['gold.events']}]
        def projected():
            return page_module.semantic_from_files([{'path': k, 'content': v} for k, v in candidate.items()],
                models, warehouse_bindings=bindings, model_context=context())[0][0]
        topic = projected()
        canonical = build_topic_trees(candidate, context(), bindings, list(models.values()))['topics'][0]
        self.assertEqual([n['id'] for n in topic['nodes']], [n['id'] for n in canonical['nodes']])
        self.assertEqual(topic['base_model_ids'], ['gold.events'])
        self.assertEqual(topic['joins'][0]['card'], 'one_to_many')
        self.assertEqual(topic['joins'][0]['direction'], 'reverse')
        candidate['activity.topic'] = candidate['activity.topic'].replace('reversible: true', 'reversible: false')
        topic = projected()
        self.assertEqual(topic['joins'][0]['status'], 'unresolved')
        self.assertEqual(topic['joins'][0]['card'], '')

    def test_missing_coverage_stays_visible_and_unassessed(self):
        value = review()
        del value['assets'][0]['mapping_status']
        page = page_module.project(value, files())
        self.assertEqual(page['dashboards'][0]['status'], 'unassessed')
        self.assertEqual(page['cards']['dashboards']['unassessed'], 1)

    def test_dashboard_counts_reject_markup_and_invalid_numbers(self):
        for field in ('n_query_tiles', 'n_served', 'n_partly_served', 'n_not_served'):
            for value in ('<svg onload="globalThis.reviewPoC=1"></svg>', '1', True, -1, 1.5, 2 ** 53):
                data = copy.deepcopy(self.page)
                data['dashboards'][0][field] = value
                with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, 'safe integer or null'):
                    page_module.render(data)
                with self.assertRaises(ValueError):
                    page_module.write_package(data, self.root / 'invalid')
                self.assertFalse((self.root / 'invalid').exists())
        for value in (None, 0, 12):
            data = copy.deepcopy(self.page)
            data['dashboards'][0]['n_served'] = value
            page_module.check_page(page_module.render(data))

    def test_script_policy_is_bound_to_script_bytes_and_blocks_inline_handlers(self):
        rendered = page_module.render(self.page)
        self.assertIn("script-src-attr 'none'", rendered)
        self.assertNotIn("script-src 'unsafe-inline'", rendered)
        for changed in (rendered.replace('<script>', '<script>globalThis.reviewPoC=1;'),
                        rendered.replace("script-src-attr 'none'", "script-src-attr 'unsafe-inline'")):
            with self.assertRaisesRegex(ValueError, 'hashed script'):
                page_module.check_page(changed)

    def test_contract_rejects_inconsistent_page_data(self):
        cases = [
            (lambda p: p['areas'][0].update(pipeline=['stg_shop__orders']), 'must include its gold tables'),
            (lambda p: p['dashboards'][0]['topics'].append('missing'), 'unknown topic'),
            (lambda p: p['dashboards'][0].update(status='done'), 'Dashboard status'),
            (lambda p: p['rels'].append({'from': 'wh_orders__orders_fct', 'to': 'nowhere'}), 'endpoints'),
            (lambda p: p['legacy'][0].update(targets=[]), 'need a target'),
            (lambda p: p['topics'][0].update(area='elsewhere'), 'Topic area'),
            (lambda p: p['models'][0].update(disp='maybe'), 'disposition'),
            (lambda p: p['files'][0].update(path='../outside.sql'), 'within its declared root'),
            (lambda p: p['meta']['repositories'][0].update(commit='not-a-sha'), 'hexadecimal'),
        ]
        for change, message in cases:
            data = copy.deepcopy(self.page)
            change(data)
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                page_module.normalise(data)

    def test_render_is_self_contained_and_checks_its_counts(self):
        html = page_module.render(self.page)
        self.assertEqual(page_module.check_page(html)['models'], 5)
        self.assertIn("connect-src 'none'", html)
        self.assertNotRegex(html, r'<script[^>]+src=')
        data = page_module.page_data(html)
        data['cards']['semantic']['topics'] = 99
        forged = html.replace(re.search(r'id="domain-review-data">(.*?)</script>', html, re.S).group(1),
                              page_module._encode(data))
        with self.assertRaisesRegex(ValueError, 'Embedded counts differ'):
            page_module.check_page(forged)

    def test_template_is_the_same_for_every_domain(self):
        def shell(html):
            html = re.sub(r'(id="domain-review-data">).*?(</script>)', r'\1\2', html, flags=re.S)
            return re.sub(r'<title>.*?</title>|<b id="brand">.*?</b>', '', html)
        first = page_module.render(self.page)
        second = page_module.render(page_module.project(review('returns', 'stores'), files('returns', 'stores'), model_context=semantic_context('returns', 'stores')))
        self.assertEqual(shell(first), shell(second))
        for word in ('orders', 'customers', 'returns', 'stores'):
            self.assertNotIn(word, shell(first))

    @unittest.skipUnless(NODE, 'Node is not installed')
    def test_page_script_is_valid_javascript(self):
        html = page_module.render(self.page)
        script = re.findall(r'<script>(.*?)</script>', html, re.S)[-1]
        path = self.root / 'page.js'
        path.write_text(script, encoding='utf-8')
        subprocess.run([NODE, '--check', str(path)], check=True, capture_output=True)

    def test_package_writes_the_review_layout_once_and_verifies(self):
        docs = {'DESIGN.md': b'# Design\n', 'model/physical_model_orders.dbml': b'Table a {}\n'}
        out = self.root / 'v1'
        result = page_module.write_package(self.page, out, docs=docs)
        self.assertEqual(Path(result['entrypoint']).name, 'START_HERE.html')
        names = {p.relative_to(out).as_posix() for p in out.rglob('*') if p.is_file()}
        self.assertTrue({'START_HERE.html', 'MANIFEST.csv', '01_review/START_HERE.md', '01_review/erd/orders.mmd',
                         '01_review/erd/shared.mmd', '04_docs/DESIGN.md', '04_docs/model/physical_model_orders.dbml',
                         '02_dbt/project/models/warehouse/wh_orders__orders_fct.sql',
                         '03_omni/model/topics/orders.topic'} <= names)
        self.assertEqual(page_module.verify_package(out)['status'], 'pass')
        markdown = (out / '01_review/START_HERE.md').read_text()
        self.assertIn('1 dashboards in scope: 0 served, 1 partly served, 0 not served.', markdown)
        self.assertIn('wh_orders__orders_fct }o--|| wh_customers__customers_dim', (out / '01_review/erd/orders.mmd').read_text())
        with self.assertRaisesRegex(ValueError, 'Output exists'):
            page_module.write_package(self.page, out)
        (out / '04_docs/DESIGN.md').write_text('# Edited\n')
        with self.assertRaisesRegex(ValueError, 'File changed after packaging'):
            page_module.verify_package(out)
        self.assertFalse([p for p in self.root.iterdir() if p.name.startswith('.v1.')])

    def test_package_keeps_code_inside_the_layout(self):
        data = copy.deepcopy(self.page)
        data['files'].append({'path': 'elsewhere/model.sql', 'status': 'new', 'content': 'select 1\n'})
        with self.assertRaisesRegex(ValueError, 'Packaged code must live under'):
            page_module.write_package(data, self.root / 'v2')
        self.assertFalse((self.root / 'v2').exists())

    def test_artifact_files_are_bound_to_their_registered_hashes(self):
        source = self.root / 'artifacts'
        (source / 'dbt/models').mkdir(parents=True)
        (source / 'dbt/models/a.sql').write_text('select 1\n')
        import hashlib
        record = {'id': 'a', 'path': 'dbt/models/a.sql', 'category': 'implementation',
                  'sha256': hashlib.sha256(b'select 1\n').hexdigest()}
        rows = page_module.files_from_artifacts({'artifacts': [record]}, source, {'dbt/': '02_dbt/'}, changed=['dbt/models/a.sql'])
        self.assertEqual(rows, [{'path': '02_dbt/models/a.sql', 'status': 'changed', 'content': 'select 1\n'}])
        (source / 'dbt/models/a.sql').write_text('select 2\n')
        with self.assertRaisesRegex(ValueError, 'Artifact changed'):
            page_module.files_from_artifacts({'artifacts': [record]}, source, {'dbt/': '02_dbt/'})
        with self.assertRaisesRegex(ValueError, 'path map target'):
            page_module.files_from_artifacts({'artifacts': [record]}, source, {'dbt/': 'code/'})

    def test_command_line_round_trip(self):
        data = self.root / 'page.json'
        data.write_text(json.dumps(self.page))
        page, folder = self.root / 'START_HERE.html', self.root / 'v3'
        with redirect_stdout(io.StringIO()):
            self.assertEqual(page_module.main(['render', '--data', str(data), '--output', str(page)]), 0)
            self.assertEqual(page_module.main(['check-page', str(page)]), 0)
            self.assertEqual(page_module.main(['package', '--data', str(data), '--output', str(folder)]), 0)
            self.assertEqual(page_module.main(['verify', str(folder)]), 0)

@unittest.skipUnless(HAS_YAML, 'Optional YAML parser unavailable')
class DomainReviewPromoteTests(unittest.TestCase):
    """A version folder is written once, from a draft that an independent review covered byte for byte."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.domain = self.root / 'Orders'
        self.domain.mkdir()
        self.page = page_module.project(review(), files(), model_context=semantic_context())
        self.draft = self.root / 'work' / 'draft-1'
        self.draft.parent.mkdir()
        page_module.write_package(self.page, self.draft, docs={'DESIGN.md': b'# Design\n'})

    def record(self, draft=None, findings=None):
        return {'schema_version': 1, 'kind': page_module.REVIEW_KIND, 'reviewer': 'independent agent, fresh context',
                'scope': 'packaged SQL and schema YAML', 'draft_manifest_sha256': page_module.manifest_sha256(draft or self.draft),
                'findings': findings if findings is not None else [
                    {'id': 'R-1', 'severity': 'wrong_numbers', 'summary': 'Duplicate join rows', 'disposition': 'fixed'},
                    {'id': 'R-2', 'severity': 'minor', 'summary': 'Naming', 'disposition': 'accepted', 'note': 'Matches the existing column.'}]}

    def test_promote_writes_the_next_version_with_the_review_and_verifies(self):
        self.assertEqual(page_module.next_version(self.domain), 'v1')
        result = page_module.promote(self.draft, self.record(), self.domain / 'v1')
        out = self.domain / 'v1'
        self.assertEqual(result['review'], {'findings': 2, 'fixed': 1, 'accepted': 1, 'deferred': 0})
        self.assertEqual(page_module.verify_package(out)['status'], 'pass')
        stored = json.loads((out / '04_docs/INDEPENDENT_REVIEW.json').read_text())
        self.assertEqual(stored['draft_manifest_sha256'], page_module.manifest_sha256(self.draft))
        draft_files = {p.relative_to(self.draft).as_posix(): p.read_bytes() for p in self.draft.rglob('*') if p.is_file() and p.name != 'MANIFEST.csv'}
        for name, content in draft_files.items():
            self.assertEqual((out / name).read_bytes(), content)
        self.assertEqual(page_module.next_version(self.domain), 'v2')
        self.assertFalse([p for p in self.domain.iterdir() if p.name.startswith('.v1.')])

    def test_promote_refuses_a_review_of_other_bytes(self):
        other = self.root / 'work' / 'draft-0'
        page_module.write_package(self.page, other, docs={'DESIGN.md': b'# Earlier design\n'})
        with self.assertRaisesRegex(ValueError, 'different draft'):
            page_module.promote(self.draft, self.record(draft=other), self.domain / 'v1')
        self.assertFalse((self.domain / 'v1').exists())

    def test_promote_refuses_open_findings_unfixed_blockers_and_bare_acceptances(self):
        cases = [([{'id': 'R-1', 'severity': 'minor', 'summary': 's', 'disposition': 'open'}], 'still open'),
                 ([{'id': 'R-1', 'severity': 'blocker', 'summary': 's', 'disposition': 'accepted', 'note': 'n'}], 'Blocker must be fixed'),
                 ([{'id': 'R-1', 'severity': 'minor', 'summary': 's', 'disposition': 'deferred'}], 'need a note'),
                 ([{'id': 'R-1', 'severity': 'severe', 'summary': 's', 'disposition': 'fixed'}], 'severity must be')]
        for findings, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                page_module.promote(self.draft, self.record(findings=findings), self.domain / 'v1')
        self.assertEqual(page_module.next_version(self.domain), 'v1')

    def test_promote_only_writes_the_next_free_version_and_never_overwrites(self):
        with self.assertRaisesRegex(ValueError, 'next version: v1'):
            page_module.promote(self.draft, self.record(), self.domain / 'v2')
        with self.assertRaisesRegex(ValueError, 'named v<N>'):
            page_module.promote(self.draft, self.record(), self.domain / 'final')
        page_module.promote(self.draft, self.record(), self.domain / 'v1')
        with self.assertRaisesRegex(ValueError, 'never overwritten'):
            page_module.promote(self.draft, self.record(), self.domain / 'v1')

    def test_promote_refuses_a_draft_that_changed_after_packaging(self):
        record = self.record()
        (self.draft / '04_docs/DESIGN.md').write_text('# Edited after review\n')
        with self.assertRaisesRegex(ValueError, 'File changed after packaging'):
            page_module.promote(self.draft, record, self.domain / 'v1')
        self.assertFalse((self.domain / 'v1').exists())

    def test_command_line_draft_review_promote(self):
        review_path = self.root / 'review.json'
        review_path.write_text(json.dumps(self.record(findings=[])))
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(page_module.main(['next-version', str(self.domain)]), 0)
        self.assertEqual(json.loads(out.getvalue())['next'], 'v1')
        with redirect_stdout(io.StringIO()):
            self.assertEqual(page_module.main(['promote', '--draft', str(self.draft), '--review', str(review_path),
                                               '--output', str(self.domain / 'v1')]), 0)
            self.assertEqual(page_module.main(['verify', str(self.domain / 'v1')]), 0)


if __name__ == '__main__':
    unittest.main()
