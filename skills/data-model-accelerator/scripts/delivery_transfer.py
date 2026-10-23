"""Retain a verified local build, then copy and verify a new delivery version.

Private receipts never enter the public ZIP. A successful filesystem copy does
not establish remote/cloud synchronization or authorize deployment.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import uuid
import zipfile

from ae_common import require
import delivery_portal as portal

RECEIPT = 'LOCAL_BUILD.json'


def directory_identity(path):
    path = portal._path(path)
    value = path.stat()
    require(path.is_dir(), 'Expected a delivery directory.')
    return value.st_dev, value.st_ino


def remove_owned_directory(path, identity):
    """Do not remove a replacement directory after an interrupted run."""
    try:
        if directory_identity(path) == identity:
            shutil.rmtree(path)
    except (OSError, ValueError):
        pass


def _separate(path, roots):
    for value in roots:
        root = portal._path(value)
        require(path != root and root not in path.parents and path not in root.parents,
                'Final delivery must be separate from the source, candidate and private work directories.')


def protected_paths(state=None, artifact_root=None, extra=()):
    source = (state or {}).get('inputs', {}).get('source', {})
    roots = [source['path']] if source.get('path') else []
    roots.extend(row['path'] for row in source.get('roots', []))
    if artifact_root is not None:
        roots.append(artifact_root)
    return [str(portal._path(p)) for p in [*roots, *extra]]


def validate_destination(value, state=None, artifact_root=None):
    """Validate an exact new version directory without creating anything.

    Intake can persist the returned absolute string in the private answer
    ``delivery_destination``. Existing versions are checked at transfer time.
    """
    require(isinstance(value, (str, Path)) and str(value).strip(),
            'Choose an absolute delivery destination, or pass --output.')
    require(not any(ord(c) < 32 or ord(c) == 127 for c in str(value)), 'Invalid destination path character.')
    require(Path(value).expanduser().is_absolute(), 'Delivery destination must be an absolute path.')
    path = portal._path(value)
    require(path != path.parent, 'Choose a version directory, not the filesystem root.')
    _separate(path, protected_paths(state, artifact_root))
    return path


def local_work_directory(value=None, protected=(), destination=None):
    default = Path(tempfile.gettempdir()).resolve() / ('dma-finalized-' + str(getattr(os, 'getuid', lambda: 0)()))
    path = portal._path(value if value is not None else default)
    _separate(path, protected)
    if destination is not None:
        _separate(path, [destination])
        require(path != destination.parent, 'Use a private local work folder, not the destination parent.')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    require(path.is_dir() and (info.st_mode & 0o077) == 0, 'Local work directory must be private (mode 0700).')
    if hasattr(os, 'getuid'):
        require(info.st_uid == os.getuid(), 'Local work directory must be owned by the current user.')
    return path


def _file_pin(path):
    path = portal._path(path)
    require(stat.S_ISREG(path.stat().st_mode), 'Expected a regular delivery file.')
    digest = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            size += len(chunk)
            digest.update(chunk)
    return {'bytes': size, 'sha256': digest.hexdigest()}


def verify_local_package(directory, expected=None):
    """Recheck ZIP, exact extracted inventory, and every byte including manifest."""
    directory = portal._path(directory)
    archive_path = portal._path(directory / 'handoff.zip')
    handoff = portal._path(directory / 'handoff')
    require(archive_path.stat().st_size <= portal.MAX_PACKAGE_BYTES * 3, 'Local ZIP exceeds package bounds.')
    pin = _file_pin(archive_path)
    if expected is not None:
        require(pin == expected['archive'], 'Local verified ZIP changed; retain the original build or finalize a new version.')
    integrity = portal.verify_delivery(archive_path)
    actual = {}
    require(handoff.is_dir(), 'Verified local handoff folder is missing.')
    for parent, directories, files in os.walk(handoff, followlinks=False):
        for name in directories:
            portal._path(Path(parent) / name)
        for name in files:
            path = portal._path(Path(parent) / name)
            actual[path.relative_to(handoff).as_posix()] = path
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        require(set(actual) == set(names), 'Extracted handoff inventory differs from the verified ZIP.')
        manifest_bytes = archive.read('DELIVERY_MANIFEST.json')
        for name in names:
            body = archive.read(name)
            require(_file_pin(actual[name]) == {'bytes': len(body), 'sha256': portal._sha(body)},
                    'Extracted handoff bytes differ: ' + name)
    package = {'archive': pin, 'manifest_sha256': portal._sha(manifest_bytes)}
    if expected is not None:
        require(package == expected, 'Local manifest differs from the retained build receipt.')
    return package, integrity


def save_local_receipt(directory, result, destination, protected=()):
    package, _ = verify_local_package(directory)
    receipt = {'schema_version': 1, 'kind': 'local_verified_delivery',
               'package': package, 'result': copy.deepcopy(result),
               'destination': str(destination), 'protected_roots': list(protected)}
    with (portal._path(directory) / RECEIPT).open('x', encoding='utf-8') as stream:
        json.dump(receipt, stream, indent=2)
        stream.write('\n')
    return receipt


def _copy_file(source, destination):
    """Copy between filesystems, without replacing an existing destination."""
    source, destination = portal._path(source), portal._path(destination)
    with source.open('rb') as incoming, destination.open('xb') as outgoing:
        shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)


def transfer_delivery(local_build, output=None):
    """Retry only copying a frozen verified result; no source reads or generation.

    Transfer failures preserve the local build and attach ``delivery_result`` to
    the original exception, so callers retain its type and recovery paths.
    """
    local_build = portal._path(local_build)
    local_identity = directory_identity(local_build)
    receipt_path = portal._path(local_build / RECEIPT)
    require(stat.S_ISREG(receipt_path.stat().st_mode), 'Local build receipt must be a regular file.')
    require(receipt_path.stat().st_size <= 2 * 1024 * 1024, 'Local build receipt exceeds its bound.')
    receipt = json.loads(receipt_path.read_text())
    require(receipt.get('schema_version') == 1 and receipt.get('kind') == 'local_verified_delivery'
            and receipt.get('result', {}).get('status') in ('handoff_verified', 'checkpoint_verified'),
            'Use a verified local build produced by the finalizer.')
    package, _ = verify_local_package(local_build, receipt['package'])
    result = copy.deepcopy(receipt['result'])
    result.update({'local_build': str(local_build), 'local_entrypoint': str(local_build / 'handoff/START_HERE.html'),
                   'local_zip': str(local_build / 'handoff.zip'), 'local_receipt': str(receipt_path)})
    output_identity = None
    destination = None
    transfer_id = uuid.uuid4().hex
    try:
        destination = validate_destination(output if output is not None else receipt.get('destination'))
        _separate(destination, [local_build.parent, *receipt.get('protected_roots', [])])
        require(not destination.exists(), 'Final delivery already exists; choose a new versioned output directory.')
        destination.parent.mkdir(parents=True, exist_ok=True)
        parent_identity = directory_identity(destination.parent)
        destination.mkdir(mode=0o700)  # Exclusive: never adopt a raced/replaced directory.
        output_identity = directory_identity(destination)
        pending = destination / '.transfer-in-progress'
        pending.mkdir(mode=0o700)
        pending_identity = directory_identity(pending)

        def check_owned():
            require(directory_identity(local_build) == local_identity, 'Local build directory changed during transfer.')
            require(directory_identity(destination.parent) == parent_identity
                    and directory_identity(destination) == output_identity,
                    'Delivery directory changed during transfer.')
            require(directory_identity(pending) == pending_identity, 'Pending transfer directory changed.')

        check_owned()
        _copy_file(local_build / 'handoff.zip', pending / 'handoff.zip')
        check_owned()
        target = pending / 'handoff'
        target.mkdir()
        with zipfile.ZipFile(local_build / 'handoff.zip') as archive:
            for name in archive.namelist():
                relative = portal._relative(name)
                check_owned()
                path = portal._path(target / relative)
                path.parent.mkdir(parents=True, exist_ok=True)
                _copy_file(local_build / 'handoff' / relative, path)
        check_owned()
        verify_local_package(pending, package)
        # Recheck the retained copy, too: a concurrent edit cannot be silently
        # accepted merely because the destination happened to match old bytes.
        verify_local_package(local_build, package)
        check_owned()
        # Exclusive writes also protect publication: rename() could replace a
        # file raced into place, and hard links are unavailable on some mounts.
        # Keep the incomplete marker until the public pair has been rechecked.
        _copy_file(pending / 'handoff.zip', destination / 'handoff.zip')
        check_owned()
        published = destination / 'handoff'
        published.mkdir()
        with zipfile.ZipFile(pending / 'handoff.zip') as archive:
            for name in archive.namelist():
                check_owned()
                relative = portal._relative(name)
                path = portal._path(published / relative)
                path.parent.mkdir(parents=True, exist_ok=True)
                _copy_file(pending / 'handoff' / relative, path)
        require(directory_identity(destination) == output_identity, 'Delivery directory changed during publication.')
        verify_local_package(destination, package)
        check_owned()
        remove_owned_directory(pending, pending_identity)
        require({p.name for p in destination.iterdir()} == {'handoff.zip', 'handoff'},
                'Unexpected files appeared in the delivery version.')
        design = result.get('design_folder')
        result.update({'entrypoint': str(destination / 'handoff/START_HERE.html'),
                       'zip': str(destination / 'handoff.zip'), 'folder': str(destination / 'handoff'),
                       'design_folder': str(destination / 'handoff' / Path(design).name) if design else None,
                       'transfer': {'status': 'verified', 'destination': str(destination),
                                    'archive': package['archive'], 'cloud_sync': 'not_verified'}})
        transfer_receipt = local_build / ('transfer-' + transfer_id + '.json')
        result['transfer_receipt'] = str(transfer_receipt)
        with transfer_receipt.open('x', encoding='utf-8') as stream:
            json.dump({'schema_version': 1, 'kind': 'delivery_transfer', 'result': result}, stream, indent=2)
            stream.write('\n')
        return result
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
        if output_identity is not None:
            remove_owned_directory(destination, output_identity)
        result.update({'status': 'local_verified_transfer_failed',
                       'entrypoint': result['local_entrypoint'], 'zip': result['local_zip'],
                       'folder': str(local_build / 'handoff'),
                       'transfer': {'status': 'failed', 'destination': str(destination) if destination else None,
                                    'error': str(error), 'cloud_sync': 'not_verified'},
                       'recovery': 'Retry --transfer-from ' + str(local_build) + ' --output /absolute/new-version; no regeneration is needed.'})
        result['completion'] = {**result.get('completion', {}),
                                'local_artifact_delivery': result.get('completion', {}).get('artifact_delivery'),
                                'artifact_delivery': 'local_verified_transfer_pending'}
        error.delivery_result = result
        raise
