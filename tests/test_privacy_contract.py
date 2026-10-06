"""Declared policy gates, conservative lineage and explicit legacy migration."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import privacy_contract as privacy
from sensitive_data import scan_bytes


def approved_classification(sensitivity='INTERNAL', categories=()):
    value = privacy.new_classification(sensitivity)
    value.update(categories=list(categories), categories_known=True, review_status='approved',
                 review_reference='synthetic-review-only', evidence=[{'reference': 'synthetic-only', 'sha256': 'a' * 64}])
    value['lineage'] = {'status': 'complete', 'upstream_ids': [], 'transformation': 'source'}
    value['handling'] = {d: 'allow' for d in privacy.DESTINATIONS}
    return value


def approved_policy():
    value = privacy.default_policy()
    value.update(policy_id='synthetic-policy', review_status='approved', review_reference='synthetic-review',
                 evidence=[{'reference': 'synthetic-only', 'sha256': 'b' * 64}])
    value['destinations'] = {d: {'allowed_sensitivities': ['PUBLIC', 'INTERNAL'], 'allowed_categories': []}
                             for d in privacy.DESTINATIONS}
    value['host_boundary'] = {'mode': 'presanitized_only', 'evidence_reference': 'synthetic-only-not-host-proof'}
    return value


class PrivacyContractTests(unittest.TestCase):
    def setUp(self):
        self.policy = approved_policy()
        self.value = approved_classification()
        self.scan = scan_bytes(b'Approved column documentation', 'a.txt')

    def decide(self, value=None, policy=None, destination='share', scan=None):
        return privacy.evaluate_disclosure(value or self.value, policy or self.policy, destination,
                                           self.scan if scan is None else scan)

    def test_declared_allow_never_authenticates_authority(self):
        result = self.decide()
        self.assertTrue(result['allowed'])
        self.assertFalse(result['authorization_authenticated'])
        self.assertFalse(result['host_enforcement_authenticated'])

    def test_missing_policy_unknown_and_unapproved_records_are_denied(self):
        self.assertFalse(privacy.evaluate_disclosure(self.value, None, 'share', self.scan)['allowed'])
        for value in (privacy.new_classification(), privacy.new_classification('PUBLIC')):
            self.assertFalse(self.decide(value)['allowed'])

    def test_classification_is_multicategory_not_mutually_exclusive(self):
        value = approved_classification('RESTRICTED', ['PII', 'PHI', 'PCI'])
        self.assertEqual(privacy.validate_classification(value), [])
        self.assertFalse(self.decide(value)['allowed'])
        self.policy['destinations']['metadata'] = {'allowed_sensitivities': ['RESTRICTED'], 'allowed_categories': ['PII', 'PHI', 'PCI']}
        self.assertTrue(self.decide(value, destination='metadata')['allowed'])

    def test_allowlist_must_allow_all_categories_and_handling(self):
        value = approved_classification(categories=['PII', 'PHI'])
        self.policy['destinations']['share']['allowed_categories'] = ['PII']
        self.assertFalse(self.decide(value)['allowed'])
        self.policy['destinations']['share']['allowed_categories'].append('PHI')
        value['handling']['share'] = 'deny'
        self.assertFalse(self.decide(value)['allowed'])

    def test_scan_unknown_blocked_or_incomplete_cannot_pass(self):
        for report in ({}, {'status': 'clear'}, scan_bytes(b'SYNTHETIC_PHI_CANARY', 'a.txt'),
                       scan_bytes(b'\xff', 'a.txt')):
            self.assertFalse(self.decide(scan=report)['allowed'])
        self.scan['coverage']['complete'] = False
        self.assertFalse(self.decide()['allowed'])

    def test_protected_agent_input_cannot_be_enabled_by_declared_host_flag(self):
        self.assertTrue(self.decide(destination='agent_input')['allowed'])
        for mode in ('unenforced', 'claimed_enforced'):
            self.policy['host_boundary']['mode'] = mode
            self.assertFalse(self.decide(destination='agent_input')['allowed'])
        self.policy['host_boundary']['mode'] = 'presanitized_only'
        self.policy['destinations']['agent_input'] = {'allowed_sensitivities': ['RESTRICTED'], 'allowed_categories': ['PII']}
        self.assertFalse(self.decide(approved_classification('RESTRICTED', ['PII']), destination='agent_input')['allowed'])

    def test_unknown_and_restricted_private_drafts_never_grant_disclosure(self):
        for value in (privacy.new_classification(), approved_classification('RESTRICTED', ['PHI'])):
            result = privacy.evaluate_disclosure(value, None, 'private_candidate')
            self.assertEqual(result['status'], 'private_only')
            self.assertFalse(result['allowed'])

    def test_lineage_propagates_union_and_never_treats_hash_mask_as_declassification(self):
        originals = [approved_classification('CONFIDENTIAL', ['PII']), approved_classification('RESTRICTED', ['PHI'])]
        for transform in ('copy', 'alias', 'join', 'derive', 'hash', 'aggregate', 'mask', 'tokenize'):
            value = privacy.propagate_classification(originals, ['source-1', 'source-2'], transform)
            self.assertEqual(value['sensitivity'], 'RESTRICTED')
            self.assertEqual(value['categories'], ['PHI', 'PII'])
            self.assertEqual(value['review_status'], 'proposed')
            self.assertFalse(self.decide(value)['allowed'])
        self.assertEqual(originals[0]['review_status'], 'approved')

    def test_unknown_lineage_remains_unknown_but_keeps_known_categories(self):
        value = privacy.propagate_classification([privacy.new_classification(), approved_classification(categories=['PII'])], ['a', 'b'])
        self.assertEqual(value['sensitivity'], 'UNKNOWN')
        self.assertFalse(value['categories_known'])
        self.assertEqual(value['categories'], ['PII'])
        self.assertEqual(value['lineage']['status'], 'unresolved')

    def test_dictionary_resolved_lineage_cannot_be_redeclared_less_sensitive(self):
        original = approved_classification('RESTRICTED', ['PII', 'PHI'])
        derived = approved_classification('INTERNAL', ['PII'])
        derived['lineage'] = {'status': 'complete', 'upstream_ids': ['source'], 'transformation': 'hash'}
        errors = privacy.validate_lineage_classifications({'source': original, 'derived': derived})
        self.assertIn('lineage.sensitivity_downgrade[1]', errors)
        self.assertIn('lineage.category_downgrade[1]', errors)
        derived.update(sensitivity='RESTRICTED', categories=['PII', 'PHI'])
        self.assertEqual(privacy.validate_lineage_classifications({'source': original, 'derived': derived}), [])
        derived['lineage']['upstream_ids'] = ['missing']
        self.assertTrue(privacy.validate_lineage_classifications({'source': original, 'derived': derived}))
        derived['lineage']['upstream_ids'] = ['derived']
        self.assertIn('lineage.cycle_or_invalid_dependency', privacy.validate_lineage_classifications({'derived': derived}))
        derived['lineage']['transformation'] = 'source'
        self.assertIn('classification.lineage_incomplete', privacy.validate_classification(derived))

    def test_malformed_json_contract_types_return_safe_errors_without_crashing(self):
        for key in self.value:
            for invalid in (None, [], {}, True, 1):
                if type(invalid) is type(self.value[key]) and invalid == self.value[key]:
                    continue
                value=copy.deepcopy(self.value);value[key]=invalid
                self.assertTrue(privacy.validate_classification(value), key)
        self.assertFalse(self.decide(scan={'schema_version': 1, 'kind':'sensitive_data_scan',
                                           'status':'clear', 'coverage':None})['allowed'])

    def test_declared_known_is_not_valid_approval_without_evidence(self):
        for field, bad in [('categories', ['PII', 'PII']), ('categories_known', False),
                           ('evidence', []), ('review_reference', None), ('sensitivity', 'UNKNOWN')]:
            value = copy.deepcopy(self.value); value[field] = bad
            self.assertTrue(privacy.validate_classification(value), field)
        self.policy['destinations']['share']['allowed_sensitivities'] = ['UNKNOWN']
        self.assertTrue(privacy.validate_disclosure_policy(self.policy))

    def test_dictionary_extension_migration_is_explicit_and_preserves_originals(self):
        from test_metadata_contract import dictionary
        from data_dictionary_v2 import validate_dictionary
        value = dictionary(); column = value['models'][0]['columns'][0]
        value.pop('privacy_schema_version', None); column.pop('privacy', None)
        original = copy.deepcopy(value)
        result = privacy.migrate_dictionary_privacy(value)
        self.assertEqual(value, original)
        self.assertEqual(result['privacy_schema_version'], 1)
        self.assertEqual(result['models'][0]['columns'][0]['privacy']['review_status'], 'unresolved')
        self.assertEqual(result['models'][0]['columns'][0]['sensitivity'], column['sensitivity'])
        self.assertEqual(validate_dictionary(result), [])
        self.assertEqual(privacy.migrate_dictionary_privacy(result), result)
        result['models'][0]['columns'][0]['privacy']['sensitivity'] = 'PUBLIC'
        self.assertTrue(validate_dictionary(result))

    def test_cli_reports_only_codes_and_creates_no_unrequested_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for name, value in [('classification', self.value), ('policy', self.policy)]:
                (root / (name + '.json')).write_text(json.dumps(value))
            (root / 'input.txt').write_text('SYNTHETIC_PHI_CANARY')
            result = subprocess.run([sys.executable, '-B', privacy.__file__, 'evaluate',
                '--classification', str(root / 'classification.json'), '--policy', str(root / 'policy.json'),
                '--input', str(root / 'input.txt'), '--destination', 'share'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn('SYNTHETIC_PHI_CANARY', result.stdout + result.stderr)
            self.assertEqual(len(list(root.iterdir())), 3)

    def test_migration_cli_creates_private_candidate_without_overwriting(self):
        from test_metadata_contract import dictionary
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = root / 'dictionary.json'; output = root / 'private.json'
            source.write_text(json.dumps(dictionary(False)))
            command = [sys.executable, '-B', privacy.__file__, 'migrate-dictionary',
                       '--input', str(source), '--output', str(output)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertFalse(json.loads(result.stdout)['approval_granted'])
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 1)


if __name__ == '__main__':
    unittest.main()
