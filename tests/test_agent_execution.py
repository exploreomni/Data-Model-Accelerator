"""Host observation receipts do not launch agents or infer absent evidence."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
import agent_context
import agent_execution as execution
from disclosure_fixtures import synthetic_disclosure


class AgentExecutionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / 'source'; self.source.mkdir()
        (self.source / 'orders.sql').write_text('select order_id from orders\n')
        self.packet = self.root / 'packet'
        disclosure = synthetic_disclosure(['packet'])
        classification = disclosure['artifacts']['packet']; classification['handling']['agent_input'] = 'allow'
        policy = disclosure['policy']
        policy['destinations']['agent_input'] = {'allowed_sensitivities': ['PUBLIC'], 'allowed_categories': []}
        policy['host_boundary'] = {'mode': 'presanitized_only', 'evidence_reference': 'synthetic-test'}
        context_request = {'schema_version': 1, 'kind': 'agent_context_request', 'task_id': 'orders-implementation',
            'role': 'analytics_engineer', 'mode': 'initial', 'bindings': {'task_fingerprint': 'a'*64},
            'brief': {'objective': 'Propose an order model', 'scope_ids': ['orders'], 'summary': 'Physical bindings unknown.',
                'decisions': [], 'unknowns': ['Uniqueness'], 'constraints': ['Provisional generation only'],
                'output_contract': 'Candidate model and evidence gaps', 'stop_conditions': ['Return the candidate']},
            'evidence': [{'id': 'source.orders', 'path': 'orders.sql',
                'sha256': self.sha((self.source/'orders.sql').read_bytes()), 'classification': classification,
                'purpose': 'Source expression', 'ranges': [[1, 1]]}],
            'policy': policy, 'classification': classification}
        agent_context.build_packet(self.source, context_request, self.packet)
        self.request = {'schema_version': 1, 'kind': 'agent_execution_request', 'task_id': 'orders-implementation',
            'run_id': 'run-1', 'packet_sha256': self.sha((self.packet/'TASK.md').read_bytes()),
            'source_context_receipt_sha256': self.sha((self.packet/'CONTEXT_RECEIPT.json').read_bytes()),
            'requested_model': 'requested-model', 'observed_model': None,
            'requested_effort': 'high', 'observed_effort': None, 'context_mode': 'unknown', 'host_run_reference': None}

    @staticmethod
    def sha(body):
        return hashlib.sha256(body).hexdigest()

    def record(self):
        return execution.record_execution(self.packet, self.request)

    def rewrite_receipt(self, change, repin=True):
        path = self.packet/'CONTEXT_RECEIPT.json'; document = json.loads(path.read_text())
        change(document); path.write_text(json.dumps(document))
        if repin: self.request['source_context_receipt_sha256'] = self.sha(path.read_bytes())

    def test_real_packet_pins_exact_bytes_and_never_infers_observed_model(self):
        before = {path.name: path.read_bytes() for path in self.packet.iterdir()}
        receipt = self.record()
        self.assertEqual(receipt['kind'], 'agent_execution_receipt')
        self.assertEqual(receipt['packet_bytes'], len(before['TASK.md']))
        self.assertEqual(receipt['packet_sha256'], self.sha(before['TASK.md']))
        self.assertEqual(receipt['source_context_receipt_sha256'], self.sha(before['CONTEXT_RECEIPT.json']))
        self.assertEqual(receipt['context_bindings'], {'task_fingerprint': 'a'*64})
        self.assertIsNone(receipt['observed_model']); self.assertEqual(receipt['observed_model_status'], 'unknown')
        self.assertEqual(receipt['requested_model'], 'requested-model')
        self.assertIsNone(receipt['observed_effort']); self.assertEqual(receipt['observed_effort_status'], 'unknown')
        self.assertEqual(receipt['assurance'], 'host_reported')
        self.assertFalse(receipt['execution_verified']); self.assertFalse(receipt['host_isolation_verified'])
        self.assertFalse(receipt['model_identity_verified']); self.assertFalse(receipt['usage_verified'])
        self.assertEqual(receipt['usage'], dict.fromkeys(execution.USAGE_FIELDS))
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.packet.iterdir()})
        self.assertNotIn('select order_id', json.dumps(receipt))
        self.assertEqual((self.source/'orders.sql').read_text(), 'select order_id from orders\n')

    def test_different_observed_settings_and_fresh_context_are_only_host_reports(self):
        self.request.update(observed_model='actual-host-model', observed_effort='medium',
                            context_mode='fresh', host_run_reference='host-run:123')
        receipt = self.record()
        self.assertEqual(receipt['observed_model'], 'actual-host-model')
        self.assertEqual(receipt['requested_model'], 'requested-model')
        self.assertEqual(receipt['observed_model_status'], 'host_reported')
        self.assertEqual(receipt['context_mode'], 'fresh')
        self.assertFalse(receipt['host_isolation_verified'])
        self.request['context_mode'] = 'inherited'
        self.assertEqual(self.record()['context_mode'], 'inherited')

    def test_explicit_usage_preserves_zero_and_unknown_without_derived_totals(self):
        self.request['usage'] = {'input_tokens': 100, 'output_tokens': 0, 'cache_read_tokens': None, 'cache_write_tokens': 23}
        self.request['usage_reference'] = 'host-counter:1'
        receipt = self.record()
        self.assertEqual(receipt['usage'], self.request['usage'])
        self.assertEqual(receipt['usage_reference'], 'host-counter:1')
        self.assertFalse(receipt['usage_verified'])
        self.assertNotIn('total_tokens', receipt); self.assertNotIn('cost', receipt)

    def test_all_missing_observations_remain_unknown(self):
        for key in ('requested_model', 'observed_model', 'requested_effort', 'observed_effort'):
            self.request[key] = None
        receipt = self.record()
        self.assertEqual(receipt['observed_model_status'], 'unknown')
        self.assertEqual(receipt['context_mode'], 'unknown')
        self.assertIsNone(receipt['host_run_reference'])

    def test_strict_request_rejects_extra_missing_and_wrong_version_fields(self):
        original = copy.deepcopy(self.request)
        variants = [dict(original, schema_version=True), dict(original, schema_version=2),
                    dict(original, kind='execution_log'), dict(original, raw_logs='private output')]
        missing = dict(original); del missing['observed_model']; variants.append(missing)
        for request in variants:
            with self.subTest(request=list(request)):
                with self.assertRaises(ValueError): execution.record_execution(self.packet, request)

    def test_bounded_single_line_observations_and_identifiers(self):
        for key, value in [('run_id', '../other'), ('task_id', []), ('observed_model', 'x'*257),
                           ('requested_model', 'model\nraw output'), ('observed_effort', 'x'*65),
                           ('host_run_reference', 'x'*1025), ('usage_reference', 42),
                           ('context_mode', []), ('context_mode', 'verified_fresh')]:
            request = copy.deepcopy(self.request); request[key] = value
            with self.subTest(key=key, value=type(value).__name__):
                with self.assertRaises(ValueError): execution.record_execution(self.packet, request)

    def test_usage_rejects_negative_bool_string_float_overflow_and_unknown_fields(self):
        for value in (-1, True, '4', 1.2, 2**63):
            self.request['usage'] = dict.fromkeys(execution.USAGE_FIELDS)
            self.request['usage']['input_tokens'] = value
            with self.subTest(value=value):
                with self.assertRaises(ValueError): self.record()
        for usage in ({}, {'total_tokens': 1}, None, []):
            self.request['usage'] = usage
            with self.assertRaises(ValueError): self.record()

    def test_changed_packet_or_receipt_pin_is_rejected(self):
        original = (self.packet/'TASK.md').read_bytes()
        (self.packet/'TASK.md').write_bytes(original + b'\n')
        with self.assertRaises(ValueError): self.record()
        (self.packet/'TASK.md').write_bytes(original)
        self.rewrite_receipt(lambda document: document.update(summary_bytes=1), repin=False)
        with self.assertRaises(ValueError): self.record()

    def test_repinning_does_not_hide_task_or_packet_metadata_mismatch(self):
        original = (self.packet/'CONTEXT_RECEIPT.json').read_bytes()
        for change in (lambda row: row.update(task_id='different-task'),
                       lambda row: row.update(packet_bytes=1),
                       lambda row: row.update(packet_sha256='b'*64),
                       lambda row: row.update(bindings={'task_fingerprint': 'b'*64}),
                       lambda row: row.update(specialist_executed=True),
                       lambda row: row.update(host_isolation_verified=True),
                       lambda row: row.update(role=[]),
                       lambda row: row.update(packet_bytes=True)):
            (self.packet/'CONTEXT_RECEIPT.json').write_bytes(original)
            self.rewrite_receipt(change)
            with self.assertRaises(ValueError): self.record()

    def test_missing_symlink_and_oversize_packet_inputs_fail(self):
        packet = self.packet/'TASK.md'; original = packet.read_bytes(); packet.unlink()
        with self.assertRaises(ValueError): self.record()
        outside = self.root/'outside.md'; outside.write_bytes(original); packet.symlink_to(outside)
        with self.assertRaises(ValueError): self.record()
        packet.unlink(); packet.write_bytes(b'x'*(execution.MAX_PACKET_BYTES+1))
        with self.assertRaises(ValueError): self.record()
        packet.write_bytes(original)
        alias = self.root/'alias'; alias.symlink_to(self.packet, target_is_directory=True)
        with self.assertRaises(ValueError): execution.record_execution(alias, self.request)

    def test_duplicate_and_nonfinite_context_json_cannot_be_pinned_as_valid(self):
        path = self.packet/'CONTEXT_RECEIPT.json'
        for body in ('{"kind":"agent_context_receipt","kind":"other"}', '{"packet_bytes":NaN}'):
            path.write_text(body); self.request['source_context_receipt_sha256'] = self.sha(path.read_bytes())
            with self.assertRaises(ValueError): self.record()


if __name__ == '__main__':
    unittest.main()
