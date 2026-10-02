"""Bounded repair state/history and external head-pin verification."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
import ae_common as common
import repair_events as repair


class RepairEventsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / 'repair.jsonl'
        self.cases, self.tasks = ['case_a', 'case_b'], ['engineer-orders']
        self.head = repair.ZERO_HEAD

    def event(self, kind='validation_failed', candidate='a', minute=0):
        return {'kind': kind, 'candidate_sha256': candidate * 64, 'evidence_sha256': 'e' * 64,
                'at': '2026-09-23T12:%02d:00+00:00' % minute, 'actor_id': 'reviewed-actor',
                'task_id': 'engineer-orders' if kind == 'repair_completed' else None,
                'case_ids': [] if kind == 'validation_passed' else ['case_a']}

    def append(self, event):
        result = repair.append_event(self.path, event, self.head, self.cases, self.tasks)
        self.head = result['event_sha256']
        return result

    def verify(self, head=None):
        return repair.verify_events(self.path, self.head if head is None else head, self.cases, self.tasks)

    def rewrite(self, events, rehash=False):
        previous = repair.ZERO_HEAD
        if rehash:
            for event in events:
                event['previous_sha256'] = previous
                event['event_sha256'] = common.hash_json({key: value for key, value in event.items() if key != 'event_sha256'})
                previous = event['event_sha256']
        self.path.write_text(''.join(json.dumps(event) + '\n' for event in events))
        return events[-1]['event_sha256'] if events else repair.ZERO_HEAD

    def test_new_and_empty_logs_require_zero_external_head(self):
        self.assertEqual(self.verify(), [])
        self.assertFalse(self.path.exists())
        with self.assertRaises(ValueError):
            self.verify('a' * 64)
        self.path.write_text('')
        self.assertEqual(self.verify(), [])

    def test_complete_failure_repair_validation_chain(self):
        original = self.event()
        first = self.append(original)
        self.assertEqual(original, self.event())
        self.assertEqual(first['sequence'], 1)
        self.assertEqual(first['previous_sha256'], repair.ZERO_HEAD)
        self.append(self.event('repair_completed', candidate='b', minute=1))
        final = self.append(self.event('validation_passed', candidate='b', minute=2))
        events = self.verify()
        self.assertEqual(len(events), 3)
        self.assertEqual(events[-1], final)

    def test_initial_pass_is_valid_and_terminal(self):
        self.append(self.event('validation_passed'))
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'after passed'):
            self.append(self.event(minute=1))
        self.assertEqual(self.path.read_bytes(), before)

    def test_wrong_expected_head_does_not_mutate_log(self):
        self.append(self.event())
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'expected_head'):
            repair.append_event(self.path, self.event('repair_completed', 'b', 1), repair.ZERO_HEAD, self.cases, self.tasks)
        self.assertEqual(self.path.read_bytes(), before)

    def test_replayed_sequence_is_rejected_even_with_valid_rehash(self):
        self.append(self.event())
        events = self.verify()
        events[0]['sequence'] = 2
        changed_head = self.rewrite(events, rehash=True)
        with self.assertRaisesRegex(ValueError, 'sequence'):
            self.verify(changed_head)

    def test_modified_old_event_and_rehashed_chain_cannot_match_external_pin(self):
        self.append(self.event())
        self.append(self.event('repair_completed', 'b', 1))
        events = self.verify()
        original_head = self.head
        events[0]['actor_id'] = 'changed-actor'
        self.rewrite(events)
        with self.assertRaisesRegex(ValueError, 'hash changed'):
            self.verify(original_head)
        self.rewrite(events, rehash=True)
        with self.assertRaisesRegex(ValueError, 'expected_head'):
            self.verify(original_head)

    def test_truncation_is_detected_against_caller_pin(self):
        self.append(self.event())
        self.append(self.event('repair_completed', 'b', 1))
        events = self.verify()
        self.rewrite(events[:1])
        with self.assertRaisesRegex(ValueError, 'expected_head'):
            self.verify()

    def test_timestamp_must_be_utc_and_nondecreasing(self):
        self.append(self.event(minute=2))
        original = self.event('repair_completed', 'b', 3)
        for value in ('2026-09-23T12:01:00Z', '2026-09-23T12:03:00', '2026-09-23T12:03:00-05:00'):
            event = dict(original, at=value)
            before = self.path.read_bytes()
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.append(event)
            self.assertEqual(self.path.read_bytes(), before)
        self.append(dict(original, at='2026-09-23T12:02:00Z'))
        self.assertEqual(len(self.verify()), 2)

    def test_state_transitions_and_candidate_identity_are_enforced(self):
        with self.assertRaises(ValueError):
            self.append(self.event('repair_completed'))
        self.assertFalse(self.path.exists())
        self.append(self.event())
        for event in (self.event('validation_passed', 'a', 1), self.event('validation_failed', 'a', 1),
                      self.event('repair_completed', 'a', 1)):
            with self.subTest(event=event), self.assertRaises(ValueError):
                self.append(event)
        self.append(self.event('repair_completed', 'b', 1))
        for event in (self.event('repair_completed', 'c', 2), self.event('validation_passed', 'a', 2)):
            with self.subTest(event=event), self.assertRaises(ValueError):
                self.append(event)

    def test_repair_limit_is_three_and_fourth_does_not_mutate(self):
        self.append(self.event())
        for index, candidate in enumerate(('b', 'c', 'd'), 1):
            self.append(self.event('repair_completed', candidate, index * 2 - 1))
            self.append(self.event('validation_failed', candidate, index * 2))
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Repair limit'):
            self.append(self.event('repair_completed', 'e', 7))
        self.assertEqual(self.path.read_bytes(), before)

    def test_event_fields_ids_and_hashes_are_strict(self):
        mutations = [lambda e: e.update(sequence=1), lambda e: e.update(candidate_sha256='bad'),
                     lambda e: e.update(evidence_sha256='F' * 64), lambda e: e.update(actor_id=' '),
                     lambda e: e.update(case_ids=[]), lambda e: e.update(case_ids=['absent']),
                     lambda e: e.update(case_ids=['case_a', 'case_a']), lambda e: e.update(task_id='engineer-orders')]
        for mutate in mutations:
            event = self.event()
            mutate(event)
            with self.subTest(event=event), self.assertRaises(ValueError):
                self.append(event)
        self.assertFalse(self.path.exists())
        self.append(self.event())
        with self.assertRaisesRegex(ValueError, 'known task_id'):
            self.append(dict(self.event('repair_completed', 'b', 1), task_id=None))

    def test_partial_jsonl_duplicate_json_keys_and_oversize_are_rejected(self):
        self.append(self.event())
        original = self.path.read_bytes()
        for content in (original.rstrip(b'\n'), original.replace(b'"sequence":1', b'"sequence":1,"sequence":1'),
                        b' ' * (repair.MAX_BYTES + 1)):
            self.path.write_bytes(content)
            with self.assertRaises(ValueError):
                self.verify()

    def test_symlink_and_path_escape_are_rejected_without_writing_target(self):
        target = self.root / 'original.jsonl'
        target.write_text('')
        self.path.symlink_to(target)
        with self.assertRaises(ValueError):
            self.append(self.event())
        self.assertEqual(target.read_text(), '')
        self.path.unlink()
        with self.assertRaises(ValueError):
            repair.append_event(self.root / 'subdir/../repair.jsonl', self.event(), self.head, self.cases, self.tasks)


if __name__ == '__main__':
    unittest.main()
