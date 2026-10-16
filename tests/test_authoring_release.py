"""Protected promotion uses recomputed bytes, never a pasted passing label."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_authoring_evidence import contract
from ae_common import hash_file
import authoring_quality as quality
import authoring_release as release


@unittest.skipUnless(importlib.util.find_spec('sqlglot'), 'Optional SQL parser')
class AuthoringReleaseTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.source = self.root / 'source'; self.source.mkdir()
        self.candidate = self.root / 'candidate'; self.candidate.mkdir()
        (self.candidate / 'orders.sql').write_text('select count(1) as id from orders')
        self.contract = contract()
        self.contract.update(mode='reviewed_candidate', assumptions=[])
        self.contract['bindings']['catalogue_sha256'] = 'c' * 64
        self.contract['models'][0].update(depends_on=['table:orders'], expressions={'id': 'count(1)'})
        self.contract_path = self.root / 'contract.json'
        self.report_path = self.root / 'report.json'
        self.contract_path.write_text(json.dumps(self.contract))
        self.report = quality.evaluate(self.candidate, self.source, self.contract, ['orders.sql'], 'snowflake')
        self.report_path.write_text(json.dumps(self.report))
        self.reference = {'contract_path': str(self.contract_path), 'report_path': str(self.report_path),
                          'source_root': str(self.source)}
        self.selected = {'orders.sql': hash_file(self.candidate / 'orders.sql')}

    def bind(self):
        return release.bind(self.reference, self.candidate, self.selected, {'orders.sql'},
                            {'framework': 'dbt', 'warehouse': 'snowflake', 'context_sha256': 'd' * 64})

    def test_complete_static_scope_recomputed_without_execution_authority(self):
        bound = self.bind()
        self.assertEqual(bound['status'], 'passed')
        self.assertEqual(bound['required_count'], 1)
        self.assertNotIn('execution_authorized', bound)

    def test_omission_cannot_shrink_denominator(self):
        with self.assertRaisesRegex(ValueError, 'coverage'):
            release.bind(self.reference, self.candidate, self.selected, {'orders.sql', 'missing.sql'}, {'warehouse': 'snowflake'})

    def test_forged_counts_changed_code_and_checker_cannot_replay(self):
        changed = copy.deepcopy(self.report); changed['counts']['passed'] += 1
        self.report_path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, 'differs from current'): self.bind()
        self.report_path.write_text(json.dumps(self.report))
        with patch.object(quality, 'checker_version', return_value='0' * 64):
            with self.assertRaisesRegex(ValueError, 'differs from current'): self.bind()
        (self.candidate / 'orders.sql').write_text('select count(2) as id from orders')
        with self.assertRaisesRegex(ValueError, 'differs from current'): self.bind()

    def test_provisional_evidence_can_be_prepared_but_not_qualified_for_promotion(self):
        self.contract['mode'] = 'provisional'
        self.contract_path.write_text(json.dumps(self.contract))
        report = quality.evaluate(self.candidate, self.source, self.contract, ['orders.sql'], 'snowflake')
        self.report_path.write_text(json.dumps(report))
        bound = self.bind()
        with self.assertRaisesRegex(ValueError, 'reviewed candidates'):
            release.require_promotion({'action': 'promote', 'quality': {'authoring': bound}},
                                      {'mode': 'live', 'require_authoring_quality': True})

    def test_source_and_candidate_cannot_be_same_root(self):
        self.reference['source_root'] = str(self.candidate)
        with self.assertRaisesRegex(ValueError, 'separate'): self.bind()


class PromotionPolicyTests(unittest.TestCase):
    def test_default_and_nonproduction_routes_are_unchanged(self):
        for policy, action in [({'mode': 'live'}, 'promote'),
                               ({'mode': 'simulation', 'require_authoring_quality': True}, 'promote'),
                               ({'mode': 'live', 'require_authoring_quality': True}, 'publish_pr'),
                               ({'mode': 'live', 'require_authoring_quality': True}, 'deploy_development')]:
            release.require_promotion({'action': action}, policy)

    def test_protected_promotion_refuses_missing_failed_and_unknown_receipts(self):
        for status in (None, 'failed', 'not_run', 'unsupported', 'stale'):
            with self.assertRaisesRegex(ValueError, 'passing authoring'):
                release.require_promotion({'action': 'promote', 'quality': {'authoring':
                    {'status': status, 'mode': 'reviewed_candidate'}}},
                    {'mode': 'live', 'require_authoring_quality': True})


if __name__ == '__main__': unittest.main()
