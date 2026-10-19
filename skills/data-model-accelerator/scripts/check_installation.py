#!/usr/bin/env python3
"""Compare an installed skill with a reviewed checkout, without modifying either."""
import argparse
import json
from pathlib import Path

from ae_common import hash_json
from run_control import content_manifest


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
    parser.add_argument('--expected-skill', type=Path, required=True)
    parser.add_argument('--installed-skill', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = compare(args.expected_skill, args.installed_skill)
        print(json.dumps(result, indent=2))
        return 0 if result['status'] == 'match' else 1
    except (ValueError, OSError) as error:
        parser.exit(2, 'Installation comparison unavailable: ' + str(error) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
