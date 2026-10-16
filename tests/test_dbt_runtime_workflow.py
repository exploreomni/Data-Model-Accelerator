"""Runtime choices change implementation evidence, not the reviewed design."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import dbt_compatibility as compatibility
import guided_workflow as guided
import delivery_portal as portal
import platform_readiness
from dbt_feature_delivery import prepare_features
from test_deployment_adapters import target, artifact
import deployment_adapters
import test_engagement_stages as stage_harness

V2 = {'distribution': 'dbt', 'version': '2.0.8', 'analysis_mode': 'baseline', 'features': []}


class RuntimeWorkflowTests(unittest.TestCase):
    def test_manifest_schema_is_not_engine_identity_and_assessment_is_read_only(self):
        files = {'target/manifest.json': json.dumps({'metadata': {'dbt_version': '2.0.8',
                 'dbt_schema_version': 'https://schemas.getdbt.com/dbt/manifest/v12.json'}}),
                 'dbt_project.yml': "name: source\nrequire-dbt-version: '<2.0.0'\n",
                 'models/a.sql': '{{ run_query("do not execute") }}'}
        with patch('subprocess.run', side_effect=AssertionError('discovery executed')):
            result = compatibility.assess_texts(files, V2, 'snowflake')
        self.assertEqual(result['source_declarations'][0]['distribution'], 'unknown')
        self.assertIsNone(result['observed_runtime'])
        self.assertFalse(result['execution_performed'])
        codes = {r['code'] for r in result['findings']}
        self.assertIn('dbt.version_constraint', codes)
        self.assertIn('dbt.macro_review', codes)
        self.assertNotIn('do not execute', json.dumps(result))

    def test_version_range_and_malformed_config_do_not_become_upgrade_success(self):
        accepted = compatibility.assess_texts({'dbt_project.yml': "require-dbt-version: ['>=2.0.0', '<3.0.0']\n"}, V2)
        # Optional YAML dependency: absence stays an explicit review finding.
        try:
            import yaml
        except ImportError:
            self.assertTrue(accepted['findings'])
        else:
            self.assertFalse(accepted['findings'])
        duplicate = compatibility.assess_texts({'dbt_project.yml': "require-dbt-version: '>=2.0.0'\nrequire-dbt-version: '<2.0.0'\n"}, V2)
        self.assertTrue(duplicate['findings'])
        with self.assertRaises(ValueError):
            compatibility.assess_texts({'../escape.sql': 'select 1'}, V2)

    def test_selection_roundtrip_preserves_legacy_target_and_changes_runtime_binding(self):
        a = {'framework': 'dbt', 'warehouse': 'snowflake'}
        target_old, runtime_old, discovery_old = guided._selection(a)
        b = guided._answers({**a, 'dbt_runtime': V2})
        target_new, runtime_new, discovery_new = guided._selection(b)
        self.assertEqual(target_old, target_new)
        self.assertEqual(discovery_old, discovery_new)
        self.assertNotEqual(runtime_old['sha256'], runtime_new['sha256'])
        self.assertNotIn('dbt_runtime', guided._missing(a))

    def test_assessment_integrates_selected_contract_without_executing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve(); (root / 'dbt_project.yml').write_text('name: example\n')
            with patch('subprocess.run', side_effect=AssertionError('executed')):
                value = platform_readiness.assess_repository(root, 'dbt', 'bigquery', dbt_runtime=V2)
            self.assertEqual(value['dbt_compatibility']['selection'], V2)
            self.assertFalse(value['execution_performed'])
            self.assertFalse(value['platform_pairing']['native_qualified'])

    def test_public_runtime_card_does_not_turn_selection_into_test_success(self):
        state = {'answers': {'framework': 'dbt', 'warehouse': 'snowflake', 'dbt_runtime': V2},
                 'runtime_probe': {'password': 'DO_NOT_EXPORT'}}
        view = portal._dbt_runtime_summary(state)
        self.assertEqual(view['observed_runtime'], 'not_probed')
        self.assertEqual(view['native_validation'], 'not_run')
        self.assertNotIn('DO_NOT_EXPORT', json.dumps(view))
        readme = portal.package_readme({'engagement': {'target': state['answers'], 'dbt_runtime': view}}).decode()
        self.assertIn('dbt==2.0.8', readme)
        self.assertIn('not an installed-runtime', readme)

    def test_runtime_package_retains_navigation_and_embedded_data(self):
        from test_delivery_portal import fixture
        import portal_checks
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            state, review = fixture(root)
            state['answers']['dbt_runtime'] = V2
            review['context_sha256'] = portal.context_fingerprint(state)
            package = root / 'runtime.zip'
            portal.package_delivery(state, review, root, package, audience='engineer')
            with zipfile.ZipFile(package) as archive:
                html = archive.read('START_HERE.html')
            _, data = portal_checks.parse_page(html)
            self.assertEqual(data['engagement']['dbt_runtime']['selection'], V2)
            self.assertEqual(html.count(b'id="dbt-runtime-validation"'), 1)
            self.assertEqual(portal.check_page(package)['status'], 'page_contract_verified')

    def test_optional_candidates_do_not_edit_or_enable_features(self):
        none = prepare_features(V2, 'snowflake')
        self.assertEqual(none['files'], [])
        selected = prepare_features({**V2, 'features': ['checks', 'information_schema']}, 'snowflake')
        self.assertEqual(len(selected['files']), 4)
        self.assertTrue(all(not f['enabled'] for f in selected['features']))
        self.assertFalse(selected['execution_performed'])
        legacy = prepare_features({'distribution': 'dbt_core', 'version': '1.12.4', 'features': ['checks']})
        self.assertEqual(legacy['files'], [])
        self.assertEqual(legacy['features'][0]['status'], 'unsupported')

    def test_deployment_binds_engine_even_when_versions_and_manifest_schemas_match(self):
        value = target('dbt_platform'); value.update(runtime_version='2.0.8', dbt_runtime=V2)
        a = deployment_adapters.build_plan(value, [artifact()], release_id='synthetic-runtime', commit_sha='a' * 40)
        value['dbt_runtime'] = {**V2, 'distribution': 'dbt_oss', 'analysis_mode': 'none'}
        b = deployment_adapters.build_plan(value, [artifact()], release_id='synthetic-runtime', commit_sha='a' * 40)
        self.assertNotEqual(a, b)
        self.assertEqual(a['operations'][0]['body'], b['operations'][0]['body'])
        value['runtime_version'] = '1.12.4'
        with self.assertRaisesRegex(ValueError, 'version differs'):
            deployment_adapters.validate_target(value)

    def test_live_deploy_rejects_missing_or_downgraded_analysis_observation(self):
        import deployment_workflow as deploy
        selected = {**V2, 'analysis_mode': 'strict'}
        destination = target('dbt_platform')
        destination.update(runtime_version='2.0.8', dbt_runtime=selected)
        plan = {'action': 'deploy_dev', 'target': destination,
                'quality': {'status': 'verified_static', 'report_sha256': 'a' * 64}}
        preflight = {'status': 'passed', 'target_sha256': deploy.digest(destination),
                     'runtime_version': '2.0.8', 'principal_namespace_verified': True,
                     'artifact_commit_verified': True, 'lint_report_sha256': 'a' * 64,
                     'permissions_verified': True, 'evidence_sha256': 'b' * 64,
                     'evidence_reference': 'synthetic://independent-preflight',
                     'dbt_runtime_verified': True, 'observed_dbt_runtime': V2}
        attestation = {'issuer': 'synthetic', 'claims': {'preflight': preflight}}
        with patch.object(deploy, 'verify_attestation', return_value=attestation), \
                patch.object(deploy, 'model_bindings', return_value={}), \
                patch.object(deploy, 'approval_bindings', return_value={}), \
                patch('delivery_release.require_release'):
            with self.assertRaisesRegex(ValueError, 'independently verified'):
                deploy._approval(plan, {'mode': 'live'}, {}, {})
            preflight['observed_dbt_runtime'] = selected
            deploy._approval(plan, {'mode': 'live'}, {}, {})
            preflight['dbt_runtime_verified'] = False
            with self.assertRaisesRegex(ValueError, 'independently verified'):
                deploy._approval(plan, {'mode': 'live'}, {}, {})

    def _deployment_plan(self, root, selected_runtime, destination, metadata_phase=None):
        """Exercise the planner; stand-ins supply trusted policy/handoff only."""
        import deployment_workflow as deploy
        content = b'select 1;'
        sha = hashlib.sha256(content).hexdigest()
        answers = {'framework': 'dbt', 'warehouse': 'snowflake', 'semantic_target': 'none'}
        if selected_runtime is not None:
            answers['dbt_runtime'] = selected_runtime
        state = {'answers': answers, 'inputs': {'source': {'path': str(root)}}}
        handoff = {'artifact_root': str(root), 'artifacts': [{'path': 'model.sql', 'sha256': sha, 'bytes': len(content)}]}
        bindings = {'source_bindings': {'runtime': guided._selection(answers)[1]['sha256']},
                    'handoff_manifest_sha256': 'a' * 64}
        policy = {'mode': 'live', 'allowed_actions': ['deploy_development'], 'destinations': {'dev': destination}}
        request = {'schema_version': 1, 'action': 'deploy_development', 'destination_id': 'dev',
                   'commit_sha': 'a' * 40, 'artifacts': [{'path': 'model.sql', 'role': 'model_sql'}],
                   'impact': ['Synthetic model'], 'recovery': ['Synthetic recovery']}
        if metadata_phase is not None:
            request['metadata_phase'] = metadata_phase
        with patch.object(deploy, '_handoff', return_value=(state, handoff, bindings)), \
                patch.object(deploy, 'load_policy', return_value=(policy, deploy.digest(policy))), \
                patch.object(deploy, '_stable_bytes', return_value=content), \
                patch.object(deploy, '_write'), \
                patch('metadata_release.bind_phase', return_value={'synthetic_bound_phase': True}):
            plan = deploy.create_plan(root, request, 'synthetic-policy', root.parent / 'not-written-plan.json')
        return plan, state, handoff, bindings, policy

    def test_deployment_cannot_drop_or_replace_reviewed_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            legacy = target('dbt_platform')
            legacy['runtime_version'] = '1.12.4'
            different_engine = target('dbt_platform')
            different_engine.update(runtime_version='2.0.8', dbt_runtime={**V2, 'distribution': 'dbt_oss', 'analysis_mode': 'none'})
            different_mode = target('dbt_platform')
            different_mode.update(runtime_version='2.0.8', dbt_runtime={**V2, 'analysis_mode': 'strict'})
            different_features = target('dbt_platform')
            different_features.update(runtime_version='2.0.8', dbt_runtime={**V2, 'features': ['checks']})
            for destination in (legacy, different_engine, different_mode, different_features):
                with self.subTest(destination=destination), self.assertRaisesRegex(ValueError, 'reviewed dbt runtime'):
                    self._deployment_plan(root, V2, destination)
            matching = target('dbt_platform')
            matching.update(runtime_version='2.0.8', dbt_runtime=V2)
            plan, *_ = self._deployment_plan(root, {'distribution': 'dbt', 'version': '2.0.8'}, matching)
            self.assertEqual(plan['target']['dbt_runtime'], V2)

    def test_legacy_and_native_metadata_routes_keep_their_existing_contract(self):
        import deployment_workflow as deploy
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            legacy = target('dbt_platform')
            plan, *_ = self._deployment_plan(root, None, legacy)
            self.assertNotIn('dbt_runtime', plan['target'])
            native = target('snowflake_sql')
            plan, *_ = self._deployment_plan(root, V2, native, metadata_phase={'synthetic': 'separate native phase'})
            self.assertEqual(plan['target']['framework'], 'native_sql')
            self.assertIn('metadata_phase', plan)
            # A dbt model route cannot evade binding by attaching metadata data.
            with self.assertRaisesRegex(ValueError, 'reviewed dbt runtime'):
                self._deployment_plan(root, V2, legacy, metadata_phase={'synthetic': 'not a native SQL route'})

    def test_dbt_publication_preserves_selection_without_probing(self):
        import deployment_workflow as deploy
        state = {'answers': {'framework': 'dbt', 'dbt_runtime': V2}}
        legacy = target('dbt_platform')
        with self.assertRaisesRegex(ValueError, 'reviewed dbt runtime'):
            deploy._reviewed_dbt_runtime(state, legacy, 'publish_pr')
        matching = target('dbt_platform')
        matching.update(runtime_version='2.0.8', dbt_runtime=V2)
        with patch('subprocess.run', side_effect=AssertionError('publication runtime probe')):
            deploy._reviewed_dbt_runtime(state, matching, 'publish_pr')

    def test_current_plan_rechecks_runtime_binding_before_dispatch(self):
        import deployment_workflow as deploy
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            matching = target('dbt_platform')
            matching.update(runtime_version='2.0.8', dbt_runtime=V2)
            plan, state, handoff, bindings, policy = self._deployment_plan(root, V2, matching)
            # Reproduce a plan made by the old planner: context is current but
            # the provisioned target omits the selected runtime.
            legacy = target('dbt_platform')
            plan['target'] = deployment_adapters.validate_target(legacy)
            policy['destinations']['dev'] = legacy
            plan['policy_sha256'] = deploy.digest(policy)
            with patch.object(deploy, '_handoff', return_value=(state, handoff, bindings)), \
                    patch.object(deploy, 'load_policy', return_value=(policy, deploy.digest(policy))), \
                    patch.object(deploy, '_release_bytes') as read_artifact:
                with self.assertRaisesRegex(ValueError, 'reviewed dbt runtime'):
                    deploy._current(plan, 'synthetic-policy')
                read_artifact.assert_not_called()

    def test_readiness_history_invalidates_on_runtime_selection_change_and_clear(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            repo, run = root / 'source', root / 'engagement'
            repo.mkdir()
            (repo / 'dbt_project.yml').write_text('name: synthetic\n')
            state = guided.start_engagement(repo, run, {'framework': 'dbt', 'warehouse': 'snowflake'})
            legacy_id = state['evidence'][-1]['id']
            self.assertNotIn('runtime', state['evidence'][-1]['dependencies'])
            state = guided.assess_engagement(run)
            self.assertEqual(next(e for e in state['evidence'] if e['id'] == legacy_id)['status'], 'current')
            previous = legacy_id
            for selected in (V2, {**V2, 'analysis_mode': 'strict'}, None):
                state = guided.update_answers(run, {'dbt_runtime': selected})
                old = next(e for e in state['evidence'] if e['id'] == previous)
                self.assertEqual(old['status'], 'stale')
                self.assertIn('runtime', old['invalidated_by'])
                latest = state['evidence'][-1]
                self.assertEqual(latest['status'], 'current')
                self.assertEqual(latest['dependencies']['runtime'], state['inputs']['runtime']['sha256'])
                previous = latest['id']


class RuntimeStageTests(unittest.TestCase):
    def test_runtime_change_reuses_review_but_regenerates_code(self):
        case = stage_harness.StageTests('test_design_only_and_forged_approval_never_unlock_code')
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.approve()
        case.plan(case.tasks())
        case.complete('build-customers')
        before = case.plan()
        self.assertEqual(next(t for t in before['tasks'] if t['id'] == 'build-customers')['action'], 'reuse')
        import engagement_stages as stages
        approved = stages.approved_entities(case.state)
        case.state = guided.update_answers(case.run, {'dbt_runtime': V2})
        self.assertEqual(stages.approved_entities(case.state), approved)
        after = case.plan()
        self.assertEqual(next(t for t in after['tasks'] if t['id'] == 'build-customers')['action'], 'regenerate')


if __name__ == '__main__':
    unittest.main()
