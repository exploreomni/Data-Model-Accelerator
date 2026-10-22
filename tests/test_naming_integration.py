"""Names survive actual stage, specialist and artifact boundaries without execution."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import engagement_stages as stages
import naming_governance as naming
import naming_artifacts as artifacts
from naming_context import packet_contract, validate_packet
import test_engagement_stages as fixtures


class NamingIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.StageTests('test_host_attributed_review_opens_candidates_not_deployment')
        self.h.setUp(); self.addCleanup(self.h.doCleanups)
        self.state = self.h.state
        self.root = self.h.artifacts
        naming.configure(self.state, {'schema_version': 1, 'policy': {'schema_version': 1, 'profile': 'preserve',
                         'platform': 'snowflake'}, 'decision_reference': 'synthetic://user/keep-names'})
        self.rows = [dict(id='identity.'+e['id'], entity_id=e['id'], source_id='repo.'+e['id'],
                         original_name=e['name'], target_name=e['name'], physical_alias=None,
                         source_relation=None, existing=False, layer=e['layer'], role='fact',
                         business_stem=e['name'], domain=e['domain'], namespace=['DEV', 'MODELS'],
                         evidence_refs=['synthetic://source']) for e in self.h.doc['entities']]
        naming.register(self.state, {'schema_version': 1, 'resources': self.rows})

    def assoc(self, path='orders.sql', kind='dbt_model', **extra):
        return dict(path=path, kind=kind, resource_ids=['identity.orders'], **extra)

    def test_actual_refs_filename_and_alias_are_checked(self):
        (self.root/'orders.sql').write_text("select * from {{ ref('customers') }}")
        report = artifacts.audit(self.state, self.root, [self.assoc()])
        self.assertEqual(report['status'], 'passed')
        (self.root/'orders.sql').write_text("{{ config(alias='invented_orders') }} select * from {{ ref('intermediate_customers') }}")
        report = artifacts.audit(self.state, self.root, [self.assoc()])
        codes = {f['code'] for f in report['findings'] if f['status'] == 'failed'}
        self.assertIn('naming.ref_identity', codes); self.assertIn('naming.physical_alias', codes)
        (self.root/'random.sql').write_text('select 1')
        self.assertEqual(artifacts.audit(self.state, self.root, [self.assoc('random.sql')])['status'], 'failed')

    def test_dynamic_reference_stays_unsupported_and_unbound_files_stay_visible(self):
        (self.root/'orders.sql').write_text("select * from {{ ref(var('runtime_model')) }}")
        report = artifacts.audit(self.state, self.root, [self.assoc()], ['orders.sql','missing.view'])
        self.assertGreater(report['counts']['unsupported'], 0)
        self.assertTrue(any(f['code']=='naming.artifact_unbound' for f in report['findings']))

    def test_omni_binding_mismatch_and_properties_names(self):
        try: import yaml
        except ImportError: self.skipTest('Optional YAML reader unavailable')
        (self.root/'orders.view').write_text('table_name: invented_orders\nschema: MODELS\ncatalog: DEV\n')
        self.assertEqual(artifacts.audit(self.state, self.root, [self.assoc('orders.view','omni_view',semantic_name='orders')])['status'], 'failed')
        (self.root/'orders.view').write_text('table_name: orders\nschema: MODELS\ncatalog: DEV\n')
        self.assertEqual(artifacts.audit(self.state, self.root, [self.assoc('orders.view','omni_view',semantic_name='orders')])['status'], 'passed')
        (self.root/'schema.yml').write_text('version: 2\nmodels:\n  - name: fact_orders\n')
        self.assertEqual(artifacts.audit(self.state, self.root, [self.assoc('schema.yml','dbt_properties')])['status'], 'failed')

    def test_idempotent_checks_and_changed_bytes_are_not_reused(self):
        (self.root/'orders.sql').write_text('select 1')
        request = {'schema_version':1, 'artifacts':[self.assoc()]}
        artifacts.record(self.state,request,self.root); artifacts.record(self.state,request,self.root)
        self.assertEqual(len(self.state['workflow']['naming_artifact_checks']),1)
        (self.root/'orders.sql').write_text("select * from {{ ref('made_up') }}")
        self.assertEqual(artifacts.summary(self.state)['status'],'failed')

    def test_policy_pins_are_scoped_and_packet_tampering_is_rejected(self):
        before = stages.entity_bindings(self.state,['orders','products'])
        packet = packet_contract(self.state,['orders'])
        self.assertEqual(set(packet['entity_ids']),{'orders','customers'})
        self.assertEqual(len(packet['resources']),2)
        request={'naming_contract':packet,'bindings':{'naming_contract':packet['sha256']}}
        validate_packet(request)
        request['naming_contract']['resources'][0]['target_name']='surprise'
        with self.assertRaisesRegex(ValueError,'pin mismatch'): validate_packet(request)
        proposed=copy.deepcopy(self.h.doc); proposed['revision']=2
        proposed['entities'][1]['name']='fct_orders'
        stages.import_design(self.state,proposed)
        self.assertTrue(naming.stage_requirements(self.state,['orders']))
        self.assertEqual(before['products'], stages.entity_bindings(self.state,['products'])['products'])

    def test_actual_cli_actions_persist_policy_and_identity_history(self):
        self.h.action('configure-naming', document={'schema_version':1,'policy':{'schema_version':1,'profile':'preserve'},
                                                  'decision_reference':'synthetic://user/keep'})
        self.h.action('record-model-identities',document={'schema_version':1,'resources':self.rows})
        self.h.action('naming-packet',entities=['orders'])
        self.assertEqual(len(self.h.state['workflow']['naming_packet']['resources']),2)
        (self.root/'orders.sql').write_text('select 1')
        self.h.action('check-naming',document={'schema_version':1,'artifacts':[self.assoc()]},artifact_root=self.root)
        self.assertEqual(artifacts.summary(self.h.state)['status'],'passed')

    def test_provisional_generation_survives_missing_names(self):
        self.state['workflow']['naming_governance']['resources']=[]
        request={'schema_version':1,'kind':'provisional_code_request','requester':'Synthetic user',
                 'request_reference':'synthetic://user/draft','request_text':'Generate provisional warehouse code.',
                 'bindings':stages.draft_bindings(self.state,['orders'])}
        stages.record_draft_request(self.state,['orders'],request)
        self.assertTrue(naming.stage_requirements(self.state,['orders']))
        self.assertEqual(stages.approved_entities(self.state),set())
        self.assertIn('orders',stages.require_stage(self.state,'implementation',['orders']))

    def test_unbound_paths_do_not_leak_between_scopes(self):
        artifacts.record(self.state,{'schema_version':1,'artifacts':[],
            'expected_paths':['private_catalog.topic'],'entity_ids':['products']},self.root)
        self.assertNotIn('private_catalog',json.dumps(artifacts.summary(self.state,['orders'])))
        self.assertIn('private_catalog',json.dumps(artifacts.summary(self.state,['products'])))
        artifacts.record(self.state,{'schema_version':1,'artifacts':[],
            'expected_paths':['unscoped_private.sql']},self.root)
        self.assertNotIn('unscoped_private',json.dumps(artifacts.summary(self.state,['orders'])))

    def test_invalid_yaml_shapes_are_findings_not_crashes(self):
        try: import yaml
        except ImportError: self.skipTest('Optional YAML reader unavailable')
        for kind, payload in [('dbt_properties','models: null'),('dbt_sources','sources: null')]:
            (self.root/'bad.yml').write_text(payload)
            report=artifacts.audit(self.state,self.root,[self.assoc('bad.yml',kind)])
            self.assertEqual(report['status'],'failed')

    def test_unrelated_policy_changes_preserve_checked_dimension(self):
        policy={'schema_version':1,'profile':'custom','platform':'snowflake',
                'templates':{'fact':'{business_stem}','dimension':'{business_stem}'}}
        naming.configure(self.state,{'schema_version':1,'policy':policy,'decision_reference':'synthetic://choice',
                                    'change_reference':'synthetic://custom'})
        rows=copy.deepcopy(self.rows); rows[0]['role']='dimension'
        naming.register(self.state,{'schema_version':1,'resources':rows})
        (self.root/'customers.sql').write_text('select 1')
        artifacts.record(self.state,{'schema_version':1,'artifacts':[dict(path='customers.sql',kind='dbt_model',
                            resource_ids=['identity.customers'])]},self.root)
        policy['templates']['fact']='fct_{business_stem}'
        naming.configure(self.state,{'schema_version':1,'policy':policy,'decision_reference':'synthetic://choice2',
                                    'change_reference':'synthetic://facts-only'})
        self.assertEqual(artifacts.summary(self.state,['customers'])['status'],'passed')

    def test_paths_cannot_escape_candidate_root(self):
        with self.assertRaises(ValueError): artifacts.audit(self.state,self.root,[self.assoc('../source/orders.sql')])

    def test_optional_folder_patterns_check_actual_sql_paths_without_renaming(self):
        policy = {'schema_version': 1, 'profile': 'preserve', 'platform': 'snowflake',
                  'folder_patterns': {'fact': 'models/{domain}/{layer}'}}
        naming.configure(self.state, {'schema_version': 1, 'policy': policy,
            'decision_reference': 'synthetic://folder-choice', 'change_reference': 'synthetic://folder-rule'})
        path = 'models/commerce/gold/orders.sql'
        (self.root/path).parent.mkdir(parents=True)
        (self.root/path).write_text('select 1')
        before = copy.deepcopy(self.state['workflow']['design'])
        report = artifacts.audit(self.state, self.root, [self.assoc(path)])
        self.assertEqual(report['status'], 'passed')
        self.assertTrue(any(f['code'] == 'naming.model_folder' and f['status'] == 'passed' for f in report['findings']))
        (self.root/'orders.sql').write_text('select 1')
        report = artifacts.audit(self.state, self.root, [self.assoc()])
        self.assertTrue(any(f['code'] == 'naming.model_folder' and f['status'] == 'failed' for f in report['findings']))
        self.assertEqual(before, self.state['workflow']['design'])
        self.assertTrue((self.root/'orders.sql').exists())
        # Warehouse folder conventions do not constrain semantic view directories.
        try: import yaml
        except ImportError: return
        (self.root/'orders.view').write_text('table_name: orders\nschema: MODELS\ncatalog: DEV\n')
        report = artifacts.audit(self.state, self.root, [self.assoc('orders.view', 'omni_view', semantic_name='orders')])
        self.assertEqual(report['status'], 'passed')
        self.assertFalse(any(f['code'] == 'naming.model_folder' for f in report['findings']))
