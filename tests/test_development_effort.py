"""Development complexity contracts, uncertainty and selective freshness checks."""
import copy
from pathlib import Path
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
import development_effort as effort


def package(identity, *, level='easy', dependencies=(), stage='implementation'):
    return {'id': identity, 'stage': stage, 'depends_on': list(dependencies),
            'model_ids': ['model.' + identity], 'material_inputs': {'grain.' + identity: 'a' * 64},
            'factors': {name: {'level': level, 'rationale': 'Reviewed bounded implementation pattern.',
                               'evidence_ids': ['reviewed-pattern']} for name in effort.FACTORS},
            'blockers': [], 'assumptions': []}


def request(packages=None):
    scope = {'stages': ['implementation'], 'excluded_stages': [s for s in effort.STAGES if s != 'implementation']}
    return {'schema_version': 1, 'kind': 'development_effort_request',
            'bindings': {'design_revision': 'design-1', 'design_material_sha256': 'a' * 64,
                         'scope_sha256': effort.digest(scope), 'route_sha256': 'b' * 64},
            'scope': scope, 'review': {'status': 'reviewed', 'reference': 'review/design-1'},
            'evidence': [{'id': 'reviewed-pattern', 'sha256': 'c' * 64}],
            'packages': packages or [package('orders')]}


class DevelopmentEffortTests(unittest.TestCase):
    def test_deterministic_assessment_and_no_input_mutation(self):
        source = request()
        before = copy.deepcopy(source)
        result = effort.assess_effort(source)
        self.assertEqual(result, effort.assess_effort(source))
        self.assertEqual(before, source)
        self.assertEqual(result['overall']['category'], 'easy')
        self.assertEqual(result['overall']['status'], 'assessed')
        self.assertEqual(result['overall']['confidence'], 'high')
        self.assertEqual(result['overall']['readiness'], 'ready')
        self.assertFalse(result['human_approval_authenticated'])
        self.assertFalse(result['execution_authorized'])
        self.assertFalse(result['deployment_authorized'])
        source['packages'][0]['blockers'].append('Later mutation')
        self.assertEqual(result['request'], before)

    def test_category_anchors_have_exact_labels(self):
        for category, label in zip(effort.CATEGORIES, ('Easy', 'Somewhat easy', 'Difficult', 'Very difficult')):
            with self.subTest(category=category):
                result = effort.assess_effort(request([package('orders', level=category)]))
                self.assertEqual((result['overall']['category'], result['overall']['label']), (category, label))

    def test_unknown_and_missing_evidence_block_instead_of_exaggerating_difficulty(self):
        for modification in ({'level': 'unknown'}, {'evidence_ids': []}):
            with self.subTest(modification=modification):
                source = request()
                source['packages'][0]['factors']['data_behavior'].update(modification)
                result = effort.assess_effort(source)
                self.assertEqual(result['overall']['status'], 'blocked')
                self.assertIsNone(result['overall']['category'])
                self.assertEqual(result['overall']['confidence'], 'low')
                self.assertEqual(result['overall']['readiness'], 'needs_discovery')
                self.assertTrue(result['packages'][0]['reasons'])

    def test_explicit_blocker_propagates_to_dependents_only(self):
        source = request([package('shared'), package('orders', dependencies=['shared']), package('independent')])
        source['packages'][0]['blockers'] = ['Waiting for approved development access.']
        report = effort.assess_effort(source)
        result = {row['id']: row for row in report['packages']}
        self.assertEqual(result['shared']['status'], 'assessed')
        self.assertEqual(result['orders']['status'], 'assessed')
        self.assertEqual(result['shared']['readiness'], 'blocked')
        self.assertEqual(result['orders']['readiness'], 'blocked')
        self.assertEqual(result['independent']['status'], 'assessed')
        self.assertEqual(result['independent']['readiness'], 'ready')
        self.assertEqual(report['overall']['category'], 'easy')
        self.assertEqual(report['overall']['readiness'], 'blocked')
        self.assertEqual(report['overall']['confidence'], 'high')
        self.assertIn('Blocked prerequisite: shared', result['orders']['reasons'])

    def test_unknown_prerequisite_removes_definitive_dependent_category(self):
        source = request([package('shared'), package('orders', dependencies=['shared']), package('independent')])
        source['packages'][0]['factors']['data_behavior']['level'] = 'unknown'
        report = effort.assess_effort(source)
        rows = {row['id']: row for row in report['packages']}
        self.assertIsNone(rows['orders']['category'])
        self.assertEqual(rows['orders']['readiness'], 'needs_discovery')
        self.assertEqual(rows['independent']['category'], 'easy')
        self.assertIsNone(report['overall']['category'])
        self.assertEqual(report['overall']['readiness'], 'needs_discovery')

    def test_shared_hard_dependency_cannot_be_averaged_away(self):
        source = request([package('shared', level='difficult'), package('orders', dependencies=['shared']),
                          package('customers', dependencies=['shared']), package('simple')])
        result = effort.assess_effort(source)
        self.assertEqual(result['overall']['category'], 'difficult')
        rows = {row['id']: row for row in result['packages']}
        self.assertEqual(rows['orders']['category'], 'difficult')
        self.assertIn('Difficulty includes prerequisite: shared', rows['orders']['reasons'])
        self.assertEqual(rows['simple']['category'], 'easy')

    def test_review_pending_and_assumptions_are_provisional(self):
        source = request([package('shared'), package('orders', dependencies=['shared'])])
        source['packages'][0]['assumptions'] = ['Existing retry pattern will apply.']
        result = effort.assess_effort(source)
        self.assertEqual(result['overall']['status'], 'provisional')
        self.assertEqual(result['overall']['confidence'], 'medium')
        self.assertEqual(result['overall']['category'], 'easy')
        self.assertEqual(result['overall']['readiness'], 'ready')
        source['packages'][0]['assumptions'] = []
        source['review'] = {'status': 'pending', 'reference': None}
        result = effort.assess_effort(source)
        self.assertEqual(result['overall']['status'], 'provisional')
        self.assertEqual(result['overall']['readiness'], 'review_pending')
        self.assertIn('Design review is pending.', result['packages'][0]['reasons'])

    def test_not_applicable_needs_evidence_and_cannot_hide_empty_work(self):
        source = request()
        source['packages'][0]['factors']['security']['level'] = 'not_applicable'
        self.assertEqual(effort.assess_effort(source)['overall']['category'], 'easy')
        source['packages'][0]['factors']['security']['evidence_ids'] = []
        self.assertEqual(effort.assess_effort(source)['overall']['status'], 'blocked')
        source = request()
        for factor in source['packages'][0]['factors'].values():
            factor['level'] = 'not_applicable'
        self.assertEqual(effort.assess_effort(source)['overall']['status'], 'blocked')

    def test_unknown_ids_cycles_duplicates_and_levels_rejected(self):
        sources = []
        bad = request(); bad['packages'][0]['depends_on'] = ['missing']; sources.append(bad)
        bad = request(); bad['packages'][0]['depends_on'] = ['orders']; sources.append(bad)
        bad = request(); bad['packages'] *= 2; sources.append(bad)
        bad = request(); bad['evidence'] *= 2; sources.append(bad)
        bad = request(); bad['packages'][0]['factors']['platform']['evidence_ids'] = ['missing']; sources.append(bad)
        bad = request(); bad['packages'][0]['factors']['platform']['level'] = 'extreme'; sources.append(bad)
        for source in sources:
            with self.subTest(source=source), self.assertRaises(effort.EffortError):
                effort.assess_effort(source)

    def test_strict_contract_rejects_duration_and_instrumentation_fields(self):
        for field in ('hours', 'cost', 'tokens', 'estimated_days', 'productivity_gain'):
            for location in ('root', 'package', 'factor'):
                source = request()
                target = source if location == 'root' else source['packages'][0] if location == 'package' else source['packages'][0]['factors']['platform']
                target[field] = 100
                with self.subTest(field=field, location=location), self.assertRaisesRegex(effort.EffortError, 'unsupported_fields'):
                    effort.assess_effort(source)

    def test_scope_hash_and_stage_denominator_enforced(self):
        source = request()
        source['bindings']['scope_sha256'] = 'd' * 64
        with self.assertRaisesRegex(effort.EffortError, 'scope_binding'):
            effort.assess_effort(source)
        source = request()
        source['scope']['stages'].append('semantic')
        source['scope']['excluded_stages'].remove('semantic')
        source['bindings']['scope_sha256'] = effort.digest(source['scope'])
        with self.assertRaisesRegex(effort.EffortError, 'scope_package_coverage'):
            effort.assess_effort(source)

    def test_changed_grain_stales_dependency_closure_preserving_unrelated_rating(self):
        source = request([package('shared'), package('orders', dependencies=['shared']), package('independent')])
        previous = effort.assess_effort(source)
        source['bindings'].update(design_revision='design-2', design_material_sha256='e' * 64)
        source['packages'][0]['material_inputs']['grain.shared'] = 'e' * 64
        source['review']['reference'] = 'review/design-2'
        refresh = effort.refresh_effort(previous, source)
        rows = {row['id']: row for row in refresh['packages']}
        self.assertEqual(refresh['status'], 'stale')
        self.assertEqual(rows['shared']['status'], 'stale')
        self.assertEqual(rows['orders']['status'], 'stale')
        self.assertEqual(rows['orders']['readiness'], 'needs_discovery')
        self.assertIsNone(rows['orders']['category'])
        self.assertEqual(rows['independent']['status'], 'current')
        self.assertEqual(rows['independent']['category'], 'easy')
        self.assertEqual(rows['independent']['readiness'], 'ready')
        self.assertEqual(rows['independent']['origin_bindings']['design_revision'], 'design-1')

    def test_cosmetic_revision_preserves_ratings_and_origin(self):
        source = request()
        previous = effort.assess_effort(source)
        source['bindings']['design_revision'] = 'design-2-label-change'
        source['review']['reference'] = 'review/design-2-label-change'
        refresh = effort.refresh_effort(previous, source)
        self.assertEqual(refresh['status'], 'current')
        self.assertFalse(refresh['requires_reassessment'])
        self.assertEqual(refresh['overall'], previous['overall'])
        self.assertEqual(refresh['bindings']['design_revision'], 'design-2-label-change')
        self.assertEqual(refresh['packages'][0]['origin_bindings']['design_revision'], 'design-1')

    def test_unmapped_material_drift_or_route_drift_is_conservatively_stale(self):
        for field in ('design_material_sha256', 'route_sha256'):
            source = request()
            previous = effort.assess_effort(source)
            source['bindings'][field] = 'e' * 64
            with self.subTest(field=field):
                refresh = effort.refresh_effort(previous, source)
                self.assertEqual(refresh['packages'][0]['status'], 'stale')
                self.assertIsNone(refresh['overall']['category'])

    def test_cutover_scope_expansion_requires_reassessment(self):
        source = request()
        previous = effort.assess_effort(source)
        source['scope']['stages'] += ['deployment', 'cutover']
        source['scope']['excluded_stages'] = [s for s in source['scope']['excluded_stages'] if s not in ('deployment', 'cutover')]
        source['bindings']['scope_sha256'] = effort.digest(source['scope'])
        source['packages'] += [package('release', stage='deployment'), package('cutover', stage='cutover', dependencies=['release'])]
        refresh = effort.refresh_effort(previous, source)
        self.assertTrue(refresh['requires_reassessment'])
        self.assertEqual({row['status'] for row in refresh['packages']}, {'stale'})
        self.assertIn('Binding changed: scope_sha256', refresh['packages'][0]['reasons'])

    def test_evidence_drift_only_stales_packages_using_it(self):
        source = request([package('orders'), package('customers')])
        source['evidence'].append({'id': 'customer-pattern', 'sha256': 'd' * 64})
        for factor in source['packages'][1]['factors'].values():
            factor['evidence_ids'] = ['customer-pattern']
        previous = effort.assess_effort(source)
        source['evidence'][0]['sha256'] = 'e' * 64
        rows = {row['id']: row for row in effort.refresh_effort(previous, source)['packages']}
        self.assertEqual(rows['orders']['status'], 'stale')
        self.assertEqual(rows['customers']['status'], 'current')

    def test_refresh_rejects_tampered_assessment_and_does_not_promote_pending_review(self):
        source = request()
        previous = effort.assess_effort(source)
        previous['overall']['category'] = 'very_difficult'
        with self.assertRaisesRegex(effort.EffortError, 'previous_assessment_changed'):
            effort.refresh_effort(previous, source)
        previous = effort.assess_effort(source)
        source['review'] = {'status': 'pending', 'reference': None}
        refreshed = effort.refresh_effort(previous, source)
        self.assertEqual(refreshed['status'], 'stale')
        self.assertEqual(refreshed['overall']['readiness'], 'review_pending')

    def test_refresh_preserves_known_blocked_work_readiness(self):
        source = request()
        source['packages'][0]['blockers'] = ['Waiting for approved development access.']
        previous = effort.assess_effort(source)
        refreshed = effort.refresh_effort(previous, source)
        self.assertEqual(refreshed['status'], 'current')
        self.assertEqual(refreshed['overall']['category'], 'easy')
        self.assertEqual(refreshed['overall']['readiness'], 'blocked')
        self.assertEqual(refreshed['packages'][0]['readiness'], 'blocked')


if __name__ == '__main__':
    unittest.main()
