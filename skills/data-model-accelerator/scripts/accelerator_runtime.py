#!/usr/bin/env python3
"""Read-only installed runtime identity; an explicit comparison, never an update."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

from ae_common import hash_json

IDENTITY_SCOPE = 'skill_scripts_references_agents_assets'
_REVISION = re.compile(r'(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z')
_FINGERPRINT = re.compile(r'[0-9a-fA-F]{64}\Z')
_CONTENT_PATHS = ('SKILL.md', 'scripts', 'references', 'agents', 'assets')
_EXCLUDED = ('**/__pycache__/**', '**/.git/**', '**/.venv/**',
             '**/node_modules/**', '**/*.pyc', '**/.DS_Store')


def _expected(value, pattern, label):
    if value is None:
        return None
    if type(value) is not str or not pattern.fullmatch(value):
        raise ValueError(label + ' must be a full hexadecimal SHA value')
    return value.lower()


def _git_identity(root):
    """No remotes, hooks, filters, source programs or optional index writes."""
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_OPTIONAL_LOCKS='0', GIT_TERMINAL_PROMPT='0',
               GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_NO_LAZY_FETCH='1', GIT_ALLOW_PROTOCOL='')
    overrides = ['-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false',
                 '-c', 'core.hooksPath=' + os.devnull]

    def git(*args):
        return subprocess.run(
            ['git', *overrides, '-C', str(root), *args],
            env=env, check=True, capture_output=True, timeout=5).stdout

    head = None
    try:
        repository = Path(os.fsdecode(git('rev-parse', '--show-toplevel').strip()))
        root.relative_to(repository)
        # A copied skill inside an unrelated repository must not inherit its HEAD.
        git('ls-files', '--error-unmatch', '--', 'SKILL.md')
        head = git('rev-parse', '--verify', 'HEAD').decode('ascii').strip().lower()
        if not _REVISION.fullmatch(head):
            return None, None
        # Status can invoke a repository-defined clean/process filter while
        # refreshing file metadata. Read only filter key names, never commands,
        # and neutralize every driver before inspecting the working files.
        try:
            keys = git('config', '--null', '--name-only', '--get-regexp',
                       r'^filter\..*\.(clean|smudge|process|required)$').decode('utf-8').split('\0')
        except subprocess.CalledProcessError as error:
            if error.returncode != 1:
                raise
            keys = []
        if len(keys) > 512:
            return head, None
        for key in filter(None, keys):
            match = re.fullmatch(r'filter\..+\.(clean|smudge|process|required)', key)
            if match is None or any(ord(char) < 32 for char in key):
                return head, None
            overrides.extend(['-c', key + ('=false' if match.group(1) == 'required' else '=')])
        pathspecs = list(_CONTENT_PATHS) + [':(exclude,glob)' + value for value in _EXCLUDED]
        dirty = bool(git('status', '--porcelain=v1', '-z', '--untracked-files=all',
                         '--ignore-submodules=all', '--', *pathspecs))
        return head, dirty
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
        return head, None


def inspect_runtime(skill_root=None, *, expected_revision=None, expected_fingerprint=None):
    """Return public-safe identity without mutating a run or choosing an install.

    Expected values are explicit full hashes, not branch names or upstream claims.
    The fingerprint reuses run_control.content_manifest exactly, so existing
    runtime receipts and portable-copy comparisons remain compatible. Missing or
    unsafe content returns unavailable evidence, not an authoring prohibition.
    """
    expected_revision = _expected(expected_revision, _REVISION, 'Expected revision')
    expected_fingerprint = _expected(expected_fingerprint, _FINGERPRINT, 'Expected fingerprint')
    # Keep this import local: run_control may call this helper while observing a run.
    from run_control import content_manifest
    root = Path(skill_root).absolute() if skill_root is not None else Path(__file__).absolute().parent.parent
    fingerprint, file_count, head, dirty = None, 0, None, None
    try:
        manifest = content_manifest(root)
        fingerprint, file_count = hash_json(manifest), len(manifest)
        head, dirty = _git_identity(root)
    except (OSError, ValueError):
        # Do not include exception text: it can contain private installation paths.
        pass

    def comparison(expected, actual):
        if expected is None:
            return 'not_requested'
        if actual is None:
            return 'unavailable'
        return 'match' if expected == actual else 'mismatch'

    revision_check = comparison(expected_revision, head)
    fingerprint_check = comparison(expected_fingerprint, fingerprint)
    checks = [value for value in (revision_check, fingerprint_check) if value != 'not_requested']
    status = ('mismatch' if 'mismatch' in checks else
              'match' if checks and all(value == 'match' for value in checks) else 'unknown')
    # HEAD alone does not identify modified installed bytes.
    if status == 'match' and expected_fingerprint is None and dirty is not False:
        status = 'unknown'
    advisories = []
    if fingerprint is None:
        advisories.append('Installed content could not be identified safely. Check the explicitly selected skill directory and permissions.')
    elif head is None:
        advisories.append('Repository revision is unavailable; use the content fingerprint to compare a copied installation.')
    elif dirty is None:
        advisories.append('Repository revision is available but local-change status could not be established; compare an expected content fingerprint.')
    if dirty is True:
        advisories.append('Installed skill content has local changes. Preserve them and compare the content fingerprint before updating.')
    if status == 'mismatch':
        advisories.append('The selected installation differs from the supplied reference. Deliberately update the host-installed copy, then restart or reload the host as required and recheck before a new run. This diagnostic does not update an active run.')
    elif not checks:
        advisories.append('Freshness is unknown without an explicit expected revision or fingerprint. No upstream latest-version check was performed.')
    elif status == 'unknown':
        advisories.append('The supplied reference could not fully establish freshness. Compare an expected content fingerprint when Git identity is unavailable or the skill has local changes.')

    return {'kind': 'accelerator_runtime_identity', 'schema_version': 1,
            'runtime_sha256': fingerprint, 'file_count': file_count,
            'identity_scope': IDENTITY_SCOPE,
            'content_status': 'available' if fingerprint is not None else 'unavailable',
            'installed_revision': head,
            'repository_status': 'available' if head is not None else 'unavailable',
            'skill_dirty': dirty,
            'freshness': {'status': status, 'expected_revision': expected_revision,
                          'expected_fingerprint': expected_fingerprint,
                          'revision_comparison': revision_check,
                          'fingerprint_comparison': fingerprint_check},
            'advisories': advisories,
            'qualification': 'Local installed bytes and repository context only. A match applies only to the supplied reference; it does not establish upstream latest, host loading, execution, approval or native acceptance. Advisory only; authoring remains available.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skill-root', type=Path, help='Explicit installed skill directory; defaults to this helper\'s skill.')
    parser.add_argument('--expected-revision', help='Explicit complete Git commit SHA; never fetched.')
    parser.add_argument('--expected-fingerprint', help='Explicit complete installed content SHA-256.')
    args = parser.parse_args(argv)
    try:
        result = inspect_runtime(args.skill_root, expected_revision=args.expected_revision,
                                 expected_fingerprint=args.expected_fingerprint)
    except ValueError:
        print(json.dumps({'kind': 'accelerator_runtime_diagnostic_error', 'schema_version': 1,
                          'error': 'Expected revision must be a full Git SHA and expected fingerprint must be a full SHA-256.'}, sort_keys=True))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    # Mismatch is an advisory, never a process-level authoring gate.
    return 0 if result['content_status'] == 'available' else 2


if __name__ == '__main__':
    raise SystemExit(main())
