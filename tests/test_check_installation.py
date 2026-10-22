"""Read-only installed content comparison includes prompts, parsers and assets."""
import shutil
import tempfile
from pathlib import Path
import unittest
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from unittest.mock import patch

import test_engagement_stages
from check_installation import compare, preflight, main, _revision


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.expected = root / 'expected'; self.expected.mkdir()
        (self.expected / 'SKILL.md').write_text('Synthetic skill')
        for folder in ('scripts', 'references', 'agents', 'assets'):
            (self.expected / folder).mkdir()
            (self.expected / folder / 'sample.txt').write_text('Synthetic pinned content')
        self.installed = root / 'installed'
        shutil.copytree(self.expected, self.installed)

    def test_equal_content_and_ignored_bytecode_are_read_only(self):
        cache = self.installed / 'scripts/__pycache__'; cache.mkdir()
        (cache / 'test.pyc').write_bytes(b'not a runtime source')
        before = {str(p): p.read_bytes() for p in self.installed.rglob('*') if p.is_file()}
        self.assertEqual(compare(self.expected, self.installed)['status'], 'match')
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.installed.rglob('*') if p.is_file()})

    def test_changed_instructions_missing_parser_and_extra_asset_are_reported(self):
        (self.installed / 'agents/sample.txt').write_text('Changed model instructions')
        (self.installed / 'scripts/sample.txt').unlink()
        (self.installed / 'assets/extra.svg').write_text('<svg/>')
        result = compare(self.expected, self.installed)
        self.assertEqual(result['status'], 'different')
        self.assertEqual(result['changed'], ['agents/sample.txt'])
        self.assertEqual(result['missing'], ['scripts/sample.txt'])
        self.assertEqual(result['extra'], ['assets/extra.svg'])

    def test_symlinks_and_missing_skill_are_not_equal_empty_installations(self):
        (self.installed / 'assets/link.txt').symlink_to(self.expected / 'SKILL.md')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            compare(self.expected, self.installed)
        with self.assertRaises(ValueError):
            compare(self.expected, self.installed / 'absent')

    def test_top_level_content_folders_cannot_redirect_identity_reads(self):
        shutil.rmtree(self.installed / 'scripts')
        (self.installed / 'scripts').symlink_to(self.expected / 'scripts', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            compare(self.expected, self.installed)

    def test_explicit_alternatives_only_conflicts_and_requested_settings(self):
        different = self.installed.parent / 'different'; shutil.copytree(self.expected, different)
        (different / 'SKILL.md').write_text('Different explicit installation')
        hidden = self.installed.parent / 'not-supplied'; shutil.copytree(self.expected, hidden)
        (hidden / 'SKILL.md').write_text('Do not discover this sibling')
        before = {str(p):p.read_bytes() for p in self.installed.parent.rglob('*') if p.is_file()}
        result = preflight(self.installed, expected_skill=self.expected,
            alternative_skills=[self.expected, different, self.installed.parent / 'absent', different, self.installed],
            host='Synthetic Cortex host', model='configured-model', effort='configured-effort')
        self.assertEqual(result['status'], 'review_required')
        self.assertEqual(result['comparison'], compare(self.expected, self.installed))
        self.assertEqual(result['possible_conflicts'], [str(different)])
        self.assertEqual(len(result['alternatives']), 3)
        self.assertNotIn(str(hidden), json.dumps(result))
        self.assertEqual(result['model_policy']['requested_model'], 'configured-model')
        self.assertEqual(result['model_policy']['requested_effort'], 'configured-effort')
        self.assertIsNone(result['model_policy']['observed_model'])
        self.assertEqual(result['host']['plugin_qualification'], 'not_tested')
        self.assertEqual(result['host']['native_integration'], 'not_tested')
        self.assertEqual(result['selected']['portable_skill'], 'available')
        self.assertEqual(result['runtime']['selected_code_execution'], 'not_run')
        self.assertEqual(before, {str(p):p.read_bytes() for p in self.installed.parent.rglob('*') if p.is_file()})

    def test_default_selection_no_home_scan_and_unsafe_alternative_not_followed(self):
        default = preflight()
        self.assertEqual(default['selected']['path'], default['runtime']['checker_skill']['path'])
        self.assertEqual(default['alternatives'], [])
        self.assertEqual(default['model_policy']['action'], 'preserve_configured_defaults')
        link = self.installed.parent / 'linked'; link.symlink_to(self.installed, target_is_directory=True)
        result = preflight(self.expected, alternative_skills=[link])
        self.assertEqual(result['alternatives'][0]['relation_to_selected'], 'unavailable')
        with self.assertRaisesRegex(ValueError, 'symlink'): preflight(link)
        with self.assertRaisesRegex(ValueError, '16'): preflight(self.expected, alternative_skills=[self.installed]*17)

    def test_old_cli_json_and_exit_codes_remain_stable(self):
        out = io.StringIO()
        with redirect_stdout(out):
            status = main(['--expected-skill', str(self.expected), '--installed-skill', str(self.installed)])
        self.assertEqual(status, 0); self.assertEqual(json.loads(out.getvalue()), compare(self.expected, self.installed))
        (self.installed / 'SKILL.md').write_text('Changed')
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--expected-skill', str(self.expected), '--installed-skill', str(self.installed)]), 1)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            main(['--expected-skill', str(self.expected)])
        self.assertEqual(error.exception.code, 2)

    def test_preflight_cli_and_revision_reader_never_claim_execution(self):
        out=io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(['--preflight','--selected-skill',str(self.expected),'--host','Codex']),0)
        result=json.loads(out.getvalue())
        self.assertEqual(result['kind'],'skill_installation_preflight')
        self.assertEqual(result['host_resolution'],'not_observed')
        replies=[type('Result',(),{'stdout':value})() for value in ('/synthetic/repo\n','a'*40+'\n','atx/example\n')]
        with patch('check_installation.subprocess.run',side_effect=replies) as run:
            revision=_revision(self.expected)
        self.assertEqual(revision['head'],'a'*40);self.assertEqual(revision['branch'],'atx/example')
        self.assertEqual([c.args[0][3] for c in run.call_args_list],['rev-parse','rev-parse','symbolic-ref'])
        self.assertTrue(all(c.kwargs['env']['GIT_OPTIONAL_LOCKS']=='0' for c in run.call_args_list))
