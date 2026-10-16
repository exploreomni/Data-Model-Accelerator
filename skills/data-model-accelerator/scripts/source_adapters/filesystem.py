"""Descriptor-relative source reads and exclusive result writes."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat
from .base import MAX_FILE_BYTES, validate_files


def _identity(info):
    return info.st_dev, info.st_ino


def _open_directory(path):
    """Retain the final descriptor and identities of every no-follow ancestor."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open('/', flags)
    identities = [_identity(os.fstat(fd))]
    try:
        for component in path.parts[1:]:
            child = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = child
            identities.append(_identity(os.fstat(fd)))
        return fd, tuple(identities)
    except BaseException:
        os.close(fd)
        raise


@contextmanager
def new_json_output(path):
    """Hold a canonical parent before parsing; publish one new private JSON file.

    Parent replacement never redirects writes. Recheck the ancestor identities
    and output inode before reporting success; failed writes remove only the
    still-matching entry through the retained directory descriptor.
    """
    path = Path(path).absolute()
    if path.parent.resolve() != path.parent:
        raise ValueError('source.redirected_output')
    parent_fd, ancestors = _open_directory(path.parent)
    created, output_fd, written = None, None, False

    def check():
        current_fd, current_ancestors = _open_directory(path.parent)
        try:
            if current_ancestors != ancestors:
                raise ValueError('source.output_parent_changed')
        finally:
            os.close(current_fd)
        if created is not None:
            current = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            if _identity(current) != created or not stat.S_ISREG(current.st_mode):
                raise ValueError('source.output_replaced')

    def write(value):
        nonlocal created, output_fd, written
        if created is not None:
            raise ValueError('source.output_already_written')
        check()
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        output_fd = os.open(path.name, flags, 0o600, dir_fd=parent_fd)
        created = _identity(os.fstat(output_fd))
        # Keep the created inode alive until validation/cleanup finishes, even
        # if another process unlinks its directory entry during serialization.
        with os.fdopen(os.dup(output_fd), 'w', encoding='utf-8') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream, indent=2, ensure_ascii=True, allow_nan=False)
            stream.write('\n')
        check()
        written = True

    try:
        # Reject existing files, directories and dangling links before parsing.
        try:
            os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError('source.output_exists')
        yield write
        if not written:
            raise ValueError('source.output_not_written')
        check()
    except BaseException:
        if created is not None:
            try:
                if _identity(os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)) == created:
                    os.unlink(path.name, dir_fd=parent_fd)
            except OSError:
                pass
        raise
    finally:
        if output_fd is not None:
            os.close(output_fd)
        os.close(parent_fd)


def read_assigned(root, relative):
    validate_files({relative: ''})
    root = Path(root).absolute()
    if root.resolve() != root:
        raise ValueError('source.redirected_root')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open('/', flags)
    try:
        for component in root.parts[1:] + Path(relative).parts[:-1]:
            child = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        file_fd = os.open(Path(relative).name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(file_fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
                raise ValueError('source.unsafe_or_oversized_file')
            raw = stream.read(MAX_FILE_BYTES + 1)
            after = os.fstat(stream.fileno())
            if before.st_size != len(raw) or after.st_size != len(raw) or before.st_mtime_ns != after.st_mtime_ns or len(raw) > MAX_FILE_BYTES:
                raise ValueError('source.changed_file')
        return raw
    finally:
        os.close(fd)
