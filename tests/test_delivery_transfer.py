"""Verified-copy and recovery checks; synthetic packages are not native evidence."""
import contextlib
import errno
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import delivery_portal as portal
import delivery_transfer as transfer
import finalize_delivery as finalizer
from test_delivery_portal import fixture


class DeliveryTransferTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.artifacts = self.root / 'candidate'
        self.artifacts.mkdir()
        self.state, self.review = fixture(self.artifacts)
        self.state['answers']['deliverables'] = ['documentation', 'diagrams', 'dictionary', 'implementation']
        self.review['handoff'] = {'design_artifact_id': '0'}
        self.output = self.root / 'destination' / 'delivery-v1'
        self.work = self.root / 'private-work'
        self.state['answers']['delivery_destination'] = str(self.output)

    def finalize(self, output=None, **kwargs):
        return finalizer.finalize_delivery(self.state, self.review, self.artifacts, output,
                                           working_dir=self.work, **kwargs)

    def test_saved_destination_and_explicit_override_keep_private_local_build(self):
        result = self.finalize()
        self.assertEqual(result['folder'], str(self.output / 'handoff'))
        local = Path(result['local_build'])
        self.assertEqual(local.parent, self.work)
        self.assertEqual(self.work.stat().st_mode & 0o777, 0o700)
        self.assertTrue(Path(result['local_zip']).is_file())
        self.assertEqual(Path(result['local_zip']).read_bytes(), Path(result['zip']).read_bytes())
        self.assertEqual({p.name for p in self.output.iterdir()}, {'handoff', 'handoff.zip'})
        self.assertEqual(result['transfer']['cloud_sync'], 'not_verified')
        self.assertTrue(Path(result['transfer_receipt']).is_file())
        alternate = self.root / 'destination' / 'delivery-v2'
        self.assertEqual(self.finalize(alternate)['folder'], str(alternate / 'handoff'))
        self.assertEqual(self.state['answers']['delivery_destination'], str(self.output))

    def test_destination_and_local_paths_are_absent_from_public_zip(self):
        result = self.finalize()
        with zipfile.ZipFile(result['zip']) as archive:
            self.assertNotIn(transfer.RECEIPT, archive.namelist())
            for name in archive.namelist():
                body = archive.read(name)
                self.assertNotIn(str(self.output).encode(), body)
                self.assertNotIn(str(self.work).encode(), body)

    def test_permission_failure_preserves_build_and_retry_needs_no_sources(self):
        original = Path.mkdir
        def deny(path, *args, **kwargs):
            if path == self.output.parent:
                raise PermissionError('Destination unavailable')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'mkdir', deny), self.assertRaises(PermissionError) as failure:
            self.finalize()
        result = failure.exception.delivery_result
        self.assertEqual(result['status'], 'local_verified_transfer_failed')
        self.assertEqual(result['completion']['artifact_delivery'], 'local_verified_transfer_pending')
        local = Path(result['local_build'])
        self.assertTrue((local / transfer.RECEIPT).is_file())
        self.assertFalse(self.output.exists())
        shutil.rmtree(self.artifacts)
        with patch.object(portal, 'package_delivery', side_effect=AssertionError('Do not regenerate')):
            retry = transfer.transfer_delivery(local)
        self.assertEqual(retry['status'], 'handoff_verified')
        self.assertEqual(retry['local_zip'], result['local_zip'])
        self.assertEqual(retry['transfer']['status'], 'verified')

    def test_copy_failure_never_publishes_completed_pair_and_retry_reuses_bytes(self):
        with patch.object(transfer, '_copy_file', side_effect=OSError('Disconnected')), self.assertRaises(OSError) as failure:
            self.finalize()
        result = failure.exception.delivery_result
        digest = transfer._file_pin(Path(result['local_zip']))
        self.assertFalse(self.output.exists())
        self.assertTrue(Path(result['local_entrypoint']).is_file())
        with patch.object(portal, 'package_delivery', side_effect=AssertionError('No generation')):
            copied = transfer.transfer_delivery(result['local_build'])
        self.assertEqual(transfer._file_pin(Path(copied['zip'])), digest)

    def test_corrupted_destination_copy_fails_verification_but_retains_local(self):
        original = transfer._copy_file
        def corrupt(source, destination):
            original(source, destination)
            if destination.name == 'START_HERE.html':
                destination.write_bytes(b'corrupt')
        with patch.object(transfer, '_copy_file', corrupt), self.assertRaisesRegex(ValueError, 'bytes differ') as failure:
            self.finalize()
        self.assertFalse(self.output.exists())
        transfer.verify_local_package(Path(failure.exception.delivery_result['local_build']))

    def test_changed_local_zip_or_folder_cannot_be_retried(self):
        result = self.finalize()
        local = Path(result['local_build'])
        original = (local / 'handoff.zip').read_bytes()
        (local / 'handoff.zip').write_bytes(original + b'changed')
        with self.assertRaisesRegex(ValueError, 'ZIP changed'):
            transfer.transfer_delivery(local, self.root / 'new-v1')
        (local / 'handoff.zip').write_bytes(original)
        (local / 'handoff/START_HERE.html').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'bytes differ'):
            transfer.transfer_delivery(local, self.root / 'new-v2')
        self.assertFalse((self.root / 'new-v1').exists())
        self.assertFalse((self.root / 'new-v2').exists())

    def test_no_cross_filesystem_rename_is_required(self):
        with patch('os.rename', side_effect=OSError(errno.EXDEV, 'Cross-device link')):
            result = self.finalize()
        self.assertEqual(result['transfer']['status'], 'verified')

    def test_existing_version_is_not_overwritten_by_retry(self):
        result = self.finalize()
        before = Path(result['zip']).read_bytes()
        with self.assertRaisesRegex(ValueError, 'already exists'):
            transfer.transfer_delivery(result['local_build'])
        self.assertEqual(before, Path(result['zip']).read_bytes())

    def test_destination_and_work_paths_reject_overlap_symlinks_and_traversal(self):
        source = self.root / 'readonly-source'
        source.mkdir()
        second = self.root / 'named-source'
        second.mkdir()
        self.state['inputs']['source'] = {'path': str(source), 'roots': [{'id': 'other', 'path': str(second)}]}
        for bad in (self.artifacts / 'delivery', source / 'delivery', second / 'delivery', self.root):
            with self.subTest(path=bad), self.assertRaisesRegex(ValueError, 'must be separate'):
                self.finalize(bad)
        for bad in ('relative/version', str(self.root / '..' / 'bad'), '/', str(self.root / 'bad\npath')):
            with self.subTest(path=bad), self.assertRaises(ValueError):
                transfer.validate_destination(bad)
        alias = self.root / 'alias'
        alias.symlink_to(source, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            transfer.validate_destination(alias / 'delivery')
        with self.assertRaisesRegex(ValueError, 'must be separate'):
            finalizer.finalize_delivery(self.state, self.review, self.artifacts, self.output, working_dir=source / 'work')
        self.assertEqual(list(source.iterdir()), [])
        self.assertEqual(list(second.iterdir()), [])

    def test_retry_retains_source_and_candidate_protection_without_state(self):
        result = self.finalize()
        with self.assertRaisesRegex(ValueError, 'must be separate'):
            transfer.transfer_delivery(result['local_build'], self.artifacts / 'bad')
        with self.assertRaisesRegex(ValueError, 'must be separate'):
            transfer.transfer_delivery(result['local_build'], self.work / 'bad')

    def test_symlink_inside_local_handoff_is_rejected_without_reading_target(self):
        result = self.finalize()
        local = Path(result['local_build'])
        target = local / 'handoff/START_HERE.html'
        target.unlink()
        target.symlink_to(self.output / 'handoff/START_HERE.html')
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            transfer.transfer_delivery(local, self.root / 'new-version')

    def test_replaced_destination_is_never_removed(self):
        original = transfer._copy_file
        moved = []
        def replace(source, destination):
            original(source, destination)
            if not moved:
                self.output.rename(self.root / 'original-partial')
                self.output.mkdir()
                (self.output / 'unrelated.txt').write_text('Preserve me')
                moved.append(True)
        with patch.object(transfer, '_copy_file', replace), self.assertRaisesRegex(ValueError, 'directory changed') as failure:
            self.finalize()
        self.assertEqual((self.output / 'unrelated.txt').read_text(), 'Preserve me')
        self.assertTrue(Path(failure.exception.delivery_result['local_zip']).is_file())

    def test_retry_cli_needs_only_local_build_and_optional_new_destination(self):
        result = self.finalize()
        alternate = self.root / 'destination' / 'delivery-v2'
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), patch.object(portal, 'package_delivery', side_effect=AssertionError('No generation')):
            status = finalizer.main(['--transfer-from', result['local_build'], '--output', str(alternate)])
        self.assertEqual(status, 0, err.getvalue())
        self.assertEqual(json.loads(out.getvalue())['zip'], str(alternate / 'handoff.zip'))
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = finalizer.main(['--transfer-from', result['local_build'], '--output', str(alternate)])
        self.assertEqual(status, 2)
        self.assertEqual(json.loads(out.getvalue())['status'], 'local_verified_transfer_failed')
        self.assertIn('--transfer-from', json.loads(out.getvalue())['recovery'])

    def test_checkpoint_retry_preserves_incomplete_status(self):
        result = self.finalize(checkpoint=True)
        retry = transfer.transfer_delivery(result['local_build'], self.root / 'checkpoint-v2')
        self.assertEqual(retry['status'], 'checkpoint_verified')
        self.assertEqual(retry['completion']['artifact_delivery'], 'incomplete_checkpoint')

    def test_missing_destination_does_not_guess_or_write(self):
        del self.state['answers']['delivery_destination']
        with self.assertRaisesRegex(ValueError, 'destination'):
            self.finalize()
        self.assertFalse(self.work.exists())


if __name__ == '__main__':
    unittest.main()
