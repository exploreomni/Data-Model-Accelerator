"""Independent mapping and draft-write QA, using synthetic data only.

Native fragments below deliberately exercise source/target accountability rather
than claiming native UI grammar or visual/behavioral parity qualification.
"""
import base64
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import looker_source
import omni_dashboard as dashboard
import omni_dashboard_native as draft
import test_omni_native_independent as native_cases
from test_omni_native_independent import Remote, RUNTIME, candidate, context, uid, native
from test_looker_source_independent import independent_dashboard, independent_inventory, independent_provenance


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def source_contract():
    return looker_source.parse_dashboard(independent_dashboard(), independent_provenance(), independent_inventory())


def reviewed(mapping):
    mapping['review'] = {'status': 'approved', 'reference': 'synthetic://independent-mapping-review',
                         'mapping_sha256': digest({k: v for k, v in mapping.items() if k != 'review'})}
    return mapping


def mapped(value, pointer, fragment):
    return {'status': 'mapped', 'source_sha256': digest(value), 'target_pointer': pointer,
            'target_sha256': digest(fragment)}


def mapping_for(contract):
    model_id = '10000000-0000-4000-8000-000000000001'
    mapping = dashboard.template(contract, 'a' * 64, model_id)
    payload = mapping['native_payload']
    payload['name'] = 'Synthetic independent operations'
    for index, tile in enumerate(contract['tiles'], 1):
        key = str(index)
        pointer = '/queryPresentations/data/' + key
        fragment = {'type': 'query', 'name': 'Synthetic ' + key, 'topicName': 'fleet',
                    'query': {'fields': ['fleet.journeys']}} if tile['kind'] == 'data' else {
                    'type': 'blank', 'name': 'Interpretation', 'text': 'Distinct synthetic populations.'}
        payload['queryPresentations']['data'][key] = fragment
        payload['queryPresentations']['order'].append(key)
        entry = mapped(tile, pointer, fragment)
        # Independent explicit list, not generated through production facets().
        entry['behavior'] = {name: mapped(tile.get(name), pointer, fragment) for name in (
            'query', 'calculations', 'filter_listeners', 'visualizations', 'text', 'source_payload')}
        mapping['tiles'][tile['id']] = entry
    for index, source_filter in enumerate(contract['filters'], 1):
        key = 'synthetic-control-' + str(index)
        pointer = '/controls/data/' + key
        fragment = {'synthetic_unqualified_filter': source_filter['source_payload']['name']}
        payload['controls']['data'][key] = fragment
        payload['controls']['order'].append(key)
        mapping['filters'][source_filter['id']] = mapped(source_filter, pointer, fragment)
        mapping['filters'][source_filter['id']]['behavior'] = {
            'source_payload': mapped(source_filter['source_payload'], pointer, fragment)}
    payload['containers'] = [{'synthetic_unqualified_layout': {'tile_order': ['1', '2', '3']}}]
    mapping['layout'] = mapped(contract['layouts'], '/containers', payload['containers'])
    return reviewed(mapping)


class DashboardMappingIndependentTests(unittest.TestCase):
    def setUp(self):
        self.source = source_contract()
        self.mapping = mapping_for(self.source)

    def test_accounted_mapping_is_neither_native_nor_business_acceptance(self):
        result = dashboard.build(self.source, self.mapping)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['coverage'], {'tiles': 3, 'data_tiles': 2, 'text_tiles': 1, 'filters': 2})
        self.assertFalse(result['native_verified'])
        self.assertFalse(result['acceptance_ready'])
        self.assertIn('not source completeness', result['assurance'])
        self.assertEqual(dashboard.verify_build(result), result)

    def test_template_has_every_source_item_and_stays_incomplete(self):
        template = dashboard.template(self.source, 'a' * 64, self.mapping['target_model_id'])
        result = dashboard.build(self.source, template)
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(set(template['tiles']), {'tile-orders', 'tile-cases', 'tile-context'})
        self.assertEqual(set(template['filters']), {'filter-window', 'filter-region'})
        self.assertTrue(result['manual_steps'])

    def test_omitted_data_text_or_filter_has_no_silent_disposition(self):
        for collection, identity in (('tiles', 'tile-orders'), ('tiles', 'tile-context'), ('filters', 'filter-window')):
            mapping = copy.deepcopy(self.mapping)
            mapping[collection].pop(identity)
            with self.subTest(collection=collection, identity=identity), self.assertRaises(ValueError):
                dashboard.build(self.source, reviewed(mapping))

    def test_two_source_tiles_cannot_share_target_even_with_fresh_review(self):
        mapping = copy.deepcopy(self.mapping)
        entry = mapping['tiles']['tile-cases']
        fragment = mapping['native_payload']['queryPresentations']['data']['1']
        entry.update(target_pointer='/queryPresentations/data/1', target_sha256=digest(fragment))
        for value in entry['behavior'].values():
            value.update(target_pointer='/queryPresentations/data/1', target_sha256=digest(fragment))
        with self.assertRaises(ValueError):
            dashboard.build(self.source, reviewed(mapping))

    def test_filter_listener_facet_cannot_be_omitted_or_rebound_to_other_tile(self):
        for mutation in ('omitted', 'other-tile'):
            mapping = copy.deepcopy(self.mapping)
            behavior = mapping['tiles']['tile-orders']['behavior']
            if mutation == 'omitted': behavior.pop('filter_listeners')
            else: behavior['filter_listeners'] = mapped(self.source['tiles'][0]['filter_listeners'], '/queryPresentations/data/2',
                                                        mapping['native_payload']['queryPresentations']['data']['2'])
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                dashboard.build(self.source, reviewed(mapping))

    def test_source_payload_reparse_prevents_fabricated_canonical_queries(self):
        modified = copy.deepcopy(self.source)
        modified['tiles'][0]['query']['filters'] = {}
        with self.assertRaises(ValueError):
            dashboard.template(modified, 'a' * 64, self.mapping['target_model_id'])

    def test_native_layout_or_text_change_invalidates_fragment_and_review(self):
        for kind in ('layout', 'text', 'filter'):
            mapping = copy.deepcopy(self.mapping)
            if kind == 'layout': mapping['native_payload']['containers'][0]['synthetic_unqualified_layout']['tile_order'].reverse()
            elif kind == 'text': mapping['native_payload']['queryPresentations']['data']['3']['text'] = 'Unreviewed interpretation'
            else: mapping['native_payload']['controls']['data']['synthetic-control-1']['synthetic_unqualified_filter'] = 'Changed'
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                dashboard.build(self.source, mapping)

    def test_manual_behavior_remains_blocking_even_with_approved_mapping(self):
        self.mapping['tiles']['tile-orders']['behavior']['filter_listeners'] = {
            'status': 'manual', 'source_sha256': digest(self.source['tiles'][0]['filter_listeners']),
            'reason': 'Native filter interaction requires review'}
        result = dashboard.build(self.source, reviewed(self.mapping))
        self.assertEqual(result['status'], 'incomplete')
        self.assertTrue(any('filter_listeners' in item['item'] for item in result['manual_steps']))

    def test_extra_native_tile_or_control_is_not_unaccounted(self):
        for collection in ('queryPresentations', 'controls'):
            mapping = copy.deepcopy(self.mapping)
            data = mapping['native_payload'][collection]
            data['data']['99'] = copy.deepcopy(next(iter(data['data'].values())))
            data['order'].append('99')
            with self.subTest(collection=collection), self.assertRaises(ValueError):
                dashboard.build(self.source, reviewed(mapping))

    def test_query_and_text_kinds_cannot_be_swapped(self):
        self.mapping['native_payload']['queryPresentations']['data']['3'] = {
            'type': 'query', 'topicName': 'fleet', 'query': {'fields': ['fleet.journeys']}}
        entry = self.mapping['tiles']['tile-context']
        entry['target_sha256'] = digest(self.mapping['native_payload']['queryPresentations']['data']['3'])
        for behavior in entry['behavior'].values(): behavior['target_sha256'] = entry['target_sha256']
        with self.assertRaises(ValueError):
            dashboard.build(self.source, reviewed(self.mapping))

    def test_final_build_mutations_cannot_be_accepted_by_rehashing_alone(self):
        spec = dashboard.build(self.source, self.mapping)
        for key, value in (('native_verified', True), ('acceptance_ready', True), ('manual_steps', ['hidden']),
                           ('coverage', {'tiles': 2}), ('source_gaps', [{'code': 'fabricated'}])):
            changed = copy.deepcopy(spec); changed[key] = value
            changed['build_sha256'] = digest({k: v for k, v in changed.items() if k != 'build_sha256'})
            with self.subTest(key=key), self.assertRaises(ValueError): dashboard.verify_build(changed)

    def test_unsupported_active_content_and_sensitive_text_cannot_leave_builder(self):
        for text in ('<img src=x>', 'javascript:alert(1)', 'https://unapproved.invalid', 'SYNTHETIC_PHI_CANARY'):
            mapping = copy.deepcopy(self.mapping)
            mapping['native_payload']['queryPresentations']['data']['3']['text'] = text
            with self.subTest(kind=text.split(':')[0]), self.assertRaises(ValueError):
                dashboard.build(self.source, reviewed(mapping))

    def test_json_pointer_escapes_and_array_indices_are_strict(self):
        self.assertEqual(dashboard.pointer({'a/b': {'~': ['ok']}}, '/a~1b/~0/0'), 'ok')
        for pointer in ('/a~2b', '/a~1b/~0/-1', '/a~1b/~0/00', '/a~1b/~0/1'):
            with self.subTest(pointer=pointer), self.assertRaises(ValueError):
                dashboard.pointer({'a/b': {'~': ['ok']}}, pointer)

    def test_unresolved_merged_feature_stays_manual_even_when_every_mapping_is_approved(self):
        payload = independent_dashboard()
        payload['dashboard_elements'][0]['result_maker']['merge_result_id'] = 'unresolved-merge'
        contract = looker_source.parse_dashboard(payload, independent_provenance(), independent_inventory())
        result = dashboard.build(contract, mapping_for(contract))
        self.assertEqual(result['status'], 'incomplete')
        self.assertTrue(result['source_gaps'])
        self.assertTrue(result['manual_steps'])

    def test_recomputed_source_gaps_cannot_be_erased_from_canonical_evidence(self):
        payload = independent_dashboard()
        payload['dashboard_elements'][0]['result_maker']['merge_result_id'] = 'unresolved-merge'
        contract = looker_source.parse_dashboard(payload, independent_provenance(), independent_inventory())
        self.assertTrue(contract['gaps'])
        altered = copy.deepcopy(contract)
        altered['gaps'] = []
        with self.assertRaises(ValueError):
            dashboard.template(altered, 'a' * 64, self.mapping['target_model_id'])


class DraftRemote(Remote):
    def __init__(self, target, files):
        super().__init__(target, files)
        self.document_id = 'synthetic-dashboard'
        self.document = {'modelId': target['model_id'], 'workbookModelId': uid(20),
                         'name': 'Existing synthetic document', 'description': None,
                         'queryPresentations': {'data': {'1': {'type': 'blank', 'name': 'Seed'}}, 'order': ['1']},
                         'controls': {'data': {}, 'order': []}, 'containers': []}
        self.drafts = []
        self.draft_document = None
        self.access = [{'id': target['principal_id'], 'type': 'user', 'role': 'OWNER',
                        'accessSource': 'direct', 'accessBoost': False}]
        self.patch_error = None
        self.patch_commits_before_error = False
        self.patch_status = 200
        self.readback_mutation = None
        self.draft_reads = 0

    def request(self, method, path, params=None, body=None):
        prefix = '/api/v2/documents/' + self.document_id
        is_document = path.startswith(prefix) or path in (
            '/api/v1/documents/' + self.document_id + '/drafts',
            '/api/v1/documents/' + self.document_id + '/access-list')
        if not is_document:
            return super().request(method, path, params, body)
        self.calls.append({'method': method, 'path': path, 'params': copy.deepcopy(params), 'body': copy.deepcopy(body)})
        if path.endswith('/access-list'):
            value = {'principals': self.access, 'pageInfo': {'hasNextPage': False, 'nextCursor': None, 'totalRecords': len(self.access)}}
        elif path.endswith('/drafts'):
            value = self.drafts
        elif path == prefix and method == 'GET':
            value = self.document
        elif path == prefix + '/draft' and method == 'PATCH':
            if self.patch_status != 200:
                return native.Response(self.patch_status, canonical({'error': 'synthetic error'}))
            if self.patch_error is None or self.patch_commits_before_error:
                self.drafts.append({'identifier': 'synthetic-created-draft', 'publishedIdentifier': self.document_id,
                                    'workbookModelId': uid(21), 'branch': {'id': self.target['branch_id']},
                                    'status': 'active', 'draftOutOfDate': False})
                self.draft_document = copy.deepcopy(self.document)
                self.draft_document.update({key: copy.deepcopy(value) for key, value in body.items() if key != 'branchId'})
                self.draft_document.update(workbookModelId=uid(21), draftOf={'identifier': self.document_id})
            if self.patch_error:
                raise self.patch_error
            value = {'identifier': self.document_id, 'draftIdentifier': 'synthetic-created-draft',
                     'name': self.draft_document['name'], 'description': self.draft_document['description']}
        elif path == prefix + '/draft/synthetic-created-draft' and method == 'GET':
            self.draft_reads += 1
            if self.readback_mutation:
                self.readback_mutation(self)
            value = self.draft_document
        else:
            raise AssertionError('Unexpected draft endpoint')
        return native.Response(200, canonical(value))


@unittest.skipUnless(RUNTIME, 'Pinned optional semantic/deployment dependencies required')
class DashboardNativeIndependentTests(unittest.TestCase):
    def setUp(self):
        support = native_cases.NativeIndependentTests()
        support.setUp()
        self.addCleanup(support.doCleanups)
        self.root, self.candidate_root, self.policy_path = support.root, support.candidate_root, support.policy_path
        self.target, self.key, self.policy = support.target, support.key, support.policy
        self.remote = DraftRemote(self.target, candidate())
        self.policy['destinations']['dev'] = dict(self.target, document_id=self.remote.document_id)
        self.policy_path.write_bytes(canonical(self.policy)); self.policy_path.chmod(0o600)
        self.source = source_contract()
        self.mapping = mapping_for(self.source)
        self.mapping['candidate_sha256'] = digest(candidate())
        self.build = dashboard.build(self.source, reviewed(self.mapping))
        self.request = {'schema_version': 1, 'kind': 'omni_dashboard_native_request', 'run_id': 'draft-independent-1',
                        'destination_id': 'dev', 'target': copy.deepcopy(self.target), 'document_id': self.remote.document_id,
                        'build_spec': self.build, 'model_files': candidate(), 'model_context': context(),
                        'expected_model': self.remote.expected(), 'expected_document_sha256': digest(self.remote.document),
                        'expected_drafts_sha256': digest(self.remote.drafts),
                        'expected_access_sha256': digest(sorted(self.remote.access, key=digest))}

    def approval(self, overrides=None):
        now = datetime.now(timezone.utc)
        preflight = {name: True for name in ('principal_namespace_verified', 'permissions_verified', 'existing_destination_approved',
                                           'synthetic_data_only', 'isolated_destination', 'branch_exclusive', 'document_exclusive')}
        preflight.update(target_sha256=digest(self.target), document_id=self.remote.document_id,
                         audience_sha256=self.request['expected_access_sha256'], access_policy_sha256='d' * 64,
                         evidence_sha256='e' * 64, evidence_reference='synthetic://independent-draft-access')
        if overrides: preflight.update(overrides)
        payload = {'schema_version': 1, 'kind': 'deployment_attestation', 'purpose': 'deployment_approval',
                   'mode': self.policy['mode'], 'issuer': 'review-service', 'actor': 'reviewer', 'id': 'draft-independent-approval',
                   'review_reference': 'synthetic://independent-draft-review',
                   'issued_at': (now - timedelta(minutes=1)).isoformat(), 'expires_at': (now + timedelta(minutes=30)).isoformat(),
                   'bindings': draft.request_bindings(self.request, hashlib.sha256(self.policy_path.read_bytes()).hexdigest()),
                   'claims': {'preflight': preflight}}
        return {'payload': payload, 'signature': base64.b64encode(self.key.sign(canonical(payload))).decode()}

    def run_draft(self, approval=None):
        return draft.run(self.request, policy_path=self.policy_path, candidate_root=self.candidate_root,
                         approval=self.approval() if approval is None else approval, transport=self.remote)

    def writes(self):
        return [call for call in self.remote.calls if call['method'] != 'GET']

    def test_draft_creation_preserves_published_seed_and_does_not_publish(self):
        original = copy.deepcopy(self.remote.document)
        receipt = self.run_draft()
        self.assertEqual(receipt['status'], 'simulated_passed', receipt)
        self.assertEqual(self.remote.document, original)
        self.assertEqual([call['method'] for call in self.writes()], ['PATCH'])
        self.assertEqual(self.writes()[0]['path'], '/api/v2/documents/synthetic-dashboard/draft')
        self.assertEqual(self.writes()[0]['body']['branchId'], self.target['branch_id'])
        self.assertFalse(receipt['native_verified'])
        self.assertFalse(receipt['published']); self.assertFalse(receipt['dashboard_tested'])
        self.assertEqual(set(self.remote.draft_document['queryPresentations']['data']), {'1', '2', '3'})

    def test_existing_branch_draft_is_preserved_without_any_write(self):
        self.remote.drafts = [{'identifier': 'existing-branch-draft', 'publishedIdentifier': self.remote.document_id,
                               'workbookModelId': uid(22), 'branch': {'id': self.target['branch_id']},
                               'status': 'active', 'draftOutOfDate': False}]
        self.request['expected_drafts_sha256'] = digest(self.remote.drafts)
        before = copy.deepcopy(self.remote.drafts)
        self.assertEqual(self.run_draft()['status'], 'blocked')
        self.assertEqual(self.remote.drafts, before)
        self.assertEqual(self.writes(), [])

    def test_unmapped_existing_tile_cannot_be_hidden_by_shallow_merge(self):
        self.remote.document['queryPresentations']['data']['99'] = {'type': 'blank', 'name': 'Existing work'}
        self.remote.document['queryPresentations']['order'].append('99')
        self.request['expected_document_sha256'] = digest(self.remote.document)
        self.assertEqual(self.run_draft()['status'], 'blocked')
        self.assertEqual(self.writes(), [])

    def test_missing_tile_filter_text_or_layout_in_readback_fails(self):
        def omit_tile(remote):
            remote.draft_document['queryPresentations']['data'].pop('2', None)
            remote.draft_document['queryPresentations']['order'] = ['1', '3']
        def omit_filter(remote):
            remote.draft_document['controls']['data'].pop('synthetic-control-1', None)
            remote.draft_document['controls']['order'] = ['synthetic-control-2']
        for mutation in (omit_tile, omit_filter,
                         lambda remote: remote.draft_document['queryPresentations']['data']['3'].update(text='Changed'),
                         lambda remote: remote.draft_document.update(containers=[])):
            # Each independent request requires its own runner state root.
            self.policy['state_root'] += '-next'
            self.policy_path.write_bytes(canonical(self.policy))
            self.remote = DraftRemote(self.target, candidate())
            self.remote.readback_mutation = mutation
            receipt = self.run_draft()
            self.assertEqual(receipt['status'], 'blocked', receipt)
            self.assertFalse(receipt['native_verified'])
            self.assertFalse(any(call['method'] in ('DELETE', 'POST') for call in self.remote.calls))

    def test_wrong_draft_parent_fails_readback(self):
        self.remote.readback_mutation = lambda remote: remote.draft_document.update(draftOf={'identifier': 'wrong-document'})
        self.assertEqual(self.run_draft()['status'], 'blocked')

    def test_unknown_committed_draft_is_reconciled_without_duplicate_patch(self):
        self.remote.patch_error = native.TransportError('transport.timeout', uncertain=True)
        self.remote.patch_commits_before_error = True
        self.assertEqual(self.run_draft()['status'], 'pending')
        self.assertEqual(len(self.writes()), 1)
        self.remote.patch_error = None
        self.request['run_id'] = 'different-display-run'
        receipt = self.run_draft()
        self.assertEqual(receipt['status'], 'simulated_passed', receipt)
        self.assertEqual(len(self.writes()), 1)

    def test_unknown_uncommitted_draft_stays_pending_without_repeat_write(self):
        self.remote.patch_error = native.TransportError('transport.timeout', uncertain=True)
        self.assertEqual(self.run_draft()['status'], 'pending')
        self.remote.patch_error = None
        self.request['run_id'] = 'new-display-run'
        receipt = self.run_draft()
        self.assertEqual(receipt['status'], 'pending', receipt)
        self.assertEqual(len(self.writes()), 1)

    def test_conflict_never_clears_or_publishes_existing_content(self):
        self.remote.patch_status = 409
        receipt = self.run_draft()
        self.assertEqual(receipt['status'], 'failed')
        self.assertEqual([call['method'] for call in self.writes()], ['PATCH'])
        self.assertNotIn('clearExistingDraft', json.dumps(self.writes()))

    def test_changed_audience_or_incomplete_preflight_blocks_before_write(self):
        approval = self.approval({'document_exclusive': False})
        self.assertEqual(self.run_draft(approval)['status'], 'blocked')
        self.assertEqual(self.remote.calls, [])
        self.remote.access[0]['accessBoost'] = True
        self.assertEqual(self.run_draft()['status'], 'blocked')
        self.assertEqual(self.writes(), [])

    def test_journal_does_not_persist_provider_person_names(self):
        marker = 'SYNTHETIC_PII_CANARY_PROVIDER_NAME'
        self.remote.drafts = [{'identifier': 'existing-unrelated-draft', 'publishedIdentifier': self.remote.document_id,
                               'workbookModelId': uid(22), 'branch': {'id': uid(29)}, 'status': 'active', 'draftOutOfDate': False,
                               'createdBy': {'name': marker}, 'lastEditedBy': {'name': marker}}]
        self.request['expected_drafts_sha256'] = digest(self.remote.drafts)
        receipt = self.run_draft()
        self.assertEqual(receipt['status'], 'simulated_passed', receipt)
        self.assertNotIn(marker, json.dumps(receipt))
        for path in (self.root / 'private-state').glob('*.json'):
            self.assertNotIn(marker, path.read_text())


if __name__ == '__main__':
    unittest.main()
