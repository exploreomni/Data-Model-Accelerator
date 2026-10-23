#!/usr/bin/env python3
"""Finalize selected review files as one verified ZIP and extracted handoff.

No model generation, source execution, native validation or approval is implied.
Existing partial exports remain available through delivery_portal.py package.
"""
import argparse
import copy
import json
from pathlib import Path
import sys
import tempfile
import zipfile

from ae_common import load_json, require
import delivery_portal as portal
import delivery_transfer as transfer

_directory_identity = transfer.directory_identity
_remove_owned_directory = transfer.remove_owned_directory


def check_selected_delivery(state, review, audience, include, manifest):
    """Require actual selected deliverables, not just requested category labels."""
    selected = set(include)
    files = manifest['files']
    counts = {category: sum(row.get('category') == category and row.get('bytes', 0) > 0 for row in files)
              for category in sorted(selected)}
    missing = [category for category, count in counts.items() if not count]
    require(not missing, 'Selected deliverables are missing: ' + ', '.join(missing)
            + '. Generate/register the requested files, or record an explicit smaller delivery selection; do not claim completion.')
    require(sum(row['path'] == 'START_HERE.html' for row in files) == 1,
            'Final handoff requires exactly one root START_HERE.html.')
    coverage = manifest.get('topic_coverage')
    semantic_id = review.get('omni', {}).get('artifact_id')
    # Manifest rows use paths rather than artifact IDs. Match the registered
    # semantic review against its category/layout destination.
    semantic_artifact = next((a for a in review.get('artifacts', []) if a['id'] == semantic_id), None)
    if semantic_artifact and any(row['path'].endswith('/' + semantic_artifact['path']) for row in files):
        require(coverage is not None, 'Selected Omni review is missing topic coverage. Repackage the semantic evidence.')
    if coverage:
        # A visible unbound topic is a reviewable candidate. A missing topic is
        # an incomplete package, never a reason to suppress provisional code.
        require(coverage.get('status') != 'failed',
                'Topic coverage is incomplete or inconsistent. Restore every selected topic join tree; '
                'provisional files can still be exported as an incomplete checkpoint.')
    if 'implementation' in selected:
        from deliverable_contract import check_packaged_code
        check_packaged_code(state, manifest)
    from package_layout import SECTIONS
    design_folder = SECTIONS['design'][0] if manifest.get('package_layout_version') == 2 else '01_Model'
    design_selected = bool(selected & {'documentation', 'diagrams', 'dictionary'}) and audience != 'audit'
    if design_selected:
        require(review.get('models'), 'Selected model review has no models. Supply the current design inventory.')
        canonical = state.get('workflow', {}).get('design') or {}
        if 'entities' in canonical:
            require({row['id'] for row in canonical['entities']} == {row['id'] for row in review['models']},
                    'Review model coverage differs from the current design. Restore every scoped entity before finalizing.')
            if canonical.get('schema_version') == 1:
                from design_consistency import compare_review
                differences = [row for row in compare_review(canonical, review)['findings']
                               if row['code'].startswith('review_')]
                require(not differences, 'Review content differs from the canonical design: '
                        + ', '.join(sorted({row['code'] for row in differences}))
                        + '. Regenerate the projection or export an explicitly incomplete checkpoint.')
        require(any(row['path'].startswith(design_folder + '/') for row in files),
                'Selected design deliverables are missing from ' + design_folder + '/.')
        if 'documentation' in selected:
            identifier = review.get('handoff', {}).get('design_artifact_id')
            artifact = next((row for row in review.get('artifacts', []) if row['id'] == identifier), None)
            require(artifact is not None and any(row['path'] == design_folder + '/' + artifact['path']
                    and row.get('bytes', 0) > 0 for row in files),
                    'Selected documentation requires the maintained design narrative: register handoff.design_artifact_id for this audience.')
    return counts


def finalize_delivery(state, review, artifact_root, output=None, audience=None, include=None, javascript=False, *,
                      checkpoint=False, working_dir=None, protected_roots=()):
    """In-process callers must refresh state first, as with the existing exporter.

    Build and check in private local storage, then copy to a new output version.
    A verified build survives transfer failure and can be retried without source
    access or generation. Prior exports are immutable; receipts stay private.
    """
    artifact_root = portal._path(artifact_root)
    output = transfer.validate_destination(output if output is not None else
                                           state.get('answers', {}).get('delivery_destination'), state, artifact_root)
    require(not output.exists(), 'Final delivery already exists; choose a new versioned output directory.')
    protected = transfer.protected_paths(state, artifact_root, protected_roots)
    transfer._separate(output, protected)
    audience = audience or state.get('answers', {}).get('audience') or 'engineer'
    include = portal.resolve_selection(state, audience, include)
    from delivery_preflight import assess as preflight, completion
    delivery_preflight = preflight(state, review, artifact_root, audience, include)
    require(not delivery_preflight['issues'], 'Delivery preflight needs attention: '
            + ', '.join(sorted({row['code'] for row in delivery_preflight['issues']}))
            + '. Resolve these delivery issues before finalization; provisional authoring remains available.')
    if not checkpoint and 'implementation' in include and state.get('workflow', {}).get('tasks'):
        # A caller may pass a saved engagement. Recheck current source and
        # artifact bindings instead of trusting an earlier reusable-task plan.
        from engagement_stages import plan_tasks
        state = copy.deepcopy(state)
        state['workflow']['last_plan'] = plan_tasks(state, artifact_root)
    work = transfer.local_work_directory(working_dir, protected, output)
    work_identity = _directory_identity(work)
    staging = Path(tempfile.mkdtemp(prefix='.dma-handoff-', dir=work))
    staging_identity = _directory_identity(staging)
    local_verified = False

    def check_local():
        require(_directory_identity(work) == work_identity
                and _directory_identity(staging) == staging_identity,
                'Delivery staging directory changed during generation.')

    try:
        archive_path = staging / 'handoff.zip'
        if checkpoint:
            manifest = portal.package_delivery(state, review, artifact_root, archive_path, audience, include, checkpoint=True)
        else:
            manifest = portal.package_delivery(state, review, artifact_root, archive_path, audience, include)
        integrity = portal.verify_delivery(archive_path)
        counts = ({category: sum(row.get('category') == category and row.get('bytes', 0) > 0 for row in manifest['files'])
                   for category in include} if checkpoint else check_selected_delivery(state, review, audience, include, manifest))
        page_check = portal.check_page(archive_path, javascript=javascript)
        check_local()
        handoff = staging / 'handoff'
        handoff.mkdir()
        # Only extract the archive just generated and verified above. Never use
        # extractall on an unverified customer archive or overwrite prior files.
        with zipfile.ZipFile(archive_path) as archive:
            for name in archive.namelist():
                check_local()
                destination = portal._path(handoff / portal._relative(name))
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open('xb') as stream:
                    stream.write(archive.read(name))
        check_local()
        design_folder = '03_Design_Documents' if manifest.get('package_layout_version') == 2 else '01_Model'
        from migration_intent import summary as migration_summary
        from migration_artifacts import summary as artifact_summary
        result = {'status': 'checkpoint_verified' if checkpoint else 'handoff_verified',
                'completion': completion(state, checkpoint), 'preflight': delivery_preflight,
                'entrypoint': str(staging / 'handoff' / 'START_HERE.html'),
                'zip': str(staging / 'handoff.zip'), 'folder': str(staging / 'handoff'),
                'design_folder': str(staging / 'handoff' / design_folder) if any(
                    row['path'].startswith(design_folder + '/') for row in manifest['files']) else None,
                'migration_intent': migration_summary(state),
                'legacy_retention_observations': artifact_summary(state),
                'selected_deliverable_counts': counts, 'integrity': integrity,
                'topic_coverage': manifest.get('topic_coverage'),
                'page_check': page_check, 'browser_review': 'not_performed_by_finalizer',
                'qualification': ('Checkpoint integrity only; selected deliverables may be missing and work remains incomplete.' if checkpoint else
                                  'Selected-file completeness and package integrity only; not model correctness, native validation, business approval or deployment.')}
        transfer.save_local_receipt(staging, result, output, protected)
        check_local()
        local_verified = True
        return transfer.transfer_delivery(staging, output)
    finally:
        if not local_verified:
            _remove_owned_directory(staging, staging_identity)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state')
    parser.add_argument('--review')
    parser.add_argument('--artifacts')
    parser.add_argument('--output', help='Exact new version directory; omission uses saved delivery_destination.')
    parser.add_argument('--working-dir', help='Private local build cache (0700), separate from source/candidate/destination.')
    parser.add_argument('--transfer-from', help='Retry a verified local build directory; no state, review or source access needed.')
    parser.add_argument('--audience', choices=sorted(portal.AUDIENCES))
    parser.add_argument('--include', help='Explicit comma-separated subset; omission uses saved selections.')
    parser.add_argument('--javascript', action='store_true', help='Also syntax-check the emitted scripts with Node.')
    parser.add_argument('--layout', choices=('simple', 'classic'), default='simple', help='New handoffs use five readable folders; classic preserves older registered document paths.')
    parser.add_argument('--checkpoint', action='store_true', help='Export interrupted work with explicit missing categories; never a completed handoff.')
    args = parser.parse_args(argv)
    try:
        if args.transfer_from:
            require(not any((args.state, args.review, args.artifacts, args.working_dir, args.audience,
                             args.include is not None, args.javascript, args.checkpoint, args.layout != 'simple')),
                    'Transfer retry accepts only --transfer-from and optional --output; finalize a new build to change contents.')
            print(json.dumps(transfer.transfer_delivery(args.transfer_from, args.output), indent=2))
            return 0
        require(all((args.state, args.review, args.artifacts)),
                'Supply --state, --review and --artifacts, or use --transfer-from to retry a verified build.')
        from guided_workflow import assess_engagement
        state_path = portal._path(args.state)
        require(state_path.name == 'state.json', 'Use the saved engagement state.json.')
        state = assess_engagement(state_path.parent)
        output = transfer.validate_destination(args.output if args.output is not None else
                                               state.get('answers', {}).get('delivery_destination'))
        require(output != state_path.parent and state_path.parent not in output.parents
                and output not in state_path.parent.parents, 'Keep the final handoff separate from the engagement work directory.')
        review = load_json(args.review)
        review['package_layout_version'] = 2 if args.layout == 'simple' else 1
        result = finalize_delivery(state, review, args.artifacts, output, args.audience,
                                   args.include.split(',') if args.include is not None else None, args.javascript,
                                   checkpoint=args.checkpoint, working_dir=args.working_dir,
                                   protected_roots=(state_path.parent,))
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, ImportError, zipfile.BadZipFile) as error:
        if getattr(error, 'delivery_result', None):
            print(json.dumps(error.delivery_result, indent=2))
        print('Handoff incomplete: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
