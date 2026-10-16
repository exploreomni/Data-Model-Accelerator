"""Bounded disclosure and evidence fidelity, without any model or network calls."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
import agent_context as context
from disclosure_fixtures import synthetic_disclosure
from specialist_profiles import load_profile, SOURCES, ROLE_ALIASES


class AgentContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.source = self.root / 'source'; self.source.mkdir()
        self.content = b'-- unrelated model\nselect order_id, amount from orders\n-- unrelated definition\n'
        (self.source / 'orders.sql').write_bytes(self.content)
        (self.source / 'unrelated.sql').write_text('UNRELATED_PROJECT_CONTENT')
        disclosure = synthetic_disclosure(['packet'])
        classification = disclosure['artifacts']['packet']
        classification['handling']['agent_input'] = 'allow'
        policy = disclosure['policy']
        policy['destinations']['agent_input'] = {'allowed_sensitivities': ['PUBLIC'], 'allowed_categories': []}
        policy['host_boundary'] = {'mode': 'presanitized_only', 'evidence_reference': 'synthetic-test-only'}
        self.request = {'schema_version': 1, 'kind': 'agent_context_request', 'task_id': 'orders-design',
                        'role': 'warehouse_architect', 'mode': 'initial', 'bindings': {'source': 'a' * 64},
                        'brief': {'objective': 'Propose order grain', 'scope_ids': ['orders'],
                                  'summary': 'Source declares order_id; uniqueness is unverified.',
                                  'decisions': [], 'unknowns': ['Actual key uniqueness'],
                                  'constraints': ['Read-only design; no implementation'],
                                  'output_contract': 'Return evidence-backed grain proposal and unresolved questions',
                                  'stop_conditions': ['Return when proposal or missing evidence is identified']},
                        'evidence': [{'id': 'source.orders', 'path': 'orders.sql',
                                      'sha256': hashlib.sha256(self.content).hexdigest(),
                                      'classification': copy.deepcopy(classification),
                                      'purpose': 'Observed source expression', 'ranges': [[2, 2]]}],
                        'policy': policy, 'classification': classification}

    def build(self, name='packet'):
        return context.build_packet(self.source, self.request, self.root / name)

    def test_only_selected_lines_disclosed_with_exact_pins_and_byte_counts(self):
        receipt = self.build()
        packet = (self.root / 'packet/TASK.md').read_bytes()
        self.assertIn(self.content.splitlines()[1], packet)
        for unrelated in (b'unrelated model', b'unrelated definition', b'UNRELATED_PROJECT_CONTENT'):
            self.assertNotIn(unrelated, packet)
        self.assertEqual(receipt['packet_sha256'], hashlib.sha256(packet).hexdigest())
        self.assertEqual(receipt['packet_bytes'], len(packet))
        self.assertEqual(receipt['selected_source_bytes'], len(self.content))
        self.assertEqual(receipt['evidence'][0]['source_sha256'], hashlib.sha256(self.content).hexdigest())
        self.assertEqual(receipt['file_coverage'], [{'id': 'source.orders', 'file_lines': 3,
                         'selected_lines': 1, 'complete_file_in_packet': False, 'semantic_extraction_verified': False}])
        self.assertFalse(receipt['specialist_executed'])
        self.assertFalse(receipt['host_isolation_verified'])
        self.assertEqual((self.source / 'orders.sql').read_bytes(), self.content)
        self.assertEqual((self.root / 'packet/TASK.md').stat().st_mode & 0o777, 0o600)
        self.assertEqual(sorted(p.name for p in (self.root / 'packet').iterdir()),
                         ['AGENT_INPUT_MANIFEST.json', 'CONTEXT_RECEIPT.json', 'TASK.md'])

    def test_same_input_produces_stable_packet_hash(self):
        first = self.build('first'); second = self.build('second')
        self.assertEqual(first['packet_sha256'], second['packet_sha256'])

    def test_all_source_profiles_fit_selected_scanned_packets_without_other_guides(self):
        self.request['role'] = 'source_specialist'
        for source in sorted(SOURCES):
            with self.subTest(source=source):
                selected = load_profile(source)
                self.request['source_type'] = source
                self.request['bindings']['specialist_profile'] = selected['sha256']
                receipt = self.build(source)
                packet = (self.root / source / 'TASK.md').read_text()
                data = json.loads(packet.split('## Task data and selected evidence\n\n')[1])
                self.assertEqual(data['specialist_profile'], selected)
                self.assertNotIn('UNRELATED_PROJECT_CONTENT', packet)
                self.assertNotIn('text', receipt['specialist_profile'])
                self.assertEqual(receipt['specialist_profile']['sha256'], selected['sha256'])
                self.assertLessEqual(receipt['packet_bytes'], context.DEFAULT_BYTES)
                self.assertEqual(receipt['bindings'], self.request['bindings'])

    def test_profile_pin_staleness_role_and_source_mismatches_fail_before_output(self):
        self.request.update(role='source_specialist', source_type='dbt')
        self.request['bindings']['specialist_profile'] = 'a' * 64
        with self.assertRaisesRegex(ValueError, 'profile changed'): self.build()
        self.request['bindings']['specialist_profile'] = load_profile('dbt')['sha256']
        self.request['source_type'] = '../dbt'
        with self.assertRaisesRegex(ValueError, 'Unsupported specialist source'): self.build()
        self.request['source_type'] = 'dbt'
        self.request['role'] = 'analytics_engineer'
        with self.assertRaisesRegex(ValueError, 'requires source_specialist'): self.build()
        self.assertFalse((self.root / 'packet').exists())

    def test_profile_bytes_do_not_bypass_packet_budget_or_disclosure_scan(self):
        self.request.update(role='source_specialist', source_type='dbt')
        selected = load_profile('dbt')
        self.request['bindings']['specialist_profile'] = selected['sha256']
        self.request['max_packet_bytes'] = 4096
        with self.assertRaisesRegex(ValueError, 'exceeds byte budget'): self.build()
        self.request.pop('max_packet_bytes')
        selected['text'] += '\nContact sample.person@example.com'
        selected['sha256'] = hashlib.sha256(selected['text'].encode()).hexdigest()
        self.request['bindings']['specialist_profile'] = selected['sha256']
        with patch.object(context, 'load_profile', return_value=selected):
            with self.assertRaisesRegex(ValueError, 'denied'): self.build()
        self.assertFalse((self.root / 'packet').exists())

    def test_legacy_review_role_aliases_are_explicit_and_keep_task_identity(self):
        for alias, canonical in ROLE_ALIASES.items():
            self.request['role'] = alias
            receipt = self.build(alias)
            self.assertEqual(receipt['role'], canonical)
            self.assertEqual(receipt['requested_role'], alias)
            self.assertEqual(receipt['task_id'], self.request['task_id'])
            data = json.loads((self.root / alias / 'TASK.md').read_text().split('## Task data and selected evidence\n\n')[1])
            self.assertEqual(data['requested_role'], alias)
            self.assertEqual(data['role'], canonical)
        self.request['role'] = 'invented_agent'
        with self.assertRaisesRegex(ValueError, 'Unsupported specialist role'): self.build()

    def test_two_object_source_excerpt_cannot_claim_full_file_coverage(self):
        content = b'view: orders { sql_table_name: orders ;; }\nview: returns { sql_table_name: returns ;; }\n'
        (self.source / 'orders.sql').write_bytes(content)
        self.request['role'] = 'source_specialist'
        self.request['evidence'][0].update(sha256=hashlib.sha256(content).hexdigest(), ranges=[[1, 1]])
        result = self.build('excerpt')
        self.assertFalse(result['file_coverage'][0]['complete_file_in_packet'])
        self.assertNotIn('view: returns', (self.root / 'excerpt/TASK.md').read_text())
        self.request['evidence'][0]['ranges'] = [[1, 2]]
        complete = self.build('complete')
        self.assertTrue(complete['file_coverage'][0]['complete_file_in_packet'])
        self.assertFalse(complete['file_coverage'][0]['semantic_extraction_verified'])

    def test_stale_hash_rejected_even_if_changed_lines_are_outside_excerpt(self):
        (self.source / 'orders.sql').write_bytes(self.content + b'-- changed contract\n')
        with self.assertRaisesRegex(ValueError, 'differs'):
            self.build()
        self.assertFalse((self.root / 'packet').exists())

    def test_range_errors_duplicate_ids_and_path_escapes_fail(self):
        for ranges in ([[0, 2]], [[2, 200]], [[2, 2], [2, 3]], [[True, 2]]):
            with self.subTest(ranges=ranges):
                self.request['evidence'][0]['ranges'] = ranges
                with self.assertRaises(ValueError): self.build()
        self.request['evidence'][0]['ranges'] = [[2, 2]]
        self.request['evidence'].append(copy.deepcopy(self.request['evidence'][0]))
        with self.assertRaisesRegex(ValueError, 'Duplicate'): self.build()
        self.request['evidence'].pop()
        self.request['evidence'][0]['path'] = '../orders.sql'
        with self.assertRaises(ValueError): self.build()

    def test_symlink_input_rejected(self):
        (self.source / 'link.sql').symlink_to(self.source / 'orders.sql')
        self.request['evidence'][0]['path'] = 'link.sql'
        with self.assertRaises(ValueError): self.build()

    def test_oversize_packet_fails_without_truncation_or_output(self):
        self.request['max_packet_bytes'] = 1024
        with self.assertRaisesRegex(ValueError, 'exceeds byte budget'): self.build()
        self.assertFalse((self.root / 'packet').exists())
        self.request['max_packet_bytes'] = 65536
        with self.assertRaisesRegex(ValueError, 'budget_reason'): self.build()
        self.request['budget_reason'] = 'Synthetic scoped schema with necessary evidence'
        self.build()

    def test_oversize_summary_cannot_consume_evidence_budget(self):
        self.request['brief']['summary'] = 'x' * 8193
        with self.assertRaisesRegex(ValueError, 'Summary exceeds'): self.build()

    def test_summary_sensitive_content_is_scanned_as_well_as_source(self):
        self.request['brief']['summary'] = 'Contact sample.person@example.com'
        with self.assertRaisesRegex(ValueError, 'denied'): self.build()
        self.assertFalse((self.root / 'packet').exists())

    def test_source_disclosure_denial_cannot_be_bypassed_by_public_packet_classification(self):
        self.request['evidence'][0]['classification']['handling']['agent_input'] = 'deny'
        with self.assertRaisesRegex(ValueError, 'denied'): self.build()

    def test_delta_requires_prior_pin_and_changed_scope_or_unresolved_findings(self):
        initial = self.build('initial')
        self.request['mode'] = 'delta'
        with self.assertRaisesRegex(ValueError, 'Delta'): self.build()
        self.request['delta'] = {'previous_packet_sha256': initial['packet_sha256'],
                                 'changed_ids': [], 'open_findings': [], 'reason': 'Targeted follow-up'}
        with self.assertRaisesRegex(ValueError, 'reuse the prior result'): self.build()
        self.request['delta']['open_findings'] = ['grain.orders.unproven']
        updated = self.build()
        self.assertNotEqual(initial['packet_sha256'], updated['packet_sha256'])
        self.assertIn('grain.orders.unproven', (self.root / 'packet/TASK.md').read_text())

    def test_write_failure_cleans_owned_output_and_preserves_existing_destination(self):
        with patch.object(context, 'write_json', side_effect=OSError('Synthetic disk failure')):
            with self.assertRaises(OSError): self.build()
        self.assertFalse((self.root / 'packet').exists())
        out = self.root / 'packet'; out.mkdir(); (out / 'keep.txt').write_text('keep')
        with self.assertRaises(ValueError): self.build()
        self.assertEqual((out / 'keep.txt').read_text(), 'keep')

    def test_destination_created_during_preparation_is_not_deleted(self):
        original_prepare = context.prepare

        def raced(root, request, output):
            if output == self.root / 'packet':
                output.mkdir(); (output / 'keep.txt').write_text('keep')
            return original_prepare(root, request, output)

        with patch.object(context, 'prepare', side_effect=raced):
            with self.assertRaises(ValueError): self.build()
        self.assertEqual((self.root / 'packet/keep.txt').read_text(), 'keep')

    def test_cli_runs_without_optional_dependencies(self):
        request = self.root / 'request.json'; request.write_text(json.dumps(self.request))
        result = subprocess.run([sys.executable, '-S', str(SCRIPTS / 'agent_context.py'),
                                 '--root', str(self.source), '--request', str(request),
                                 '--output', str(self.root / 'cli')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)['specialist_executed'])


if __name__ == '__main__':
    unittest.main()
