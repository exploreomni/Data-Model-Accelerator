"""Metadata choices must invalidate earlier evidence without authorizing writes."""
import copy
import unittest

import test_guided_workflow as fixtures
import guided_workflow as workflow
from metadata_options import validate_options, validate_naming


OPTIONS = {'mode': 'comments', 'raw_comments': False, 'source_ids': [],
           'environments': ['development'], 'owner': None, 'taxonomy': None,
           'tag_namespace': [], 'unknown_handling': 'block', 'decision_reference': None}
BASE = fixtures.BASE


class MetadataOptionsTests(unittest.TestCase):
    def test_unknown_is_not_internal(self):
        options = copy.deepcopy(OPTIONS)
        options['unknown_handling'] = 'INTERNAL'
        with self.assertRaises(ValueError):
            validate_options(options)

    def test_raw_writes_need_exact_scope(self):
        options = dict(OPTIONS, raw_comments=True)
        with self.assertRaises(ValueError):
            validate_options(options)
        options['source_ids'] = ['source.erp.orders']
        self.assertEqual(validate_options(options), options)
        options['mode'] = 'documentation_only'
        with self.assertRaises(ValueError):
            validate_options(options)

    def test_naming_is_an_explicit_decision(self):
        self.assertEqual(validate_naming({'mode': 'preserve', 'domain': None, 'decision_reference': None})['mode'], 'preserve')
        with self.assertRaises(ValueError):
            validate_naming({'mode': 'type_domain', 'domain': 'SALES', 'decision_reference': None})

    def test_legacy_fingerprints_remain_stable(self):
        target, _, _ = workflow._selection(BASE)
        self.assertEqual(target['sha256'], workflow._digest({k: BASE[k] for k in ('framework', 'warehouse', 'semantic_target')}))


class MetadataInvalidationTests(unittest.TestCase):
    setUp = fixtures.GuidedWorkflowTests.setUp
    start = fixtures.GuidedWorkflowTests.start
    receipt = fixtures.GuidedWorkflowTests.receipt

    def test_metadata_change_invalidates_receipt(self):
        self.start(dict(BASE, metadata_policy=OPTIONS))
        self.receipt('metadata-evidence', ('target',))
        changed = dict(OPTIONS, environments=['development', 'production'])
        state = workflow.update_answers(self.run, {'metadata_policy': changed})
        evidence = next(e for e in state['evidence'] if e['kind'] == 'metadata-evidence')
        self.assertEqual(evidence['status'], 'stale')
        self.assertFalse(state['readiness']['execution_authorized'])


if __name__ == '__main__':
    unittest.main()
