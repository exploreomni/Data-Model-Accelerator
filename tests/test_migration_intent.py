"""Synthetic intent/conformance regressions; no warehouse or identity claims."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch

import test_engagement_stages as fixtures
from ae_common import hash_json
import legacy_alignment
import design_coverage
import design_evidence
import migration_intent as intent
import source_roots


class MigrationIntentTests(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.StageTests('test_design_only_and_forged_approval_never_unlock_code')
        self.h.setUp(); self.addCleanup(self.h.doCleanups)
        self.state = self.h.state
        doc = copy.deepcopy(self.h.doc); doc['revision'] += 1
        doc['entities'][2]['domain'] = 'catalog'
        fixtures.stages.import_design(self.state, doc)
        (self.h.repo / 'target').mkdir()
        (self.h.repo / 'target/orders.sql').write_text('select 1 as orders_id -- independently supplied target convention')
        for domain in ('commerce', 'catalog'):
            legacy_alignment.configure(self.state, {'schema_version': 1, 'domain_id': domain, 'mode': 'refactor',
                'comparison_requested': True, 'behavior': 'preserve', 'request_reference': 'synthetic://requested-comparison'})
        tables, evidence = [], []
        for name, domain in [('orders', 'commerce'), ('customers', 'commerce'), ('products', 'catalog')]:
            (self.h.repo / (name + '.schema.json')).write_text(json.dumps({'columns': [name + '_id']}))
            (self.h.repo / (name + '.rules.md')).write_text('Synthetic complete population: every fixture row; no additional filters.')
            tables.append({'id': 'old.' + name, 'namespace': 'synthetic', 'native_id': name, 'label': name,
                'consumer_domains': [domain], 'columns': [{'id': 'key', 'name': name + '_id', 'type': 'integer', 'definition': 'Stable key'}],
                'rules': [], 'evidence_ids': [name + '.sql', name + '.schema', name + '.rules'], 'completeness': {'columns': 'complete', 'rules': 'complete'}})
            evidence.append({'id': name + '.sql', 'kind': 'sql', 'reference': 'synthetic://source/' + name,
                             'source_path': name + '.sql', 'sha256': self.sha(name + '.sql')})
            for kind, suffix in [('schema', '.schema.json'), ('rules', '.rules.md')]:
                evidence.append({'id': name + '.' + kind, 'kind': kind, 'reference': 'synthetic://source/' + name + suffix,
                                 'source_path': name + suffix, 'sha256': self.sha(name + suffix)})
        legacy_alignment.register_baseline(self.state, {'schema_version': 1, 'status': 'complete',
                                                      'tables': tables, 'evidence': evidence}, self.h.run)
        for domain, names in [('commerce', ['orders', 'customers']), ('catalog', ['products'])]:
            legacy_alignment.register_alignment(self.state, {'schema_version': 1, 'domain_id': domain, 'mappings': [
                {'id': name + '.mapping', 'sources': [{'table_id': 'old.' + name, 'kind': 'table'},
                    {'table_id': 'old.' + name, 'kind': 'column', 'field_id': 'key'}],
                 'targets': [{'model_id': name, 'kind': 'table'}, {'model_id': name, 'kind': 'column', 'field': name + '_id'}],
                 'status': 'mapped', 'basis': 'expression_analysis', 'behavior': 'preserve',
                 'rationale': 'Source and target key expression comparison.', 'evidence_refs': [name + '.sql']}
                for name in names]}, self.h.run)

    def sha(self, reference):
        return hashlib.sha256((self.h.repo / reference).read_bytes()).hexdigest()

    def configure(self, domain='commerce', **changes):
        names = ['orders', 'customers'] if domain == 'commerce' else ['products']
        request = {'schema_version': 1, 'kind': 'migration_intent', 'domain_id': domain,
            'structural_objective': 'refactor', 'behavior': 'preserve',
            'objectives': [{'id': 'shape', 'statement': 'Evaluate the target design against explicit source behavior and conventions.'}],
            'source_roles': [{'id': 'old-' + name, 'root_id': 'primary', 'role': 'legacy_baseline', 'path_prefix': name + '.sql'} for name in names]
                + [{'id': 'target', 'root_id': 'primary', 'role': 'target_implementation', 'path_prefix': 'target'}],
            'behavior_constraints': ['Preserve key and row grain.'], 'request_reference': 'synthetic://user/refactor', **changes}
        intent.configure(self.state, request)
        return request

    def assessment(self, domain='commerce', **changes):
        names = ['orders', 'customers'] if domain == 'commerce' else ['products']
        refs = [name + '.sql' for name in names] + ['target/orders.sql']
        return {'schema_version': 1, 'domain_id': domain,
            'binding_sha256': intent.assessment_bindings(self.state, domain)['binding_sha256'],
            'author': 'builder', 'reviewer': 'independent-reviewer', 'review_reference': 'synthetic://review/architecture',
            'status': 'accepted', 'objective_results': [{'objective_id': 'shape', 'status': 'addressed', 'model_ids': names,
                'source_evidence': [{'reference': r, 'sha256': self.sha(r)} for r in refs],
                'mapping_ids': [name + '.mapping' for name in names],
                'analysis': 'Compared source keys and row populations with the explicit target design; source behavior remains distinct from layout.',
                'findings': []}], 'transitional_dependencies': [], 'semantic_purpose': [{
                    'model_ids': names, 'topic_ids': ['shared-analysis'], 'consumer_or_metric_refs': ['report:' + name for name in names],
                    'evidence_refs': [name + '.sql' for name in names]}], 'findings': [], **changes}

    def row(self, domain='commerce', selected=None):
        return next(r for r in intent.summary(self.state, selected)['domains'] if r['domain_id'] == domain)

    def reject(self, request, pattern=None):
        before = copy.deepcopy(self.state)
        with self.assertRaisesRegex(ValueError, pattern or '.'):
            intent.record_assessment(self.state, request)
        self.assertEqual(before, self.state)

    def add_supporting_pipeline(self, *, reused_shared=False, orphan=False):
        doc = copy.deepcopy(self.state['workflow']['design']); doc.pop('sha256'); doc['revision'] += 1
        models = {m['id']: m for m in doc['entities']}
        for subject in ('orders', 'customers', 'refunds'):
            template = models['customers' if subject == 'customers' else 'orders']
            for tier, parents in (('raw', []), ('stg', ['raw_' + subject])):
                key = tier + '_' + subject
                path = 'target_stg_customers.sql' if key == 'stg_customers' and reused_shared else 'target/' + key + '.sql'
                (self.h.repo / path).write_text('select 1 as ' + template['keys'][0] + ' -- ' + key)
                model = copy.deepcopy(template)
                model.update(id=key, name=key, layer='bronze' if tier == 'raw' else 'silver',
                    object_kind='source' if tier == 'raw' else 'model', depends_on=parents,
                    asset_ids=[], source_paths=[path], catalogue_pointers=[])
                if key == 'stg_customers' and reused_shared:
                    model['domain'] = 'shared'
                    model.update(disposition='reuse', reuse={'existing_id': 'existing-stg-customers',
                        'rationale': 'Reuse the supplied compatible target staging model.',
                        'dimensions': {d: {'status': 'compatible', 'evidence_refs': [path],
                                           'explanation': 'Compared the actual existing target definition.'} for d in fixtures.stages.DIMENSIONS}})
                    doc['existing_models'].append({'id': 'existing-stg-customers', 'name': key, 'grain': model['grain'],
                        'keys': model['keys'], 'definitions': 'Independent target staging definition', 'history': model['history'],
                        'security': model['security'], 'dependencies': parents, 'evidence_refs': [path]})
                doc['entities'].append(model)
        models['orders']['depends_on'] = ['customers', 'stg_orders', 'stg_refunds']
        models['customers']['depends_on'] = ['stg_customers']
        if orphan:
            extra = copy.deepcopy(next(m for m in doc['entities'] if m['id'] == 'stg_orders'))
            extra.update(id='orphan_staging', name='orphan_staging')
            doc['entities'].append(extra)
        fixtures.stages.import_design(self.state, doc)
        previous = legacy_alignment._alignment(self.state, 'commerce')['request']
        legacy_alignment.register_alignment(self.state, previous, self.h.run)

    def registered_nested_reuse(self, *, legacy=False):
        root = self.h.root / 'registered-target'; (root / 'models').mkdir(parents=True)
        path = root / 'models/orders.sql'; path.write_text('select 7 as orders_id -- independent nested implementation')
        source_roots.register(self.state, {'schema_version': 1, 'roots': [
            {'id': 'warehouse', 'path': str(root), 'revision': 'synthetic-revision'}]}, self.h.run)
        reference = '@sources/warehouse/models/orders.sql'
        doc = copy.deepcopy(self.state['workflow']['design']); doc.pop('sha256'); doc['revision'] += 1
        model = next(m for m in doc['entities'] if m['id'] == 'orders')
        model.update(disposition='reuse', reuse={'existing_id': 'existing-orders', 'rationale': 'Compare the captured independent target.',
            'dimensions': {d: {'status': 'compatible', 'evidence_refs': ['baseline.' + d],
                               'explanation': 'Use the registered original source claim.'} for d in fixtures.stages.DIMENSIONS}})
        existing = {'id': 'existing-orders', 'name': 'retained.orders', 'grain': model['grain'], 'keys': model['keys'],
            'definitions': 'Captured original order definition', 'history': model['history'], 'security': model['security'],
            'dependencies': [], 'evidence_refs': ['capture.orders']}
        doc['existing_models'] = [existing]
        fixtures.stages.import_design(self.state, doc)
        snapshot = root / 'snapshot.json'; snapshot.write_text(json.dumps({'models': [existing]}))
        source = {'id': 'captured', 'namespace': 'synthetic.captured', 'role': 'existing_models',
            'kind': 'external_inventory', 'status': 'available', 'domain_ids': ['commerce'], 'root': str(root),
            'inventory': {'status': 'complete', 'reference': 'synthetic://capture', 'files': [
                {'path': p, 'sha256': hashlib.sha256((root / p).read_bytes()).hexdigest(), 'status': 'parsed', 'object_ids': []}
                for p in ('models/orders.sql', 'snapshot.json')]}}
        design_coverage.record(self.state, {'schema_version': 1, 'sources': [source],
            'objects': [], 'consumers': [], 'assignments': []}, self.h.run)
        original = {'source_id': 'captured', 'path': 'models/orders.sql',
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'locator': 'line 1'}
        evidence = {'schema_version': 1, 'kind': 'design_evidence', 'claims': [
            {'id': 'baseline.' + d, 'model_ids': ['orders'], 'baseline_id': 'existing-orders', 'subject': d,
             'basis': 'repository_declaration', 'statement': 'Captured independent ' + d, 'sources': [original]}
            for d in sorted(fixtures.stages.DIMENSIONS)], 'baselines': [{
                'existing_id': 'existing-orders', 'snapshot': existing,
                'snapshot_source': {'source_id': 'captured', 'path': 'snapshot.json',
                    'sha256': hashlib.sha256(snapshot.read_bytes()).hexdigest(), 'locator': '/models/0'},
                'claim_ids': ['baseline.' + d for d in sorted(fixtures.stages.DIMENSIONS)],
                'captured_by': 'synthetic-operator', 'capture_reference': 'synthetic://independent-snapshot'}]}
        design_evidence.record(self.state, evidence, self.h.run)
        previous = legacy_alignment._alignment(self.state, 'commerce')['request']
        legacy_alignment.register_alignment(self.state, previous, self.h.run)
        contract = self.configure()
        contract['source_roles'].append({'id': 'captured', 'root_id': 'warehouse',
            'role': 'legacy_baseline' if legacy else 'target_implementation', 'path_prefix': 'models'})
        intent.configure(self.state, contract)
        request = self.assessment()
        request['objective_results'][0]['source_evidence'].append({'reference': reference, 'sha256': original['sha256']})
        request['semantic_purpose'][0]['evidence_refs'] = [reference]
        if legacy:
            request['legacy_exceptions'] = [{'model_id': 'orders', 'reason': 'Explicitly retain this captured original.',
                                             'evidence_refs': [reference]}]
        return request, evidence, path

    def test_absent_old_and_nonrefactor_contracts_never_add_authority_or_completion_gate(self):
        old = {'schema_version': 1}
        self.assertEqual(intent.scope_bindings(old), {})
        self.assertIsNone(intent.packet_contract(old, 'commerce'))
        self.assertEqual(intent.require_complete(old)['status'], 'unassessed')
        for objective in ('preserve', 'new_model'):
            self.configure(structural_objective=objective)
            intent.require_complete(self.state)
        self.assertEqual(self.state['workflow']['approvals'], [])
        self.assertFalse(self.state['readiness']['execution_authorized'])

    def test_gold_alignment_accounts_for_connected_raw_and_staging_without_fake_mappings(self):
        self.add_supporting_pipeline(); self.configure()
        request = self.assessment()
        self.assertEqual(set(request['objective_results'][0]['model_ids']), {'orders', 'customers'})
        self.assertEqual(set(request['objective_results'][0]['mapping_ids']), {'orders.mapping', 'customers.mapping'})
        intent.record_assessment(self.state, request)
        self.assertEqual(self.row()['status'], 'accepted')
        self.assertEqual(self.row()['model_disposition_counts']['create'], 5)
        intent.require_complete(self.state)

    def test_unconnected_staging_cannot_be_accounted_by_other_targets(self):
        self.add_supporting_pipeline(orphan=True); self.configure()
        self.reject(self.assessment(), 'account for every in-domain object')

    def test_reused_shared_supporting_model_needs_its_own_pinned_origin(self):
        self.add_supporting_pipeline(reused_shared=True)
        contract = self.configure()
        contract['source_roles'].append({'id': 'shared-target', 'root_id': 'primary', 'role': 'target_implementation',
                                         'path_prefix': 'target_stg_customers.sql'})
        intent.configure(self.state, contract)
        self.reject(self.assessment(), 'Existing model origin')
        request = self.assessment()
        request['objective_results'][0]['source_evidence'].append(
            {'reference': 'target_stg_customers.sql', 'sha256': self.sha('target_stg_customers.sql')})
        intent.record_assessment(self.state, request)
        self.assertEqual(self.row()['status'], 'accepted')
        supporting = next(m for m in self.state['workflow']['design']['entities'] if m['id'] == 'stg_customers')
        supporting['reuse']['dimensions']['grain']['evidence_refs'] = ['unrelated-target']
        previous = legacy_alignment._alignment(self.state, 'commerce')['request']
        legacy_alignment.register_alignment(self.state, previous, self.h.run)
        request['binding_sha256'] = intent.assessment_bindings(self.state, 'commerce')['binding_sha256']
        self.reject(request, 'current original source evidence')

    def test_assessment_engine_change_stales_review_without_changing_work_bindings(self):
        self.configure(); intent.record_assessment(self.state, self.assessment())
        packet = intent.packet_contract(self.state, 'commerce')
        entity_pins = fixtures.stages.entity_bindings(self.state, ['orders', 'customers'])
        old_bindings = intent.assessment_bindings(self.state, 'commerce')
        with patch.object(intent, '_assessment_engine_sha256', return_value='0' * 64):
            self.assertNotEqual(intent.assessment_bindings(self.state, 'commerce'), old_bindings)
            self.assertEqual(self.row()['status'], 'stale')
            self.assertEqual(intent.packet_contract(self.state, 'commerce'), packet)
            self.assertEqual(fixtures.stages.entity_bindings(self.state, ['orders', 'customers']), entity_pins)

    def test_registered_nested_target_provenance_ids_and_scoped_association_freshness(self):
        request, evidence, path = self.registered_nested_reuse()
        intent.record_assessment(self.state, request)
        self.assertEqual(self.row()['status'], 'accepted')
        self.configure('catalog'); intent.record_assessment(self.state, self.assessment('catalog'))
        evidence['claims'][0]['statement'] = 'An updated captured interpretation with the same source bytes.'
        design_evidence.record(self.state, evidence, self.h.run)
        self.assertEqual(self.row()['status'], 'stale')
        self.assertEqual(self.row('catalog')['status'], 'accepted')
        request['binding_sha256'] = intent.assessment_bindings(self.state, 'commerce')['binding_sha256']
        intent.record_assessment(self.state, request)
        path.write_text('select 8 as orders_id -- changed nested original')
        self.assertEqual(self.row()['status'], 'stale')
        request['binding_sha256'] = intent.assessment_bindings(self.state, 'commerce')['binding_sha256']
        self.reject(request, 'source bytes changed')

    def test_registered_claims_reject_wrong_model_dimension_and_proposal(self):
        request, evidence, _ = self.registered_nested_reuse()
        original = copy.deepcopy(evidence)
        for mutation in ('model', 'dimension', 'missing'):
            doc = copy.deepcopy(original)
            claim = next(c for c in doc['claims'] if c['subject'] == 'grain')
            if mutation == 'model': claim['model_ids'] = ['customers']
            elif mutation == 'dimension': claim['subject'] = 'security'
            else:
                doc['claims'].remove(claim)
                doc['baselines'][0]['claim_ids'].remove(claim['id'])
            design_evidence.record(self.state, doc, self.h.run)
            request['binding_sha256'] = intent.assessment_bindings(self.state, 'commerce')['binding_sha256']
            self.reject(request, 'current original source evidence')
        doc = copy.deepcopy(original)
        doc['claims'].append({'id': 'proposed.grain', 'model_ids': ['orders'], 'subject': 'grain',
            'basis': 'proposal', 'statement': 'Unverified target guess.', 'sources': original['claims'][0]['sources']})
        design_evidence.record(self.state, doc, self.h.run)
        next(m for m in self.state['workflow']['design']['entities'] if m['id'] == 'orders')['reuse']['dimensions']['grain']['evidence_refs'] = ['proposed.grain']
        legacy_alignment.register_alignment(self.state, legacy_alignment._alignment(self.state, 'commerce')['request'], self.h.run)
        request['binding_sha256'] = intent.assessment_bindings(self.state, 'commerce')['binding_sha256']
        self.reject(request, 'current original source evidence')

    def test_nested_legacy_exception_and_semantic_source_refs_are_paths_not_ids(self):
        request, _, _ = self.registered_nested_reuse(legacy=True)
        without = copy.deepcopy(request); without.pop('legacy_exceptions')
        self.reject(without, 'explicit exception')
        intent.record_assessment(self.state, request)
        self.assertEqual(self.row()['legacy_exception_model_ids'], ['orders'])
        self.assertEqual(self.row()['status'], 'accepted')

    def test_shared_legacy_exception_and_transition_must_be_in_dependency_closure(self):
        self.add_supporting_pipeline(reused_shared=True)
        contract = self.configure()
        contract['source_roles'].append({'id': 'shared-origin', 'root_id': 'primary', 'role': 'legacy_baseline',
                                         'path_prefix': 'target_stg_customers.sql'})
        intent.configure(self.state, contract)
        request = self.assessment(legacy_exceptions=[{'model_id': 'stg_customers', 'reason': 'Retain the shared transition explicitly.',
                                                      'evidence_refs': ['target_stg_customers.sql']}])
        request['objective_results'][0]['source_evidence'].append(
            {'reference': 'target_stg_customers.sql', 'sha256': self.sha('target_stg_customers.sql')})
        intent.record_assessment(self.state, request)
        self.assertEqual(self.row()['legacy_exception_model_ids'], ['stg_customers'])
        self.assertEqual(self.row(selected=list(intent._models(self.state, 'commerce')))['legacy_exception_model_ids'], [])
        for key in ('products', 'raw_customers'):
            bad = copy.deepcopy(request); bad['legacy_exceptions'][0]['model_id'] = key
            self.reject(bad, 'Unknown or duplicate')
            bad = copy.deepcopy(request)
            bad['transitional_dependencies'] = [{'model_id': key, 'reason': 'Not a scoped model.', 'resolution': 'Review separately.'}]
            self.reject(bad, 'Unknown transitional')
        request['transitional_dependencies'] = [{'model_id': 'stg_customers', 'reason': 'Shared legacy dependency still exists.',
                                                 'resolution': 'Replace under a separate reviewed change.'}]
        intent.record_assessment(self.state, request)
        self.assertEqual(self.row()['status'], 'partial')
        self.assertEqual(self.row()['transitional_dependency_count'], 1)

    def test_pinned_monorepo_roles_packet_and_public_projection(self):
        self.configure()
        packet = intent.packet_contract(self.state, 'commerce')
        self.assertEqual(intent.validate_packet_contract(packet), packet)
        self.assertEqual(intent.source_roles_for_reference(self.state, 'commerce', 'target/orders.sql'), ['target_implementation'])
        self.assertEqual(intent.source_roles_for_reference(self.state, 'commerce', 'products.sql'), [])
        self.assertNotIn(str(self.h.repo), str(intent.summary(self.state)))
        self.assertNotIn('path_prefix', str(intent.summary(self.state)))
        self.assertEqual(intent.summary(self.state, ['orders'])['domains'], [])
        with self.assertRaisesRegex(ValueError, 'Refactor completion'):
            intent.require_complete(self.state, ['orders'])
        bad = copy.deepcopy(packet); bad['intent']['behavior'] = 'undecided'
        with self.assertRaises(ValueError): intent.validate_packet_contract(bad)
        for role in ({'id': 'bad', 'root_id': 'missing', 'role': 'legacy_baseline'},
                     {'id': 'bad', 'root_id': 'primary', 'role': 'legacy_baseline', 'path_prefix': '../outside'}):
            before = copy.deepcopy(self.state)
            with self.assertRaises(ValueError): self.configure(source_roles=[role])
            self.assertEqual(self.state, before)

    def test_copied_model_names_counts_and_empty_evidence_cannot_complete(self):
        self.configure()
        request = self.assessment()
        request['objective_results'][0]['source_evidence'] = []
        self.reject(request, 'source bytes')
        request = self.assessment(); request['objective_results'][0]['mapping_ids'] = []
        self.reject(request, 'alignment mappings')
        request = self.assessment(); request['objective_results'] = []; request['semantic_purpose'] = []
        self.reject(request, 'Every structural objective')
        request = self.assessment(); request['reviewer'] = request['author']
        self.reject(request, 'differ')
        request = self.assessment(); request['findings'] = ['Legacy wrappers still retain the eliminated dependency.']
        self.reject(request, 'Unresolved findings')
        with self.assertRaises(ValueError): intent.require_complete(self.state)

    def test_valid_evidenced_target_reuse_and_shared_topic_do_not_require_new_models(self):
        doc = self.state['workflow']['design']
        model = next(m for m in doc['entities'] if m['id'] == 'orders')
        model.update(disposition='reuse', reuse={'existing_id': 'existing-orders', 'rationale': 'Fits the reviewed target contract.',
            'dimensions': {d: {'status': 'compatible', 'evidence_refs': ['orders.sql', 'target/orders.sql'],
                               'explanation': 'Compared the original source definition and target implementation.'} for d in fixtures.stages.DIMENSIONS}})
        doc['existing_models'] = [{'id': 'existing-orders', 'name': 'orders', 'grain': model['grain'],
            'keys': model['keys'], 'definitions': 'Pinned target definition', 'history': model['history'],
            'security': model['security'], 'dependencies': [], 'evidence_refs': ['target/orders.sql']}]
        # Re-pin the existing alignment after this scoped target change.
        previous = legacy_alignment._alignment(self.state, 'commerce')['request']
        legacy_alignment.register_alignment(self.state, previous, self.h.run)
        self.configure(); before = intent.scope_bindings(self.state)
        intent.record_assessment(self.state, self.assessment())
        self.assertEqual(self.row()['status'], 'accepted')
        self.assertTrue(self.row()['refactor_complete'])
        self.assertEqual(self.row()['model_disposition_counts']['reuse'], 1)
        self.assertEqual(intent.scope_bindings(self.state), before)
        intent.require_complete(self.state)
        self.assertEqual(self.state['workflow']['approvals'], [])
        model['reuse']['dimensions']['grain']['evidence_refs'] = ['copied-file-hash']
        previous = legacy_alignment._alignment(self.state, 'commerce')['request']
        legacy_alignment.register_alignment(self.state, previous, self.h.run)
        self.reject(self.assessment(), 'original source evidence')

    def test_source_design_and_intent_changes_stale_only_the_affected_domain(self):
        for domain in ('commerce', 'catalog'):
            self.configure(domain); intent.record_assessment(self.state, self.assessment(domain))
        packets = {d: intent.packet_contract(self.state, d)['binding_sha256'] for d in ('commerce', 'catalog')}
        (self.h.repo / 'orders.sql').write_text('select 2 as orders_id')
        self.assertEqual(self.row()['status'], 'stale')
        self.assertEqual(self.row('catalog')['status'], 'accepted')
        self.assertEqual(intent.packet_contract(self.state, 'commerce')['binding_sha256'], packets['commerce'])
        self.configure(behavior_constraints=['Preserve a newly specified population rule.'])
        self.assertNotEqual(intent.packet_contract(self.state, 'commerce')['binding_sha256'], packets['commerce'])
        self.assertEqual(intent.packet_contract(self.state, 'catalog')['binding_sha256'], packets['catalog'])

    def test_legacy_reuse_cannot_borrow_unrelated_target_origin_evidence(self):
        doc = self.state['workflow']['design']
        model = next(m for m in doc['entities'] if m['id'] == 'orders')
        model.update(disposition='reuse', reuse={'existing_id': 'legacy-orders', 'rationale': 'Retain an explicitly reviewed legacy source.',
            'dimensions': {d: {'status': 'compatible', 'evidence_refs': ['orders.sql'],
                               'explanation': 'Compared the original legacy implementation.'} for d in fixtures.stages.DIMENSIONS}})
        doc['existing_models'] = [{'id': 'legacy-orders', 'name': 'orders', 'grain': model['grain'],
            'keys': model['keys'], 'definitions': 'Pinned legacy definition', 'history': model['history'],
            'security': model['security'], 'dependencies': [], 'evidence_refs': ['orders.sql']}]
        previous = legacy_alignment._alignment(self.state, 'commerce')['request']
        legacy_alignment.register_alignment(self.state, previous, self.h.run)
        self.configure()
        # This review already includes target/orders.sql. It belongs to a
        # different implementation and cannot establish this existing origin.
        self.reject(self.assessment(), 'explicit exception pinned to its actual source origin')
        wrong = [{'model_id': 'orders', 'reason': 'Reviewed legacy exception.', 'evidence_refs': ['customers.sql']}]
        self.reject(self.assessment(legacy_exceptions=wrong), 'actual source origin')
        allowed = [{'model_id': 'orders', 'reason': 'Explicitly retain this original implementation.', 'evidence_refs': ['orders.sql']}]
        intent.record_assessment(self.state, self.assessment(legacy_exceptions=allowed))
        self.assertEqual(self.row()['status'], 'accepted')
        self.assertEqual(self.row()['legacy_exception_model_ids'], ['orders'])
        intent.require_complete(self.state)
        (self.h.repo / 'orders.sql').write_text('select 3 as orders_id')
        self.assertEqual(self.row()['status'], 'stale')
        self.assertEqual(self.row()['legacy_exception_model_ids'], [])

    def test_decisions_and_responses_are_scoped_assessment_inputs(self):
        self.configure(); self.configure('catalog')
        before = {d: intent.assessment_bindings(self.state, d)['binding_sha256'] for d in ('commerce', 'catalog')}
        decision = {'id': 'grain-choice', 'model_ids': ['orders'], 'question': 'Retain the declared grain?'}
        self.state['workflow']['design']['decisions'].append(decision)
        changed = intent.assessment_bindings(self.state, 'commerce')['binding_sha256']
        self.assertNotEqual(changed, before['commerce'])
        self.assertEqual(intent.assessment_bindings(self.state, 'catalog')['binding_sha256'], before['catalog'])
        self.state['workflow']['responses'].append({'decision_id': 'grain-choice', 'answer': 'Retain it.'})
        self.assertNotEqual(intent.assessment_bindings(self.state, 'commerce')['binding_sha256'], changed)

    def test_unknown_assessment_and_missing_catalogue_preserve_explicit_drafts(self):
        self.configure(behavior='undecided')
        request = self.assessment(status='changes_requested')
        request['objective_results'][0].update(status='unresolved', source_evidence=[], mapping_ids=[], findings=['Need native type evidence.'])
        request['semantic_purpose'] = []
        intent.record_assessment(self.state, request)
        self.state['inputs']['catalogue'] = None
        self.state['readiness'].update(generation_ready=False, provisional_generation_available=True)
        selected = ['orders', 'customers']
        fixtures.stages.record_draft_request(self.state, selected, {'schema_version': 1, 'kind': 'provisional_code_request',
            'requester': 'synthetic-user', 'request_reference': 'synthetic://draft', 'request_text': 'Generate provisional code.',
            'bindings': fixtures.stages.draft_bindings(self.state, selected)})
        self.assertEqual(fixtures.stages.generation_mode(self.state, 'implementation', selected), 'provisional')
        with self.assertRaises(ValueError): intent.require_complete(self.state)

    def test_dangling_and_wrong_scope_evidence_rejected_atomically(self):
        self.configure()
        for mutation in ('mapping', 'source', 'hash', 'model', 'topic-purpose'):
            with self.subTest(mutation=mutation):
                request = self.assessment(); row = request['objective_results'][0]
                if mutation == 'mapping': row['mapping_ids'] = ['unknown.mapping']
                if mutation == 'source': row['source_evidence'][0] = {'reference': 'products.sql', 'sha256': self.sha('products.sql')}
                if mutation == 'hash': row['source_evidence'][0]['sha256'] = 'a' * 64
                if mutation == 'model': row['model_ids'] = ['products']
                if mutation == 'topic-purpose': request['semantic_purpose'][0]['consumer_or_metric_refs'] = ['invented.consumer']
                self.reject(request)

    def test_partial_semantic_and_transitional_dependencies_remain_visible(self):
        self.configure()
        request = self.assessment(); request['semantic_purpose'][0]['model_ids'] = ['orders']
        intent.record_assessment(self.state, request)
        self.assertEqual(self.row()['status'], 'partial')
        self.assertIn('semantic_purpose_unassessed', self.row()['gaps'])
        request = self.assessment(transitional_dependencies=[{'model_id': 'orders', 'reason': 'Legacy dependency remains.',
                                                              'resolution': 'Replace it in the next reviewed change.'}])
        intent.record_assessment(self.state, request)
        self.assertEqual(self.row()['transitional_dependency_count'], 1)
        self.assertEqual(self.row()['status'], 'partial')
        with self.assertRaises(ValueError): intent.require_complete(self.state)

    def test_legacy_exceptions_need_source_evidence_and_cannot_override_elimination(self):
        self.configure()
        request = self.assessment(legacy_exceptions=[{'model_id': 'orders', 'reason': 'Explicitly retained source behavior fits the objective.',
                                                     'evidence_refs': ['orders.sql']}])
        intent.record_assessment(self.state, request)
        self.assertEqual(self.row()['legacy_exception_model_ids'], ['orders'])
        request['legacy_exceptions'][0]['evidence_refs'] = ['fake-evidence']
        self.reject(request)
        self.configure(objectives=[{'id': 'shape', 'statement': 'Eliminate remaining legacy dependencies.', 'kind': 'eliminate_legacy_dependencies'}])
        self.reject(self.assessment(legacy_exceptions=[{'model_id': 'orders', 'reason': 'Keep it anyway.', 'evidence_refs': ['orders.sql']}]), 'eliminate-legacy')

    def test_named_root_revision_changes_and_source_output_guard_remain_separate(self):
        target = self.h.root / 'second-source'; target.mkdir(); (target / 'model.sql').write_text('select 1')
        source_roots.register(self.state, {'schema_version': 1, 'roots': [{'id': 'target', 'path': str(target), 'revision': 'rev1'}]}, self.h.run)
        self.configure(source_roles=[{'id': 'new-target', 'root_id': 'target', 'role': 'target_implementation'}])
        before = intent.scope_bindings(self.state)
        source_roots.register(self.state, {'schema_version': 1, 'roots': [{'id': 'target', 'path': str(target), 'revision': 'rev2'}]}, self.h.run)
        self.assertNotEqual(before['orders'], intent.scope_bindings(self.state)['orders'])
        self.assertNotIn('products', intent.scope_bindings(self.state))
        with self.assertRaises(ValueError): source_roots.ensure_output(self.state, target / 'generated.sql')

    def test_preserve_and_new_model_assessments_can_have_no_alignment(self):
        self.state['workflow'].pop('legacy_alignment')
        self.state['answers']['semantic_target'] = 'none'
        for objective in ('preserve', 'new_model'):
            self.configure(structural_objective=objective)
            request = self.assessment(); request['objective_results'][0]['mapping_ids'] = []
            request['semantic_purpose'] = []
            intent.record_assessment(self.state, request)
            self.assertEqual(self.row()['status'], 'accepted')
            intent.require_complete(self.state)


if __name__ == '__main__':
    unittest.main()
