"""Public-safe runtime identity is local evidence, not an upstream update check."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import accelerator_runtime as runtime
from ae_common import hash_json
from run_control import content_manifest


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.skill = self.root / 'repo' / 'skills' / 'data-model-accelerator'
        self.skill.mkdir(parents=True)
        (self.skill / 'SKILL.md').write_text('Synthetic installed skill\n')
        for folder in ('scripts', 'references', 'agents', 'assets'):
            (self.skill / folder).mkdir()
            (self.skill / folder / 'example.txt').write_text('Synthetic content\n')
        self.repo = self.root / 'repo'

    def git(self, *args):
        env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_AUTHOR_DATE='2026-01-01T00:00:00Z', GIT_COMMITTER_DATE='2026-01-01T00:00:00Z')
        return subprocess.run(['git', '-c', 'user.name=Synthetic Test', '-c',
                               'user.email=synthetic@example.invalid', '-c', 'commit.gpgsign=false',
                               '-c', 'core.hooksPath=' + os.devnull, '-C', str(self.repo), *args],
                              env=env, check=True, capture_output=True).stdout.decode().strip()

    def init_repo(self):
        if not shutil.which('git'):
            self.skipTest('Git is unavailable')
        self.git('init', '-q')
        self.git('add', 'skills')
        self.git('commit', '-qm', 'Synthetic baseline')
        return self.git('rev-parse', 'HEAD')

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob('*') if path.is_file()}

    def test_clean_checkout_full_head_no_expected_is_unknown_and_read_only(self):
        head = self.init_repo()
        before = self.snapshot()
        result = runtime.inspect_runtime(self.skill)
        self.assertEqual(result['installed_revision'], head)
        self.assertIs(result['skill_dirty'], False)
        self.assertEqual(result['freshness']['status'], 'unknown')
        self.assertEqual(result['runtime_sha256'], hash_json(content_manifest(self.skill)))
        self.assertEqual(before, self.snapshot())

    def test_revision_mismatch_has_update_reload_advisory_without_mutation(self):
        self.init_repo()
        before = self.snapshot()
        result = runtime.inspect_runtime(self.skill, expected_revision='f' * 40)
        self.assertEqual(result['freshness']['status'], 'mismatch')
        self.assertEqual(result['freshness']['revision_comparison'], 'mismatch')
        self.assertIn('restart or reload', ' '.join(result['advisories']))
        self.assertIn('authoring remains available', result['qualification'])
        self.assertEqual(before, self.snapshot())

    def test_dirty_skill_revision_match_does_not_claim_content_match(self):
        head = self.init_repo()
        prior = runtime.inspect_runtime(self.skill)['runtime_sha256']
        (self.skill / 'scripts' / 'example.txt').write_text('Changed implementation\n')
        result = runtime.inspect_runtime(self.skill, expected_revision=head)
        self.assertIs(result['skill_dirty'], True)
        self.assertEqual(result['freshness']['revision_comparison'], 'match')
        self.assertEqual(result['freshness']['status'], 'unknown')
        self.assertNotEqual(result['runtime_sha256'], prior)
        exact = runtime.inspect_runtime(self.skill, expected_fingerprint=result['runtime_sha256'])
        self.assertEqual(exact['freshness']['status'], 'match')
        self.assertIs(exact['skill_dirty'], True)

    def test_unrelated_repo_edits_and_generated_bytecode_do_not_dirty_skill(self):
        head = self.init_repo()
        baseline = runtime.inspect_runtime(self.skill)['runtime_sha256']
        (self.repo / 'unrelated.txt').write_text('Unrelated repository work\n')
        cache = self.skill / 'scripts' / '__pycache__'
        cache.mkdir()
        (cache / 'ignored.pyc').write_bytes(b'not source')
        (self.skill / 'scripts' / '.DS_Store').write_bytes(b'not source')
        result = runtime.inspect_runtime(self.skill, expected_revision=head)
        self.assertIs(result['skill_dirty'], False)
        self.assertEqual(result['runtime_sha256'], baseline)
        self.assertEqual(result['freshness']['status'], 'match')

    def test_untracked_source_and_deleted_tracked_source_are_dirty(self):
        self.init_repo()
        (self.skill / 'scripts' / 'new.py').write_text('raise RuntimeError("never execute")\n')
        self.assertIs(runtime.inspect_runtime(self.skill)['skill_dirty'], True)
        (self.skill / 'scripts' / 'new.py').unlink()
        (self.skill / 'assets' / 'example.txt').unlink()
        self.assertIs(runtime.inspect_runtime(self.skill)['skill_dirty'], True)

    def test_copied_install_retains_fingerprint_without_claiming_repository(self):
        self.init_repo()
        original = runtime.inspect_runtime(self.skill)
        copied = self.root / 'copied'
        shutil.copytree(self.skill, copied)
        result = runtime.inspect_runtime(copied, expected_fingerprint=original['runtime_sha256'])
        self.assertEqual(result['runtime_sha256'], original['runtime_sha256'])
        self.assertIsNone(result['installed_revision'])
        self.assertIsNone(result['skill_dirty'])
        self.assertEqual(result['freshness']['status'], 'match')
        unknown = runtime.inspect_runtime(copied, expected_revision=original['installed_revision'])
        self.assertEqual(unknown['freshness']['status'], 'unknown')
        self.assertEqual(unknown['freshness']['revision_comparison'], 'unavailable')

    def test_untracked_copy_inside_another_git_repo_does_not_inherit_its_head(self):
        self.init_repo()
        copied = self.repo / 'other-install'
        shutil.copytree(self.skill, copied)
        result = runtime.inspect_runtime(copied)
        self.assertIsNone(result['installed_revision'])
        self.assertEqual(result['repository_status'], 'unavailable')
        self.assertEqual(result['content_status'], 'available')

    def test_detached_head_is_identified_and_combined_comparisons_are_conservative(self):
        head = self.init_repo()
        self.git('checkout', '--detach', '-q', head)
        value = runtime.inspect_runtime(self.skill, expected_revision=head.upper(), expected_fingerprint='0' * 64)
        self.assertEqual(value['installed_revision'], head)
        self.assertEqual(value['freshness']['revision_comparison'], 'match')
        self.assertEqual(value['freshness']['fingerprint_comparison'], 'mismatch')
        self.assertEqual(value['freshness']['status'], 'mismatch')

    def test_unavailable_git_status_retains_head_without_revision_only_freshness(self):
        head = self.init_repo()
        actual_run = subprocess.run
        def read_git(*args, **kwargs):
            if 'status' in args[0]:
                raise subprocess.TimeoutExpired(args[0], 5)
            return actual_run(*args, **kwargs)
        with patch.object(runtime.subprocess, 'run', side_effect=read_git):
            result = runtime.inspect_runtime(self.skill, expected_revision=head)
        self.assertEqual(result['installed_revision'], head)
        self.assertIsNone(result['skill_dirty'])
        self.assertEqual(result['freshness']['status'], 'unknown')

    def test_public_result_never_exposes_installation_paths_or_remote_urls(self):
        self.init_repo()
        self.git('remote', 'add', 'origin', 'https://private.invalid/confidential/repository.git')
        result = json.dumps(runtime.inspect_runtime(self.skill))
        self.assertNotIn(str(self.root), result)
        self.assertNotIn('private.invalid', result)
        self.assertNotIn('confidential', result)
        self.assertNotIn('repository.git', result)

    def test_git_fsmonitor_hooks_and_injected_git_environment_are_not_executed(self):
        self.init_repo()
        marker = self.root / 'executed-marker'
        program = self.root / 'monitor.sh'
        program.write_text('#!/bin/sh\ntouch ' + str(marker) + '\n')
        program.chmod(0o755)
        self.git('config', 'core.fsmonitor', str(program))
        with patch.dict(os.environ, {'GIT_DIR': str(self.root / 'wrong'),
                                     'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'core.fsmonitor',
                                     'GIT_CONFIG_VALUE_0': str(program)}):
            self.assertIsNotNone(runtime.inspect_runtime(self.skill)['installed_revision'])
        self.assertFalse(marker.exists())

    def test_git_clean_and_process_filters_are_disabled_and_transports_forbidden(self):
        self.init_repo()
        marker = self.root / 'executed-marker'
        program = self.root / 'filter.sh'
        program.write_text('#!/bin/sh\ntouch ' + str(marker) + '\ncat\n')
        program.chmod(0o755)
        (self.repo / '.gitattributes').write_text('*.txt filter=hostile\n')
        self.git('config', 'filter.hostile.clean', str(program))
        self.git('config', 'filter.hostile.process', str(program))
        self.git('config', 'filter.hostile.required', 'true')
        (self.skill / 'scripts' / 'example.txt').write_text('Changed content\n')
        actual_run = subprocess.run
        with patch.object(runtime.subprocess, 'run', wraps=actual_run) as run:
            result = runtime.inspect_runtime(self.skill)
        self.assertIsNotNone(result['installed_revision'])
        self.assertIs(result['skill_dirty'], True)
        self.assertFalse(marker.exists())
        for call in run.call_args_list:
            self.assertEqual(call.kwargs['env']['GIT_ALLOW_PROTOCOL'], '')
            self.assertEqual(call.kwargs['env']['GIT_NO_LAZY_FETCH'], '1')

    def test_symlinks_missing_install_and_errors_return_safe_unavailable_evidence(self):
        outside = self.root / 'private-secret.txt'
        outside.write_text('PRIVATE_SENTINEL')
        (self.skill / 'scripts' / 'link.py').symlink_to(outside)
        with patch.object(runtime, '_git_identity') as git_identity:
            result = runtime.inspect_runtime(self.skill, expected_fingerprint='0' * 64)
        git_identity.assert_not_called()
        self.assertEqual(result['content_status'], 'unavailable')
        self.assertEqual(result['freshness']['status'], 'unknown')
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))
        self.assertNotIn(str(self.root), json.dumps(result))
        self.assertEqual(runtime.inspect_runtime(self.root / 'absent')['content_status'], 'unavailable')

    def test_source_python_is_hashed_not_imported_or_run(self):
        marker = self.root / 'executed-marker'
        (self.skill / 'scripts' / 'danger.py').write_text('from pathlib import Path\nPath(' + repr(str(marker)) + ').touch()\n')
        (self.skill / 'scripts' / 'sitecustomize.py').write_text('raise RuntimeError("not imported")\n')
        self.assertEqual(runtime.inspect_runtime(self.skill)['content_status'], 'available')
        self.assertFalse(marker.exists())

    def test_cli_json_mismatch_is_advisory_and_invalid_reference_is_bounded(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = runtime.main(['--skill-root', str(self.skill), '--expected-fingerprint', '0' * 64])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())['freshness']['status'], 'mismatch')
        output = io.StringIO()
        with redirect_stdout(output):
            code = runtime.main(['--expected-revision', '/private/sensitive-path'])
        self.assertEqual(code, 2)
        self.assertNotIn('sensitive-path', output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['kind'], 'accelerator_runtime_diagnostic_error')

    def test_invalid_reference_rejected_without_git_or_content_reads(self):
        for kwargs in ({'expected_revision': 'main'}, {'expected_revision': 'abc1234'},
                       {'expected_fingerprint': 'not-a-sha'}, {'expected_revision': 123}):
            with patch.object(runtime, '_git_identity') as git_identity:
                with self.assertRaises(ValueError):
                    runtime.inspect_runtime(self.skill, **kwargs)
                git_identity.assert_not_called()


if __name__ == '__main__':
    unittest.main()
