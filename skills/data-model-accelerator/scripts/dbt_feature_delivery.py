"""Prepare opt-in dbt feature candidates; never edit or execute a project."""
import argparse
import hashlib
import json

from dbt_runtime import runtime_contract

ACCEPTANCE = {
    'sql_analysis': 'Capture the effective analysis mode; baseline or authentication fallback cannot pass strict analysis.',
    'native_lint': 'Check every eligible file and every violation; exit code zero alone is insufficient. Retain SQLFluff checks separately.',
    'information_schema': 'Read the bounded versioned export; verify IDs and coverage without exporting SQL, variables or secrets.',
    'checks': 'Exercise both passing and deliberately failing metadata; verify enabled checks and full intended resource scope.',
    'batch_tests': 'Reconcile every individual expected test and failure; batching must not hide skipped or missing tests.',
    'model_freshness': 'Confirm each model/source timestamp, timezone, threshold and late-arrival policy against independent expectations.',
    'docs_v2': 'Validate the generated site and artifacts offline; keep START_HERE.html as the portable review entrypoint.',
    'incremental': 'Compare initial and subsequent builds, late updates, deletes, reruns, schema changes and recovery to an independent baseline.',
    'snapshots': 'Exercise changes and deletions over multiple runs; validate history intervals, current rows and key uniqueness.',
    'unit_tests': 'Use independent edge-case inputs and expected rows; include nulls, fanout, filters and tenant boundaries.',
    'contracts': 'Verify declared columns/types and actual adapter enforcement; declaration is not an enforced constraint.',
    'model_versions': 'Validate versioned refs and every affected downstream consumer before retiring an old version.',
    'dbt_state': 'Confirm service entitlement, account/project, state baseline, exact selected closure and recovery; no implicit activation.',
    'local_unit_tests': 'Experimental: verify local-versus-warehouse semantics, supported types and security before adopting.',
    'multi_adapter': 'Experimental: qualify every adapter, cross-boundary dependency and type conversion independently.',
}


def prepare_features(selection, warehouse=None):
    contract = runtime_contract(selection, warehouse)
    selected = contract['selection']
    files, features = [], []
    for name in selected['features']:
        capability = contract['features'][name]
        features.append({'name': name, 'status': capability['status'],
                         'acceptance': ACCEPTANCE[name], 'enabled': False,
                         'native_validation': 'not_run'})
    def candidate(path, body, operation):
        files.append({'path': path, 'content': body, 'sha256': hashlib.sha256(body.encode()).hexdigest(),
                      'operation': operation, 'status': 'candidate_only'})
    requested = set(selected['features'])
    if requested & {'information_schema', 'checks'} and contract['features']['information_schema']['documented']:
        candidate('dbt_project.yml.fragment', 'info_schema:\n  version: 1\n', 'review_and_merge_owned_keys')
    if 'checks' in requested and contract['features']['checks']['documented']:
        candidate('checks/dma_model_descriptions.sql',
                  "select m.unique_id\nfrom {{ info_schema('models') }} as m\nwhere nullif(trim(m.description), '') is null\n", 'create_after_review')
        candidate('checks/dma_public_model_owners.sql',
                  "select m.unique_id\nfrom {{ info_schema('models') }} as m\nleft join {{ info_schema('groups') }} as g on m.\"group\" = g.name\nwhere m.access = 'public'\n  and coalesce(nullif(trim(g.owner_name), ''), nullif(trim(g.owner_email), '')) is null\n", 'create_after_review')
        candidate('checks/_dma_checks.yml',
                  'version: 2\nchecks:\n  - name: dma_model_descriptions\n    description: Require a nonempty model definition.\n    config:\n      severity: error\n  - name: dma_public_model_owners\n    description: Require a responsible group owner for public models.\n    config:\n      severity: error\n', 'review_and_merge_without_overwrite')
    return {'schema_version': 1, 'kind': 'dbt_feature_candidates', 'selection': selected,
            'features': features, 'files': files, 'execution_performed': False,
            'assurance': 'Reviewable candidates only; no source edits, feature enablement, native validation or authorization.',
            'required_reviews': ['Review metadata-check scope and merge collisions.',
                                 'Keep independent data, security and business acceptance tests.',
                                 'Qualify selected features before using them in an execution request.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--distribution', required=True, choices=('dbt_core', 'dbt', 'dbt_oss'))
    parser.add_argument('--version', required=True)
    parser.add_argument('--warehouse')
    parser.add_argument('--feature', action='append', default=[])
    args = parser.parse_args()
    result = prepare_features({'distribution': args.distribution, 'version': args.version,
                               'features': args.feature}, args.warehouse)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
