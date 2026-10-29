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

HAS_YAML = importlib.util.find_spec('yaml') is not None
NODE = shutil.which('node')


def review(domain='orders', other='customers'):
    """A small synthetic review: one owned pipeline, one shared dimension, one legacy change."""
    gold_fct, gold_dim, shared = f'wh_{domain}__{domain}_fct', f'wh_{domain}__channel_dim', f'wh_{other}__{other}_dim'
    return {
        'schema_version': 1, 'title': f'{domain.capitalize()} data model review',
        'target': {'framework': 'dbt', 'warehouse': 'duckdb'},
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
         'content': f'- join_from_view: {gold_fct}\n  join_to_view: {shared}\n  relationship_type: many_to_one\n'
                    f'  on_sql: ${{{gold_fct}.customer_fk}} = ${{{shared}.customer_pk}}\n'},
        {'path': f'03_omni/model/topics/{domain}.topic', 'status': 'new',
         'content': f'base_view: {gold_fct}\nlabel: {domain.capitalize()}\ndescription: One row per order.\n'
                    f'joins:\n  {shared}: {{}}\n  unbound_lookup: {{}}\n# TODO owners: not supplied\n'}]


@unittest.skipUnless(HAS_YAML, 'Optional YAML parser unavailable')
class DomainReviewPageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.page = page_module.project(review(), files())

    def test_projection_derives_counts_areas_and_bindings_from_the_review(self):
        page = self.page
        self.assertEqual(page['meta']['domain'], 'orders')
        self.assertEqual(page['cards']['layers']['gold'], {'create': 0, 'extend': 1, 'reuse': 2})
        self.assertEqual(page['cards']['code'], {'new': 3, 'changed': 1, 'new_sql': 2, 'changed_sql': 1})
        own, shared = page['areas']
        self.assertEqual(own['gold'], ['wh_orders__channel_dim', 'wh_orders__orders_fct'])
        self.assertTrue(set(own['gold']) <= set(own['pipeline']))
        self.assertIn('stg_shop__orders', own['pipeline'])
        self.assertTrue(shared['shared'])
        self.assertEqual(shared['pipeline'], [])
        topic = page['topics'][0]
        self.assertEqual(topic['base'], 'wh_orders__orders_fct')
        self.assertEqual(topic['area'], own['id'])
        # A view binds to a model only through table_name; the unbound view stays visible as itself.
        self.assertEqual({j['to'] for j in topic['joins']}, {'wh_customers__customers_dim', 'unbound_lookup'})
        self.assertEqual(next(j for j in topic['joins'] if j['to'] == 'wh_customers__customers_dim')['card'], 'many_to_one')
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
        self.assertEqual(kinds, [('Question', 'OQ-01'), ('Unresolved legacy model', 'mart__orders_daily'), ('Unverified', 'V-02')])
        self.assertTrue(all(o['owner'] == 'Not assigned' for o in page['open']))
        self.assertEqual([s['count'] for s in page['static']], [0, 0, 0, 0, 0])

    def test_every_dashboard_needs_a_coverage_status(self):
        value = review()
        del value['assets'][0]['mapping_status']
        with self.assertRaisesRegex(ValueError, 'coverage status'):
            page_module.project(value, files())

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
        second = page_module.render(page_module.project(review('returns', 'stores'), files('returns', 'stores')))
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

@unittest.skipUnless(HAS_YAML and importlib.util.find_spec('playwright'), 'Optional browser check unavailable')
class DomainReviewPageBrowserTests(unittest.TestCase):
    def test_every_view_and_inspector_renders_without_script_errors(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'START_HERE.html'
            path.write_text(page_module.render(page_module.project(review(), files())), encoding='utf-8')
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                tab = browser.new_page()
                errors = []
                tab.on('pageerror', lambda error: errors.append(str(error)))
                tab.goto(path.as_uri())
                for view in page_module.VIEWS:
                    tab.click(f'#nav button[data-v="{view}"]')
                    self.assertTrue(tab.is_visible(f'#v-{view}'))
                tab.click('#nav button[data-v="model"]')
                tab.click('#abody .nd')
                self.assertTrue(tab.is_visible('#insp'))
                browser.close()
            self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
