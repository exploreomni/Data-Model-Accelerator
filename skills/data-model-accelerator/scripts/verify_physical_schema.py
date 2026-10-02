"""Reconcile declared model columns with separately captured physical metadata.

Exact identifiers are intentional: a host must preserve quoting/case and supply
qualified names consistently. Export hashes establish association, not authenticity.
"""
import argparse
from pathlib import Path
import sys

from ae_common import hash_file, load_json, require, snapshot, write_json
from freeze_benchmark import _bound_json, _fields, _sha, _text
from verify_dbt_evidence import instant


def reconcile(inventory, observed, candidate_sha256):
    _fields(observed, ('schema_version', 'kind', 'candidate_sha256', 'origin',
                      'validation_scope', 'adapter_type', 'captured_at', 'identifier_policy',
                      'scope', 'relations'), ('native_receipt_sha256', 'invocation_id'))
    require(type(observed['schema_version']) is int and observed['schema_version'] == 1
            and observed['kind'] == 'physical_schema_observation', 'Unsupported physical schema observation')
    require(_sha(observed['candidate_sha256']) == _sha(candidate_sha256), 'Physical observation candidate drift')
    require(observed['origin'] in ('executed_metadata', 'provided_export'), 'Physical metadata must be observed or explicitly provided')
    require(observed['validation_scope'] in ('local', 'target'), 'Invalid metadata validation scope')
    _text(observed['adapter_type'], 'metadata adapter')
    instant(observed['captured_at'], 'metadata capture')
    require(observed['identifier_policy'] == 'exact', 'Identifiers require exact case/quoting, not silent folding')
    require(type(observed['scope']) is list and observed['scope'], 'Metadata scope required')
    require(all(type(item) is str and item.strip() == item and item for item in observed['scope']), 'Invalid metadata scope')
    require(len(set(observed['scope'])) == len(observed['scope']), 'Duplicate metadata scope')
    require(type(inventory) is dict and type(inventory.get('schema_version')) is int
            and inventory['schema_version'] == 1 and inventory.get('kind') == 'data_model_inventory', 'Invalid model inventory')

    def index(records, documented=False):
        require(type(records) is list and records, 'Nonempty physical relation denominator required')
        indexed, model_ids = {}, set()
        for item in records:
            require(type(item) is dict, 'Relation must be an object')
            name = _text(item.get('physical_name'), 'qualified physical name')
            require(name not in indexed, 'Duplicate physical relation: ' + name)
            columns = item.get('columns')
            require(type(columns) is list and columns, 'Nonempty column denominator required: ' + name)
            for column in columns:
                _text(column, 'physical column name')
            require(len(columns) == len(set(columns)), 'Duplicate physical column: ' + name)
            if documented:
                mid = _text(item.get('model_id'), 'model_id')
                require(mid not in model_ids, 'Duplicate documentation model ID')
                model_ids.add(mid)
            indexed[name] = set(columns)
        return indexed

    declared = index(inventory.get('models'), True)
    physical = index(observed['relations'])
    errors = []
    if set(declared) != set(physical):
        errors.append('Physical relation coverage differs: missing=' + repr(sorted(set(declared) - set(physical)))
                      + ', undocumented=' + repr(sorted(set(physical) - set(declared))))
    for name in sorted(set(declared) & set(physical)):
        if declared[name] != physical[name]:
            errors.append('Physical column coverage differs: ' + name + '; missing=' + repr(sorted(declared[name] - physical[name]))
                          + ', undocumented=' + repr(sorted(physical[name] - declared[name])))
    return {'schema_version': 1, 'kind': 'physical_schema_verification', 'passed': not errors,
            'candidate_sha256': candidate_sha256, 'validation_scope': observed['validation_scope'],
            'relations': len(physical), 'columns': sum(len(columns) for columns in physical.values()), 'errors': errors,
            'limitations': ['Metadata origin and scope are self-attested; the host must capture a complete, independently scoped export.',
                            'Exact names/columns only; types, nullability, grain, prose, lineage and access policy need separate review.']}


def verify(inventory_path, observed_path, project):
    candidate = snapshot(project)
    inventory, inventory_hash = _bound_json(inventory_path)
    observed, observed_hash = _bound_json(observed_path)
    result = reconcile(inventory, observed, candidate['sha256'])
    require(snapshot(project) == candidate and hash_file(inventory_path) == inventory_hash
            and hash_file(observed_path) == observed_hash, 'Physical schema evidence changed during verification')
    result.update(inventory_sha256=inventory_hash, observation_sha256=observed_hash)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('inventory', 'observation', 'project', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        require(args.project.absolute() not in args.output.absolute().parents, 'Output must stay outside candidate')
        result = verify(args.inventory, args.observation, args.project)
        write_json(args.output, result)
        print('PASS' if result['passed'] else 'FAIL: ' + '; '.join(result['errors']))
        return 0 if result['passed'] else 1
    except (ValueError, OSError, TypeError, KeyError) as error:
        print('Physical schema verification refused: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
