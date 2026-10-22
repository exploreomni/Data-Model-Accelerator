"""Metadata inventory scaling stays bounded and does not execute source files."""
import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import design_coverage as coverage
import test_design_coverage as fixtures


class CoverageScalingTests(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.DesignCoverageTests(); self.h.setUp(); self.addCleanup(self.h.doCleanups)

    def test_4757_file_inventory_is_retained_without_copies_or_truncation(self):
        source = self.h.doc['sources'][0]
        raw = b'select 1 as id'
        digest = hashlib.sha256(raw).hexdigest()
        for index in range(4755):
            relative = 'model-%04d.sql' % index
            (self.h.source / relative).write_bytes(raw)
            source['inventory']['files'].append({'path': relative, 'sha256': digest,
                                                 'status': 'parsed', 'object_ids': []})
        # There are 4,756 files here and one in the second source root.
        result = self.h.save()
        retained = coverage.load(self.h.state)['request']
        self.assertEqual(result['counts']['files'], 4757)
        self.assertEqual(sum(len(s['inventory']['files']) for s in retained['sources']), 4757)
        self.assertEqual(len(list(self.h.source.iterdir())), 4756)
        self.assertNotIn('inventory_limit', self.h.codes())
        (self.h.source / 'model-0000.sql').write_text('select 2 as id')
        self.assertIn('source_stale', self.h.codes())

    def test_file_count_overflow_rejects_without_writing_a_smaller_inventory(self):
        with patch.object(coverage, 'MAX_FILES', 1), self.assertRaisesRegex(ValueError, 'file bound'):
            self.h.save()
        self.assertNotIn('design_coverage', self.h.state['workflow'])
        self.assertFalse((self.h.run / 'design-coverage').exists())

    def test_directory_entry_and_depth_limits_are_retained_as_partial_evidence(self):
        (self.h.source / 'a' / 'b' / 'c').mkdir(parents=True)
        with patch.object(coverage, 'MAX_DEPTH', 1):
            self.h.save()
            source = coverage.load(self.h.state)['request']['sources'][0]
            self.assertEqual(source['inventory']['status'], 'partial')
            self.assertIn('inventory_depth_limit', self.h.codes())
        with patch.object(coverage, 'MAX_ENTRIES', 1):
            self.assertIn('inventory_entry_limit', self.h.codes())

    def test_byte_exhaustion_is_visible_and_python_is_never_executed(self):
        marker = self.h.root / 'must-not-exist'
        (self.h.source / 'unsafe.py').write_text('raise RuntimeError("Source must never execute")')
        with patch.object(coverage, 'MAX_TOTAL_BYTES', 1):
            result = self.h.save()
            self.assertNotEqual(result['status'], 'complete')
            self.assertIn('file_unreadable', self.h.codes())
        self.assertFalse(marker.exists())


if __name__ == '__main__': unittest.main()
