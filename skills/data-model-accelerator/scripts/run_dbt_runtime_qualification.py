#!/usr/bin/env python3
"""Execute a synthetic v2/OSS local pilot with independently fixed expectations.

Install the selected runtime and checksum-pinned driver separately. This helper
never downloads, logs in or uses customer projects. --execute is required.
Generated projects, databases and evidence must remain outside the checkout.
"""
import argparse
import json
from pathlib import Path
import sys

from ae_common import require, snapshot
from dbt_runtime import driver_contract, runtime_identity, validate_selection
from run_dbt_project import _private_json, run_project
from verify_dbt_evidence import canonical, verify


def qualify(distribution, executable, driver, output, execute=False):
    require(execute is True, 'Explicit --execute is required')
    import duckdb
    output = Path(output).absolute()
    checkout = Path(__file__).resolve().parents[3]
    require(checkout != output and checkout not in output.parents, 'Qualification evidence must remain outside the checkout')
    require(not output.exists() and not output.is_symlink(), 'Qualification output must be new')
    canonical(output.parent)
    executable, driver = canonical(executable), canonical(driver)
    selected = validate_selection({'distribution': distribution, 'version': '2.0.8'})
    identity, driver_info = runtime_identity(executable, selected), driver_contract()
    output.mkdir(mode=0o700)
    outcomes = []
    # Different project names and database files also make artifact reuse fail.
    for label, incorrect in (('positive', False), ('intentional_failure', True)):
        root = output / label
        root.mkdir(mode=0o700)
        project, profiles = root / 'source', root / 'profiles'
        for path in (project / 'models', project / 'seeds', project / 'tests', profiles):
            path.mkdir(parents=True, mode=0o700)
        name = 'qualification_' + label
        (project / 'dbt_project.yml').write_text('name: ' + name + "\nversion: '1.0'\nconfig-version: 2\nprofile: qualification\n", encoding='utf-8')
        (project / 'seeds/input.csv').write_text('id,amount\n1,10\n2,25\n', encoding='utf-8')
        (project / 'models/orders.sql').write_text("{{ config(materialized='table') }}\nselect id, amount * " +
            ('3' if incorrect else '2') + " as doubled from {{ ref('input') }}\n", encoding='utf-8')
        (project / 'models/schema.yml').write_text('version: 2\nmodels:\n  - name: orders\n    columns:\n      - name: id\n        data_tests: [not_null]\n', encoding='utf-8')
        # Literal expected amounts are independent of the candidate expression.
        (project / 'tests/exact_values.sql').write_text("select * from {{ ref('orders') }} where (id = 1 and doubled != 20) or (id = 2 and doubled != 50)\n", encoding='utf-8')
        database = root / 'warehouse.duckdb'
        (profiles / 'profiles.yml').write_text('qualification:\n  target: dev\n  outputs:\n    dev:\n      type: duckdb\n      path: ' +
            json.dumps(str(database)) + '\n      schema: main\n      threads: 1\n', encoding='utf-8')
        source = snapshot(project)
        request = {'schema_version': 2, 'project_sha256': source['sha256'], 'adapter_type': 'duckdb',
                   'profile': 'qualification', 'target': 'dev', 'profiles_dir': str(profiles),
                   'allowed_destinations': [{'database': 'warehouse', 'schema': 'main'}],
                   'expected_profile': {'path': str(database)}, 'timeout_seconds': 120,
                   'dbt_runtime': selected, 'runtime_identity': identity,
                   'driver': {'path': str(driver), 'sha256': driver_info['sha256'], 'version': driver_info['version']}}
        request_path = root / 'request.json'
        _private_json(request_path, request)
        result = run_project(project, request_path, root / 'execution', executable, execute=True)
        require(snapshot(project) == source, 'Qualification mutated original project')
        require(result['evidence_complete'] is (not incorrect), 'Independent native outcome mismatch')
        if not incorrect:
            require(verify(result['receipt_path'])['evidence_complete'], 'Archived native evidence failed recheck')
            with duckdb.connect(str(database), read_only=True) as connection:
                rows = connection.execute('select id, doubled from main.orders order by id').fetchall()
            require(rows == [(1, 20), (2, 50)], 'Independent physical result mismatch')
        else:
            runs = json.loads((root / 'execution/build/run_results.json').read_text(encoding='utf-8'))
            matches = [r for r in runs['results'] if r['unique_id'] == 'test.' + name + '.exact_values']
            require(len(matches) == 1 and matches[0]['status'] == 'fail' and matches[0]['failures'] == 2,
                    'Intentional failure must be the exact independently expected two failing rows')
        outcomes.append({'case': label, 'expected_evidence_complete': not incorrect,
                         'observed_evidence_complete': result['evidence_complete'], 'receipt_path': result['receipt_path']})
    summary = {'schema_version': 1, 'kind': 'native_dbt_runtime_qualification', 'passed': True,
               'selection': selected, 'cases': outcomes,
               'limitations': ['Synthetic local DuckDB evidence only; no cloud authentication, warehouse acceptance or deployment.']}
    _private_json(output / 'qualification.json', summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--distribution', choices=('dbt', 'dbt_oss'), required=True)
    for name in ('dbt', 'driver', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = qualify(args.distribution, args.dbt, args.driver, args.output, args.execute)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, ImportError, KeyError, TypeError) as error:
        print('Native runtime qualification failed: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
