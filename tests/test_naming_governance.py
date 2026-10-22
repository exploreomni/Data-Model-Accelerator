"""Synthetic naming decisions preserve identity; no catalogue or deployment claim."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import naming_governance as naming
import test_engagement_stages as fixtures


class NamingGovernanceTests(unittest.TestCase):
    def setUp(self):
        design = fixtures.candidate()
        for entity in design['entities']:
            entity['name'] = ('fct_' if entity['id'] == 'orders' else 'dim_') + entity['id']
        self.state = {'answers': {'naming_policy': 'preserve'}, 'workflow': {
            'schema_version': 1, 'design': design, 'approvals': [], 'runs': []}}

    def policy(self, **values):
        return dict(schema_version=1, profile='abbreviated', platform='snowflake', **values)

    def select(self, policy=None, **values):
        return naming.configure(self.state, dict(schema_version=1, policy=policy or self.policy(),
            decision_reference='host-request:synthetic-selection', **values))

    def entity(self, identity):
        return next(e for e in self.state['workflow']['design']['entities'] if e['id'] == identity)

    def resource(self, identity='orders', **values):
        entity = self.entity(identity)
        row = {'id': 'resource:' + identity, 'entity_id': identity, 'source_id': 'legacy.' + identity,
               'original_name': identity, 'target_name': entity['name'], 'physical_alias': None,
               'source_relation': None, 'existing': False, 'layer': entity['layer'],
               'role': 'fact' if identity == 'orders' else 'dimension', 'business_stem': identity,
               'domain': 'commerce', 'namespace': ['database', 'analytics'], 'evidence_refs': ['evidence:' + identity]}
        row.update(values)
        return row

    def register(self, rows=None, **values):
        return naming.register(self.state, dict(schema_version=1,
            resources=rows or [self.resource(e['id']) for e in self.state['workflow']['design']['entities']], **values))

    def test_absent_companion_is_noop_and_does_not_replace_legacy_policy(self):
        before = copy.deepcopy(self.state)
        self.assertEqual(naming.summarize(self.state)['status'], 'unassessed')
        self.assertEqual(naming.scope_bindings(self.state), {})
        self.assertEqual(naming.stage_requirements(self.state, ['orders']), [])
        self.assertEqual(naming.records(self.state), [])
        self.assertEqual(self.state, before)
        self.select(); self.register()
        self.assertEqual(self.state['answers']['naming_policy'], 'preserve')
        self.assertFalse(naming.summarize(self.state)['deployment_authorized'])
        self.assertEqual(self.state['workflow']['approvals'], [])

    def test_optional_column_key_rules_use_canonical_bindings_and_only_affected_scope(self):
        orders = self.entity('orders')
        orders['columns'].append({'name': 'customers_id', 'type': 'integer', 'description': 'Explicit customer key'})
        edge = self.state['workflow']['design']['relationships'][0]
        edge.update(from_columns=['customers_id'], to_columns=['customers_id'])
        self.select(); self.register()
        before = naming.scope_bindings(self.state)
        rules = {'fact': {'case': 'lower_snake', 'primary_key': {'suffix': '_id'},
                          'foreign_key': {'suffix': '_id'}}}
        selected = dict(self.policy(), column_rules=rules)
        result = self.select(selected, change_reference='host-request:column-conventions')
        self.assertEqual(result['invalidated_entity_ids'], ['orders'])
        self.assertEqual(naming.stage_requirements(self.state, ['orders']), [])
        self.assertEqual(before['customers'], naming.scope_bindings(self.state)['customers'])
        pinned = naming.scope_bindings(self.state)
        orders['columns'].append({'name': 'GrossAmount', 'type': 'numeric', 'description': 'Synthetic amount'})
        orders['keys'] = ['GrossAmount']
        edge['from_columns'] = ['GrossAmount']
        gaps = naming.stage_requirements(self.state, ['orders'])
        self.assertTrue(any('column_case_nonconforming:GrossAmount' in g for g in gaps))
        self.assertTrue(any('primary_key_nonconforming:GrossAmount' in g for g in gaps))
        self.assertTrue(any('foreign_key_nonconforming:GrossAmount' in g for g in gaps))
        self.assertNotEqual(pinned['orders'], naming.scope_bindings(self.state)['orders'])
        self.assertEqual(pinned['products'], naming.scope_bindings(self.state)['products'])
        del edge['from_columns']; del edge['to_columns']
        self.assertTrue(any('foreign_key_binding_unassessed' in g for g in naming.stage_requirements(self.state, ['orders'])))
        self.assertEqual(orders['columns'][-1]['name'], 'GrossAmount')  # Inspection never renames.

    def test_optional_rules_are_bounded_and_preserve_existing_and_source_identifiers(self):
        invalid = [
            {'folder_patterns': {'fact': '../models'}}, {'folder_patterns': {'fact': '/models'}},
            {'folder_patterns': {'fact': 'models/{domain.__class__}'}},
            {'folder_patterns': {'fact': 'models/{domain!r}'}},
            {'column_rules': {'fact': {'case': 'arbitrary-regex'}}},
            {'column_rules': {'fact': {'primary_key': {'suffix': '.*'}}}},
            {'column_rules': {'source': {'case': 'lower_snake'}}}]
        for addition in invalid:
            with self.subTest(addition=addition), self.assertRaises(ValueError):
                naming.validate_policy(dict(self.policy(), **addition))
        self.select(); self.register()
        # Declared retained reuse remains protected even when its registry row was new.
        self.entity('orders')['disposition'] = 'reuse'
        self.entity('orders')['columns'][0]['name'] = 'Original Key'
        self.entity('orders')['keys'] = ['Original Key']
        orders = next(r for r in naming.records(self.state) if r['entity_id'] == 'orders')
        before = naming.scope_bindings(self.state)
        policy = dict(self.policy(), folder_patterns={'fact': 'models/{domain}/{layer}'},
                      column_rules={'fact': {'case': 'lower_snake', 'primary_key': {'suffix': '_id'}}})
        result = self.select(policy, change_reference='host-request:optional-conventions')
        self.assertEqual(result['invalidated_entity_ids'], [])
        self.assertIsNone(naming.folder_requirement(self.state, orders))
        self.assertEqual(before, naming.scope_bindings(self.state))
        protected = copy.deepcopy(orders); protected['existing'] = True
        self.entity('orders')['disposition'] = 'create'
        self.assertIsNone(naming.folder_requirement(self.state, protected))
        protected['existing'] = False; protected['role'] = 'source'
        self.assertIsNone(naming.folder_requirement(self.state, protected))

    def test_profiles_produce_exact_names_without_guessing_business_stems(self):
        cases = [
            ({'profile': 'abbreviated'}, 'staging', 'silver', 'stg_orders', 'analytics'),
            ({'profile': 'abbreviated'}, 'intermediate', 'silver', 'int_orders', 'analytics'),
            ({'profile': 'abbreviated'}, 'mart', 'gold', 'mart_orders', 'analytics'),
            ({'profile': 'expanded', 'fact_pattern': '{business_stem}_fact'}, 'fact', 'gold', 'orders_fact', 'analytics'),
            ({'profile': 'expanded', 'fact_pattern': 'fact_{business_stem}'}, 'intermediate', 'silver', 'intermediate_orders', 'analytics'),
            ({'profile': 'expanded', 'fact_pattern': 'fact_{business_stem}'}, 'dimension', 'gold', 'dim_orders', 'analytics'),
            ({'profile': 'medallion'}, 'fact', 'gold', 'gold_orders', 'analytics'),
            ({'profile': 'medallion', 'medallion_placement': 'schema'}, 'fact', 'gold', 'orders', 'gold'),
            ({'profile': 'medallion', 'include_raw': True}, 'staging', 'raw', 'raw_orders', 'analytics'),
            ({'profile': 'preserve'}, 'fact', 'gold', 'orders', 'analytics')]
        for options, role, layer, target, namespace in cases:
            with self.subTest(options=options, role=role):
                self.setUp(); entity = self.entity('orders')
                entity.update(name=target, layer=layer, object_kind='model')
                self.select(dict(schema_version=1, platform='snowflake', **options))
                self.register([self.resource(role=role, namespace=['database', namespace])])
                self.assertEqual(naming.stage_requirements(self.state, ['orders']), [])
                self.assertEqual(naming.summarize(self.state, ['orders'])['resources'][0]['expected_name'], target)

    def test_custom_template_is_explicit_and_unsafe_formatting_is_rejected(self):
        self.entity('orders')['name'] = 'wh_commerce__orders_fct'
        self.select({'schema_version': 1, 'profile': 'custom', 'platform': 'snowflake',
                     'templates': {'fact': 'wh_{domain}__{business_stem}_fct'}})
        self.register([self.resource()])
        self.assertEqual(naming.stage_requirements(self.state, ['orders']), [])
        for template in ['{business_stem.__class__}', '{business_stem!r}', '{business_stem:>20}',
                         '{unknown}_{business_stem}', '^.*{business_stem}$', '{{business_stem}}', 'fact_only']:
            with self.subTest(template=template), self.assertRaises(ValueError):
                naming.validate_policy({'schema_version': 1, 'profile': 'custom', 'templates': {'fact': template}})
        with self.assertRaises(ValueError): naming.validate_policy({'schema_version': 1, 'profile': 'expanded'})
        self.select({'schema_version': 1, 'profile': 'custom', 'platform': 'snowflake',
            'templates': {'fact': '{business_stem}_{business_stem}'}}, change_reference='host-request:long-names')
        before = copy.deepcopy(self.state)
        with self.assertRaises(ValueError): self.register([self.resource(business_stem='x' * 200)])
        self.assertEqual(self.state, before)

    def test_proposed_policy_does_not_select_itself_and_unknown_native_identity_is_separate(self):
        naming.configure(self.state, {'schema_version': 1, 'policy': self.policy()})
        self.register()
        self.assertIsNone(naming.access(self.state))
        self.assertEqual(naming.summarize(self.state)['status'], 'proposed')
        self.assertTrue(naming.stage_requirements(self.state, ['orders']))
        self.select({'schema_version': 1, 'profile': 'abbreviated', 'platform': 'bigquery'})
        self.assertEqual(naming.stage_requirements(self.state, ['orders']), [])
        self.assertEqual(naming.summarize(self.state)['native_identity_status'], 'unsupported')
        self.assertEqual(naming.summarize(self.state)['status'], 'conforming')

    def test_policy_change_requires_decision_and_change_reference_and_invalidates_only_affected_models(self):
        self.select(); self.register(); before = copy.deepcopy(self.state)
        policy = {'schema_version': 1, 'profile': 'custom', 'platform': 'snowflake',
                  'templates': {'fact': 'fact_{business_stem}', 'dimension': 'dim_{business_stem}'}}
        with self.assertRaises(ValueError): self.select(policy)
        self.assertEqual(self.state, before)
        changed = self.select(policy, change_reference='host-request:change-fact-style')
        self.assertEqual(changed['invalidated_entity_ids'], ['orders'])
        self.assertEqual(len(self.state['workflow']['naming_governance']['history']), 3)
        self.assertEqual(self.state['workflow']['naming_governance']['history'][0]['policy']['profile'], 'abbreviated')
        self.assertEqual(naming.stage_requirements(self.state, ['customers']), [])
        self.assertIn('naming:orders:name_nonconforming', naming.stage_requirements(self.state, ['orders']))

    def test_existing_names_and_aliases_require_scoped_override_and_history_is_idempotent(self):
        self.entity('orders')['name'] = 'legacy_orders'
        self.select()
        row = self.resource(original_name='legacy_orders', existing=True, physical_alias='ORDERS_TABLE',
            source_relation={'namespace': ['ORIGINAL_DATABASE', 'RAW'], 'name': 'ORDERS_TABLE', 'quote': 'unquoted'})
        self.register([row]); self.assertEqual(naming.stage_requirements(self.state, ['orders']), [])
        changed = dict(row, target_name='fct_orders', physical_alias='ORDER_FACT')
        before = copy.deepcopy(self.state)
        with self.assertRaises(ValueError): self.register([changed])
        self.assertEqual(self.state, before)
        self.entity('orders')['name'] = 'fct_orders'
        override = {'resource_id': row['id'], 'fields': ['target_name', 'physical_alias'],
                    'decision_reference': 'host-request:rename-orders', 'reason': 'Explicit reviewed compatibility migration'}
        self.register([changed], overrides=[override])
        self.assertEqual(naming.stage_requirements(self.state, ['orders']), [])
        recorded = copy.deepcopy(self.state)
        self.assertEqual(self.register([changed])['invalidated_entity_ids'], [])
        self.assertEqual(self.state, recorded)
        self.assertEqual(naming.records(self.state)[0]['source_relation'], row['source_relation'])

    def test_source_objects_and_qualified_identity_are_immutable_even_with_override(self):
        self.entity('orders').update(name='orders', layer='bronze', object_kind='source')
        self.select(); row = self.resource(role='source', existing=True)
        self.register([row]); before = copy.deepcopy(self.state)
        for updates in [{'source_id': 'different.orders'}, {'original_name': 'different'},
                        {'source_relation': {'namespace': ['raw'], 'name': 'different', 'quote': 'unquoted'}},
                        {'target_name': 'stg_orders'}]:
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                self.register([dict(row, **updates)], overrides=[{'resource_id': row['id'], 'fields': ['target_name'],
                    'decision_reference': 'host-request:invalid-source-rename', 'reason': 'Must remain forbidden'}])
            self.assertEqual(self.state, before)

    def test_normalized_physical_collision_rejects_atomically_and_quoted_names_are_distinct(self):
        self.select(); self.register([self.resource()]); before = copy.deepcopy(self.state)
        with self.assertRaisesRegex(ValueError, 'Physical identity collision'):
            self.register([self.resource('customers', physical_alias='FCT_ORDERS')])
        self.assertEqual(self.state, before)
        self.select(self.policy(quote='quoted'), change_reference='host-request:quoted-identifiers')
        self.register([self.resource('customers', physical_alias='FCT_ORDERS')])
        self.assertEqual(len(naming.records(self.state)), 2)

    def test_only_naming_design_changes_stale_identity_and_reregistration_refreshes_pin(self):
        self.select(); self.register(); before = naming.scope_bindings(self.state)
        self.entity('orders')['columns'][0]['description'] = 'Reviewed revised definition'
        self.assertEqual(naming.scope_bindings(self.state), before)
        self.entity('orders')['name'] = 'fact_orders'
        after = naming.scope_bindings(self.state)
        self.assertEqual({key for key in before if before[key] != after[key]}, {'orders'})
        self.assertIn('naming:orders:design_changed', naming.stage_requirements(self.state, ['orders']))
        self.entity('orders')['name'] = 'fct_orders'
        self.register([self.resource()]); self.assertEqual(naming.stage_requirements(self.state, ['orders']), [])
        self.assertEqual(len(naming.records(self.state)), 3)

    def test_missing_and_dangling_resource_references_do_not_silently_complete_scope(self):
        self.select(); self.register([self.resource()])
        self.assertIn('naming:customers:identity_not_registered', naming.stage_requirements(self.state, ['customers']))
        before = copy.deepcopy(self.state)
        for updates in [{'entity_id': 'absent'}, {'source_id': 'unqualified'}, {'layer': 'silver'},
                        {'domain': 'other'}, {'id': 'resource:new-id'}]:
            with self.subTest(updates=updates), self.assertRaises(ValueError): self.register([self.resource(**updates)])
            self.assertEqual(self.state, before)

    def test_explicit_alias_is_retained_and_registration_does_not_mutate_design_or_authority(self):
        self.select(); row = self.resource(physical_alias='fixed_physical_orders')
        design = copy.deepcopy(self.state['workflow']['design']); self.register([row])
        self.assertEqual(naming.records(self.state)[0]['physical_alias'], 'fixed_physical_orders')
        self.assertEqual(self.state['workflow']['design'], design)
        self.assertEqual(self.state['workflow']['approvals'], [])
        self.assertEqual(naming.summarize(self.state, ['customers'])['resources'], [])
        with self.assertRaisesRegex(ValueError, 'Name or alias changes'):
            self.register([dict(row, physical_alias='silently_changed_alias')])

    def test_split_source_identity_and_full_namespaces_preserve_existing_quoted_names(self):
        self.select()
        first = self.resource(physical_alias='shared_name', namespace=['db_one', 'analytics'])
        second = self.resource('customers', source_id=first['source_id'], original_name=first['original_name'],
            physical_alias='shared_name', namespace=['db_two', 'analytics'])
        self.register([first, second])
        self.assertEqual(len(naming.records(self.state)), 2)
        with self.assertRaisesRegex(ValueError, 'Physical identity collision'):
            self.register([dict(second, namespace=['DB_ONE', 'ANALYTICS'])], overrides=[{
                'resource_id': second['id'], 'fields': ['namespace'], 'decision_reference': 'host-request:collision', 'reason': 'Collision must reject'}])
        self.entity('products')['name'] = 'Existing Product Name'
        original = self.resource('products', existing=True, original_name='Existing Product Name',
            namespace=['Original Database', 'Custom Schema'], physical_alias='Exact Table Name',
            source_relation={'namespace': ['Original Database', 'Custom Schema'], 'name': 'Exact Table Name', 'quote': 'quoted'})
        self.register([original])
        self.assertEqual(naming.stage_requirements(self.state, ['products']), [])
        self.assertEqual(naming.records(self.state, ['products']), [original])


if __name__ == '__main__': unittest.main()
