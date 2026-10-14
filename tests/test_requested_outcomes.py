"""Requested scope, rather than the registered task subset, determines the next step."""
import unittest

import test_engagement_stages as fixtures

stages = fixtures.stages


class RequestedOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.StageTests('test_semantic_entrypoint_requires_actual_physical_outputs_and_current_guidance')
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.entities = ['customers', 'orders', 'products']
        self.select_outcomes(code=True)

    def select_outcomes(self, *, code):
        self.h.state['answers'].update({
            'deliverables': ['documentation', 'diagrams', 'dictionary', 'implementation', 'validation']
                            if code else ['documentation', 'diagrams', 'dictionary'],
            'semantic_target': 'omni' if code else 'none',
            'migration_scope': 'model_semantic' if code else 'model_only'})
        fixtures.guided._save(self.h.run, self.h.state, 'synthetic_requested_outcomes')
        self.h.state = fixtures.guided.resume_engagement(self.h.run)

    def approve(self):
        self.h.action('approve-design', entities=self.entities, document={
            'schema_version': 1, 'kind': 'human_design_review', 'decision': 'approve',
            'reviewer': 'Synthetic domain reviewer', 'review_reference': 'synthetic://human/requested-scope',
            'bindings': stages.review_bindings(self.h.state, self.entities)})

    def design_task(self):
        return {'id': 'design-review', 'stage': 'design', 'entity_ids': self.entities,
                'depends_on': [], 'components': [], 'outputs': ['design.md']}

    def warehouse_tasks(self):
        return [task for task in self.h.tasks()['tasks'] if task['stage'] == 'implementation']

    def semantic_task(self, *, full_scope):
        return {'id': 'semantic', 'stage': 'semantic',
                'entity_ids': self.entities if full_scope else ['orders'],
                'depends_on': ['build-customers', 'build-orders', 'build-products'] if full_scope else ['build-orders'],
                'components': [], 'outputs': ['semantic-model.yaml']}

    def complete_plan(self, tasks):
        self.h.plan({'schema_version': 1, 'tasks': tasks})
        for task in tasks:
            self.h.complete(task['id'])
        return stages.public_view(self.h.state)

    def assert_pending(self, view, stage):
        self.assertEqual(view['current_stage'], stage)
        row = next(item for item in view['stages'] if item['id'] == stage)
        self.assertNotIn(row['status'], {'outputs_recorded', 'complete', 'completed'})
        self.assertTrue(view['next_action'].strip())
        guidance = (view['next_action'] + ' ' + row['next_action']).lower()
        expected = 'implementation|warehouse|code' if stage == 'implementation' else 'semantic|omni'
        self.assertRegex(guidance, expected)
        self.assertNotIn('all requested outputs are recorded', guidance)
        return row

    def test_finished_design_task_does_not_skip_requested_warehouse_code(self):
        self.approve()
        view = self.complete_plan([self.design_task()])
        self.assert_pending(view, 'implementation')
        self.assertFalse(any(path.suffix == '.sql' for path in self.h.artifacts.iterdir()))
        self.assertEqual({task['stage'] for task in view['task_plan']['tasks']}, {'design'})

    def test_finished_warehouse_tasks_do_not_skip_requested_omni_model(self):
        self.approve()
        view = self.complete_plan(self.warehouse_tasks())
        self.assert_pending(view, 'semantic')
        self.assertEqual({task['stage'] for task in view['task_plan']['tasks']}, {'implementation'})

    def test_documentation_files_cannot_fulfill_requested_implementation_or_semantic_code(self):
        self.approve()
        for stage in ('implementation', 'semantic'):
            with self.subTest(stage=stage):
                tasks = self.warehouse_tasks() + [self.semantic_task(full_scope=True)]
                for task in tasks:
                    if task['stage'] == stage:
                        task['outputs'] = [task['id'] + '.md']
                with self.assertRaisesRegex(ValueError, 'code|artifact'):
                    self.h.plan({'schema_version': 1, 'tasks': tasks})

    def test_partial_semantic_scope_stays_pending_for_uncovered_entities(self):
        self.approve()
        view = self.complete_plan(self.warehouse_tasks() + [self.semantic_task(full_scope=False)])
        row = self.assert_pending(view, 'semantic')
        # The orders semantic task may include its customer dependency, but it
        # cannot fulfill the separate requested products entity by implication.
        guidance = (view['next_action'] + ' ' + row['next_action']).lower()
        self.assertIn('products', guidance)
        self.assertTrue(all(task['action'] == 'reuse' for task in view['task_plan']['tasks']),
                        'Recorded tasks can be reusable while requested scope remains incomplete')

    def test_full_code_scope_moves_to_validation_without_claiming_validation_ran(self):
        self.approve()
        view = self.complete_plan(self.warehouse_tasks() + [self.semantic_task(full_scope=True)])
        self.assertEqual(view['current_stage'], 'validation')
        row = next(item for item in view['stages'] if item['id'] == 'validation')
        self.assertNotIn(row['status'], {'outputs_recorded', 'complete', 'completed', 'pass', 'passed'})
        self.assertIn('validation', (view['next_action'] + ' ' + row['next_action']).lower())
        self.assertFalse(any(task['stage'] == 'validation' for task in view['task_plan']['tasks']))

    def test_documentation_only_selection_ends_at_review_or_packaging_without_inventing_code(self):
        self.select_outcomes(code=False)
        view = self.complete_plan([self.design_task()])
        self.assertIn(view['current_stage'], {'design', 'packaging'})
        self.assertNotRegex(view['next_action'].lower(), 'generate.*(?:sql|warehouse code|omni)|prepare independent validation')
        self.assertFalse(self.h.state['workflow']['approvals'], 'Design-only packaging does not require implementation approval')
        self.assertFalse(any(path.suffix in {'.sql', '.yaml', '.yml'} for path in self.h.artifacts.iterdir()))

    def test_documentation_only_selection_does_not_skip_unfinished_design_tasks(self):
        self.select_outcomes(code=False)
        self.h.plan({'schema_version': 1, 'tasks': [self.design_task()]})
        view = stages.public_view(self.h.state)
        self.assertEqual(view['current_stage'], 'design')
        self.assertEqual(view['delivery_status'], 'design_proposal_pending')


if __name__ == '__main__':
    unittest.main()
