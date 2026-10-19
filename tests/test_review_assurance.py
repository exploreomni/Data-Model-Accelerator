"""Versioned review evidence remains separate from approval and authoring."""
import copy
import unittest
import tempfile
import json
from pathlib import Path

import test_engagement_stages as fixtures
import review_assurance as assurance


class AssuranceCompatibilityTests(unittest.TestCase):
    def test_portal_projection_omits_private_evidence_and_approval_payloads(self):
        from delivery_portal import _workflow_presentation, _trim_workflow_details
        raw = {'review_assurance': {'schema_version': 1,
            'coverage': {'status': 'recorded', 'counts': {'total': 1},
                'document': {'path': '/private/evidence.json'}, 'source_contracts': ['private-source'],
                'rows': [{'id': 'occurrence', 'name': 'amount', 'status': 'unresolved', 'private': 'hidden-row'}]},
            'reuse': {'status': 'recorded', 'counts': {'total': 1, 'unassigned': 1}, 'approval': 'hidden-approval'},
            'reconciliation': {'status': 'conflicts', 'findings': [{'code': 'shared_rule_conflict',
                'message': 'Currency decision needed', 'model_ids': ['orders'], 'private': 'hidden-finding'}]}}}
        view = _workflow_presentation(raw)
        for private in ('/private/', 'private-source', 'hidden-row', 'hidden-approval', 'hidden-finding'):
            self.assertNotIn(private, json.dumps(view))
        data = {'workflow': view, 'review': {}}
        _trim_workflow_details(data)
        self.assertNotIn('review_assurance', data['workflow'])

    def test_decision_consequences_are_optional_and_scope_changes_to_their_stage(self):
        h = fixtures.StageTests('test_design_only_and_forged_approval_never_unlock_code')
        h.setUp(); self.addCleanup(h.doCleanups)
        doc = copy.deepcopy(h.doc)
        doc['revision'] = 2
        doc['decisions'] = [{'id': 'topic', 'question': 'Combine topics?',
            'options': [{'id': 'separate', 'label': 'Separate topics', 'consequences': 'Retains separate grains.'}],
            'recommendation': 'separate', 'reviewer_role': 'Model owner', 'model_ids': ['orders'],
            'asset_ids': [], 'blocking_stages': ['semantic'], 'rationale': 'Review grain safety.',
            'evidence_summary': 'Synthetic question.'}]
        h.action('import-design', document=doc)
        before = fixtures.stages.review_bindings(h.state, ['orders', 'products'])
        doc['revision'] = 3
        doc['decisions'][0]['options'][0]['consequences'] = 'Changes discoverability.'
        h.action('import-design', document=doc)
        after = fixtures.stages.review_bindings(h.state, ['orders', 'products'])
        self.assertEqual(before['stage_entities']['implementation'], after['stage_entities']['implementation'])
        self.assertNotEqual(before['stage_entities']['semantic']['orders'], after['stage_entities']['semantic']['orders'])
        self.assertEqual(before['stage_entities']['semantic']['products'], after['stage_entities']['semantic']['products'])

    def test_large_documents_are_stored_once_and_tampering_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory).resolve()
            state = {'workflow': {}}
            document = {'rows': list(range(10000))}
            assurance.save_document(state, 'coverage', document, directory)
            first = copy.deepcopy(state)
            assurance.save_document(state, 'coverage', document, directory)
            self.assertEqual(first, state)
            self.assertNotIn('rows', str(state))
            reference = assurance.records(state)['coverage']['document']
            self.assertEqual(assurance.load_document(reference), document)
            Path(reference['path']).write_text('{}')
            with self.assertRaisesRegex(ValueError, 'bytes changed'):
                assurance.load_document(reference)

    def test_symlinked_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / 'other').mkdir()
            (root / 'review-evidence').symlink_to(root / 'other', target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                assurance.save_document({'workflow': {}}, 'coverage', {}, root)

    def test_legacy_read_is_unassessed_and_does_not_migrate(self):
        state = {'schema_version': 1}
        self.assertEqual(assurance.public_summary(state)['coverage']['status'], 'unassessed')
        self.assertEqual(state, {'schema_version': 1})

    def test_unsupported_contract_is_not_replaced(self):
        for value in ({'schema_version': 2}, {'schema_version': True}, []):
            state = {'workflow': {'review_assurance': value}}
            before = copy.deepcopy(state)
            with self.assertRaisesRegex(ValueError, 'Unsupported'):
                assurance.save(state, 'coverage', {'schema_version': 1, 'kind': 'coverage'})
            self.assertEqual(state, before)

    def test_independent_slots_are_copied_and_preserved(self):
        state = {'workflow': {}}
        value = {'schema_version': 1, 'kind': 'coverage', 'rows': []}
        assurance.save(state, 'coverage', value)
        value['rows'].append('mutated')
        assurance.save(state, 'reuse', {'schema_version': 1, 'kind': 'reuse'})
        self.assertEqual(assurance.records(state)['coverage']['rows'], [])
        self.assertIsNone(assurance.records(state)['reconciliation'])

    def test_additive_records_preserve_scoped_review_and_draft_bindings(self):
        h = fixtures.StageTests('test_design_only_and_forged_approval_never_unlock_code')
        h.setUp(); self.addCleanup(h.doCleanups)
        scope = ['orders']
        before = fixtures.stages.review_bindings(h.state, scope)
        draft = fixtures.stages.draft_bindings(h.state, scope)
        original = copy.deepcopy(h.state['workflow'])
        assurance.save(h.state, 'coverage', {'schema_version': 1, 'kind': 'coverage'})
        self.assertEqual(before, fixtures.stages.review_bindings(h.state, scope))
        self.assertEqual(draft, fixtures.stages.draft_bindings(h.state, scope))
        for key in ('design', 'approvals', 'responses', 'tasks', 'runs'):
            self.assertEqual(original[key], h.state['workflow'][key])
        self.assertFalse(fixtures.stages.approved_entities(h.state))


if __name__ == '__main__':
    unittest.main()
