"""Result writers cannot follow replaced directories or erase another file."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
import extract_specialist_task as bridge
import run_source_adapter as runner
from plan_specialists import plan_repository
from source_adapters.filesystem import new_json_output


class SourceOutputBoundaryTests(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name).resolve()
        source = base / 'source'; source.mkdir()
        (source / 'orders.sql').write_text("SELECT 'synthetic-boundary-marker' AS value")
        approved = base / 'outer' / 'approved'; approved.mkdir(parents=True)
        unrelated = base / 'unrelated'; unrelated.mkdir()
        plan_root = base / 'plan'
        plan = plan_repository(source, plan_root, source_profiles=['snowflake:.'], inspect_git=False)
        return base, source, approved, unrelated, plan_root / 'dispatch-plan.json', plan['tasks'][0]['task_id']

    def invoke(self, module, fixture):
        _, source, approved, _, plan, task = fixture
        output = approved / 'result.json'
        args = ([str(source), '--source', 'snowflake', '--output', str(output)] if module is runner
                else ['--plan', str(plan), '--task', task, '--output', str(output)])
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = module.main(args)
        self.assertNotIn('synthetic-boundary-marker', stdout.getvalue() + stderr.getvalue())
        return code

    def test_both_clis_write_private_json_without_changing_source(self):
        for module in (runner, bridge):
            with self.subTest(module=module.__name__):
                fixture = self.fixture()
                _, source, approved, _, _, _ = fixture
                original = (source / 'orders.sql').read_bytes()
                self.assertIn(self.invoke(module, fixture), (0, 2) if module is runner else (0,))
                output = approved / 'result.json'
                result = json.loads(output.read_text())
                self.assertIn('synthetic-boundary-marker', output.read_text())
                self.assertEqual(result['kind'] if module is runner else result['schema_version'],
                                 'source_adapter_result' if module is runner else 1)
                self.assertEqual(output.stat().st_mode & 0o777, 0o600)
                self.assertEqual(list(source.iterdir()), [source / 'orders.sql'])
                self.assertEqual((source / 'orders.sql').read_bytes(), original)

    def test_both_clis_reject_parent_swapped_to_source_or_unrelated_directory(self):
        for module in (runner, bridge):
            for target_name in ('source', 'unrelated'):
                with self.subTest(module=module.__name__, target=target_name):
                    fixture = self.fixture()
                    base, source, approved, unrelated, _, _ = fixture
                    target = source if target_name == 'source' else unrelated
                    name = 'parse' if module is runner else 'extract'
                    original = getattr(module, name)

                    def swapped(*args, **kwargs):
                        result = original(*args, **kwargs)
                        approved.rename(base / 'held-approved')
                        approved.symlink_to(target, target_is_directory=True)
                        return result

                    with patch.object(module, name, side_effect=swapped):
                        self.assertEqual(self.invoke(module, fixture), 1)
                    self.assertFalse((target / 'result.json').exists())
                    self.assertFalse((base / 'held-approved/result.json').exists())

    def test_both_clis_reject_moved_ancestor_even_with_new_normal_directories(self):
        for module in (runner, bridge):
            with self.subTest(module=module.__name__):
                fixture = self.fixture()
                base, _, approved, _, _, _ = fixture
                name = 'parse' if module is runner else 'extract'
                original = getattr(module, name)

                def swapped(*args, **kwargs):
                    result = original(*args, **kwargs)
                    (base / 'outer').rename(base / 'held-outer')
                    approved.mkdir(parents=True)
                    return result

                with patch.object(module, name, side_effect=swapped):
                    self.assertEqual(self.invoke(module, fixture), 1)
                self.assertFalse((approved / 'result.json').exists())
                self.assertFalse((base / 'held-outer/approved/result.json').exists())

    def test_both_clis_reject_existing_file_without_parsing_or_overwriting(self):
        for module in (runner, bridge):
            with self.subTest(module=module.__name__):
                fixture = self.fixture()
                output = fixture[2] / 'result.json'
                output.write_text('keep-existing')
                name = 'parse' if module is runner else 'extract'
                with patch.object(module, name) as parser:
                    self.assertEqual(self.invoke(module, fixture), 1)
                    parser.assert_not_called()
                self.assertEqual(output.read_text(), 'keep-existing')

    def test_both_clis_reject_existing_output_symlink(self):
        for module in (runner, bridge):
            with self.subTest(module=module.__name__):
                fixture = self.fixture()
                target = fixture[3] / 'missing.json'
                output = fixture[2] / 'result.json'
                output.symlink_to(target)
                self.assertEqual(self.invoke(module, fixture), 1)
                self.assertTrue(output.is_symlink())
                self.assertFalse(target.exists())

    def test_both_clis_clean_partial_write_failure(self):
        for module in (runner, bridge):
            with self.subTest(module=module.__name__):
                fixture = self.fixture()

                def failed_dump(value, stream, **kwargs):
                    stream.write('{"partial":')
                    stream.flush()
                    raise OSError('synthetic write failure')

                with patch('source_adapters.filesystem.json.dump', side_effect=failed_dump):
                    self.assertEqual(self.invoke(module, fixture), 1)
                self.assertFalse((fixture[2] / 'result.json').exists())

    def test_both_clis_detect_parent_swap_during_write_and_clean_original_entry(self):
        for module in (runner, bridge):
            with self.subTest(module=module.__name__):
                fixture = self.fixture()
                base, source, approved, _, _, _ = fixture
                original_dump = json.dump

                def swapped_dump(value, stream, **kwargs):
                    original_dump(value, stream, **kwargs)
                    approved.rename(base / 'held-approved')
                    approved.symlink_to(source, target_is_directory=True)

                with patch('source_adapters.filesystem.json.dump', side_effect=swapped_dump):
                    self.assertEqual(self.invoke(module, fixture), 1)
                self.assertFalse((source / 'result.json').exists())
                self.assertFalse((base / 'held-approved/result.json').exists())

    def test_both_clis_preserve_replacement_file_on_write_failure(self):
        for module in (runner, bridge):
            with self.subTest(module=module.__name__):
                fixture = self.fixture()
                output = fixture[2] / 'result.json'

                def replaced_dump(value, stream, **kwargs):
                    stream.write('{"partial":')
                    stream.flush()
                    output.unlink()
                    output.write_text('replacement-must-survive')
                    raise OSError('synthetic replacement during failure')

                with patch('source_adapters.filesystem.json.dump', side_effect=replaced_dump):
                    self.assertEqual(self.invoke(module, fixture), 1)
                self.assertEqual(output.read_text(), 'replacement-must-survive')

    def test_both_clis_reject_replaced_output_before_success(self):
        for module in (runner, bridge):
            with self.subTest(module=module.__name__):
                fixture = self.fixture()
                output = fixture[2] / 'result.json'
                original_dump = json.dump

                def replaced_dump(value, stream, **kwargs):
                    original_dump(value, stream, **kwargs)
                    output.unlink()
                    output.write_text('replacement-must-survive')

                with patch('source_adapters.filesystem.json.dump', side_effect=replaced_dump):
                    self.assertEqual(self.invoke(module, fixture), 1)
                self.assertEqual(output.read_text(), 'replacement-must-survive')

    def test_created_descriptor_stays_open_during_replaced_file_cleanup(self):
        for module in (runner, bridge):
            with self.subTest(module=module.__name__):
                fixture = self.fixture()
                output = fixture[2] / 'result.json'
                actual_open, actual_stat, actual_fstat = os.open, os.stat, os.fstat
                state = {'fd': None, 'identity': None, 'failed': False, 'checked': False}

                def tracked_open(path, flags, *args, **kwargs):
                    fd = actual_open(path, flags, *args, **kwargs)
                    if path == 'result.json' and flags & os.O_CREAT:
                        info = actual_fstat(fd)
                        state.update(fd=fd, identity=(info.st_dev, info.st_ino))
                    return fd

                def tracked_stat(path, *args, **kwargs):
                    if path == 'result.json' and state['failed']:
                        info = actual_fstat(state['fd'])
                        self.assertEqual((info.st_dev, info.st_ino), state['identity'])
                        self.assertEqual(info.st_nlink, 0)
                        state['checked'] = True
                    return actual_stat(path, *args, **kwargs)

                def replaced_dump(value, stream, **kwargs):
                    stream.write('{"partial":')
                    stream.flush()
                    output.unlink()
                    output.write_text('replacement-must-survive')
                    state['failed'] = True
                    raise OSError('synthetic replacement during failure')

                with patch('source_adapters.filesystem.os.open', side_effect=tracked_open), \
                        patch('source_adapters.filesystem.os.stat', side_effect=tracked_stat), \
                        patch('source_adapters.filesystem.json.dump', side_effect=replaced_dump):
                    self.assertEqual(self.invoke(module, fixture), 1)
                self.assertTrue(state['checked'])
                with self.assertRaises(OSError):
                    actual_fstat(state['fd'])
                self.assertEqual(output.read_text(), 'replacement-must-survive')

    def test_nonfinite_json_rejected_and_partial_output_removed(self):
        fixture = self.fixture()
        output = fixture[2] / 'result.json'
        with self.assertRaises(ValueError):
            with new_json_output(output) as write:
                write({'value': float('inf')})
        self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
