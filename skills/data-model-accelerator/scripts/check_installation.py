#!/usr/bin/env python3
"""Compare an installed skill with a reviewed checkout, without modifying either."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from ae_common import hash_json
from run_control import content_manifest

MAX_ALTERNATIVES = 16


def _revision(path):
    """Read only the supplied tree's Git identity, never remotes or host config."""
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env['GIT_OPTIONAL_LOCKS'] = '0'
    def git(*args):
        return subprocess.run(['git', '-C', str(path), *args], env=env, check=True,
                              capture_output=True, text=True, timeout=5).stdout.strip()
    try:
        root = git('rev-parse', '--show-toplevel')
        head = git('rev-parse', '--verify', 'HEAD')
        branch = git('symbolic-ref', '--quiet', '--short', 'HEAD')
    except (OSError, subprocess.SubprocessError):
        # Installed portable skills need not be Git checkouts. A detached HEAD
        # still has a useful revision even when no branch name is available.
        try:
            return {'root': git('rev-parse', '--show-toplevel'),
                    'head': git('rev-parse', '--verify', 'HEAD'), 'branch': None}
        except (OSError, subprocess.SubprocessError):
            return None
    return {'root': root, 'head': head, 'branch': branch}


def _identity(path):
    # Do not resolve symlinks before content_manifest applies its safety check.
    path = Path(path).absolute()
    manifest = content_manifest(path)
    return {'path': str(path), 'content_sha256': hash_json(manifest),
            'file_count': len(manifest), 'repository': _revision(path),
            'portable_skill': 'available', 'identity_scope': 'skill_scripts_references_agents_assets',
            'qualification': 'Repository HEAD is context only; the content hash identifies these bytes. No skill code was executed.'}


def preflight(selected_skill=None, *, expected_skill=None, alternative_skills=(),
              host=None, model=None, effort=None):
    """Inspect explicit installations only; never select or rewrite host settings.

    Alternative presence is not proof that a host loads it. Model/effort values
    are supplied preferences, never observed host telemetry or overrides.
    """
    if not isinstance(alternative_skills, (tuple, list)) or len(alternative_skills) > MAX_ALTERNATIVES:
        raise ValueError('Supply at most 16 explicit alternative skill paths')
    for value in (host, model, effort):
        if value is not None and (type(value) is not str or not value.strip() or len(value) > 256):
            raise ValueError('Host, model and effort must be bounded nonempty strings when supplied')
    from guided_workflow import _secrets
    _secrets({'host': host, 'model': model, 'effort': effort})
    selected = _identity(selected_skill or Path(__file__).resolve().parent.parent)
    alternatives, seen = [], {selected['path']}
    for supplied in alternative_skills:
        path = str(Path(supplied).absolute())
        if path in seen:
            continue
        seen.add(path)
        try:
            row = _identity(path)
            row['relation_to_selected'] = ('same_content' if row['content_sha256'] == selected['content_sha256'] else 'different_content')
        except (ValueError, OSError):
            row = {'path': path, 'portable_skill': 'unavailable', 'relation_to_selected': 'unavailable',
                   'qualification': 'Missing, unreadable or unsafe skill directory; content was not qualified.'}
        alternatives.append(row)
    comparison = compare(expected_skill, selected['path']) if expected_skill is not None else None
    conflicts = [x['path'] for x in alternatives if x['relation_to_selected'] == 'different_content']
    checker = _identity(Path(__file__).resolve().parent.parent)
    return {'schema_version': 1, 'kind': 'skill_installation_preflight',
            'status': 'review_required' if conflicts or any(x['relation_to_selected'] == 'unavailable' for x in alternatives)
                      or (comparison and comparison['status'] != 'match') else 'identified',
            'selected': selected, 'comparison': comparison, 'alternatives': alternatives,
            'possible_conflicts': conflicts, 'host_resolution': 'not_observed',
            'runtime': {'checker_skill': checker, 'python_executable': sys.executable,
                        'python_version': '.'.join(map(str, sys.version_info[:3])),
                        'selected_code_execution': 'not_run'},
            'host': {'supplied_name': host, 'plugin_qualification': 'not_tested',
                     'native_integration': 'not_tested', 'credentials': 'not_checked'},
            'model_policy': {'requested_model': model, 'requested_effort': effort,
                             'observed_model': None, 'observed_effort': None,
                             'action': 'preserve_configured_defaults',
                             'guidance': 'Preserve configured model and effort. Do not select cheaper defaults or silently downgrade; only attributable host telemetry can establish observed settings.'},
            'qualification': 'Read-only portable skill availability and content identity. Only explicitly supplied alternatives were checked; host precedence, plugin loading and native integration remain untested. No installation or global configuration was changed.'}


def compare(expected_skill, installed_skill):
    expected = content_manifest(expected_skill)
    installed = content_manifest(installed_skill)
    missing = sorted(set(expected) - set(installed))
    extra = sorted(set(installed) - set(expected))
    changed = sorted(path for path in set(expected) & set(installed) if expected[path] != installed[path])
    return {'schema_version': 1, 'kind': 'skill_installation_comparison',
            'status': 'match' if not (missing or extra or changed) else 'different',
            'expected_sha256': hash_json(expected), 'installed_sha256': hash_json(installed),
            'missing': missing, 'extra': extra, 'changed': changed,
            'qualification': 'Content comparison only. Does not install code, launch an agent, validate credentials or establish native acceptance.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-skill', type=Path)
    parser.add_argument('--installed-skill', type=Path)
    parser.add_argument('--preflight', action='store_true', help='Read-only identity and explicit installation conflict report.')
    parser.add_argument('--selected-skill', type=Path)
    parser.add_argument('--alternative-skill', type=Path, action='append', default=[])
    parser.add_argument('--host')
    parser.add_argument('--model', help='Supplied preference; never changes the configured model.')
    parser.add_argument('--effort', help='Supplied preference; never changes the configured effort.')
    args = parser.parse_args(argv)
    if not args.preflight and (not args.expected_skill or not args.installed_skill):
        parser.error('comparison requires --expected-skill and --installed-skill; use --preflight for identity inspection')
    if not args.preflight and (args.selected_skill or args.alternative_skill or args.host or args.model or args.effort):
        parser.error('identity options require --preflight')
    if args.selected_skill and args.installed_skill:
        parser.error('use either --selected-skill or --installed-skill in preflight mode')
    try:
        result = (preflight(args.selected_skill or args.installed_skill, expected_skill=args.expected_skill,
                            alternative_skills=args.alternative_skill, host=args.host, model=args.model, effort=args.effort)
                  if args.preflight else compare(args.expected_skill, args.installed_skill))
        print(json.dumps(result, indent=2))
        return 0 if result['status'] in {'match', 'identified'} else 1
    except (ValueError, OSError) as error:
        parser.exit(2, 'Installation comparison unavailable: ' + str(error) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
