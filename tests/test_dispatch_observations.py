import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
from ae_common import hash_json
import run_control as control
import test_run_control as fixtures


class DispatchObservationTests(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.RunControlTests()
        self.h.setUp(); self.addCleanup(self.h.doCleanups)

    def request(self, mode='specialist'):
        claim = self.h.claim('extract', execution_mode=mode)
        return {'schema_version': 1, 'attempt_id': 'extract-1', 'fingerprint': claim['fingerprint'],
                'execution_mode': mode, 'host_run_reference': 'synthetic://host/worker-1',
                'observed_model': None, 'observed_effort': None}

    def test_reservation_is_not_execution(self):
        request = self.request()
        self.assertEqual(control.public_summary(self.h.state)['dispatch_counts']['unobserved'], 1)
        receipt = control.record_dispatch(self.h.state, request)
        self.assertIsNone(receipt['observed_model'])
        self.assertFalse(receipt['execution_verified'])
        self.assertEqual(control.public_summary(self.h.state)['dispatch_counts']['specialist_reported'], 1)
        self.assertEqual(control.record_dispatch(self.h.state, request), receipt)

    def test_inline_needs_reason_and_is_not_counted_as_specialist(self):
        request = self.request('inline')
        with self.assertRaises(ValueError):
            control.record_dispatch(self.h.state, request)
        request['fallback_reason'] = 'Host does not expose delegation; coordinator performed a bounded pass'
        control.record_dispatch(self.h.state, request)
        counts = control.public_summary(self.h.state)['dispatch_counts']
        self.assertEqual(counts, {'specialist_reported': 0, 'inline_reported': 1, 'unobserved': 0})

    def test_dispatch_cannot_claim_another_attempt_or_changed_source(self):
        request = self.request()
        bad = copy.deepcopy(request); bad['fingerprint'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'binding changed'):
            control.record_dispatch(self.h.state, bad)
        (self.h.source / 'orders.sql').write_text('select changed')
        with self.assertRaisesRegex(ValueError, 'Inputs changed'):
            control.record_dispatch(self.h.state, request)

    def test_model_claims_cannot_replace_recorded_observation(self):
        request = self.request()
        control.record_dispatch(self.h.state, request)
        request['observed_model'] = 'different-model'
        with self.assertRaisesRegex(ValueError, 'immutable'):
            control.record_dispatch(self.h.state, request)

    def test_outputs_remain_reusable_after_truncated_summary(self):
        request = self.request()
        control.record_dispatch(self.h.state, request)
        (self.h.output / 'result.json').write_text('{"retained":"complete extraction"}')
        self.h.checkpoint('extract', 'outputs_recorded', ['result.json'])
        reused = self.h.claim('extract', attempt_id='extract-2')
        self.assertEqual(reused['action'], 'reuse')
        self.assertEqual(len(self.h.state['operations']['attempts']), 1)

    def test_runtime_git_observation_is_reused_only_while_content_matches(self):
        manifest = {'SKILL.md': 'a' * 64}
        identity = {'identity_scope': 'skill_scripts_references_agents_assets',
                    'runtime_sha256': hash_json(manifest), 'installed_revision': 'b' * 40}
        self.h.state['runtime_observations'] = [identity]
        with patch.object(control, 'content_manifest', return_value=manifest), patch.object(control, 'runtime_identity') as inspect:
            control.observe_runtime(self.h.state)
            inspect.assert_not_called()
        changed = {'SKILL.md': 'c' * 64}
        with patch.object(control, 'content_manifest', return_value=changed), patch.object(control, 'runtime_identity',
                return_value={**identity, 'runtime_sha256': hash_json(changed)}) as inspect:
            control.observe_runtime(self.h.state)
            inspect.assert_called_once()
        self.assertEqual(len(self.h.state['runtime_observations']), 2)
