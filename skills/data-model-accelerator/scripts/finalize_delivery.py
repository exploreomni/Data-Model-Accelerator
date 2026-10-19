#!/usr/bin/env python3
"""Finalize selected review files as one verified ZIP and extracted handoff.

No model generation, source execution, native validation or approval is implied.
Existing partial exports remain available through delivery_portal.py package.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

from ae_common import load_json, require
import delivery_portal as portal


def _directory_identity(path):
    portal._path(path)
    value = path.stat()
    require(path.is_dir(), 'Expected a delivery directory.')
    return value.st_dev, value.st_ino


def _remove_owned_directory(path, identity):
    # Do not delete a replacement directory after an interrupted local run.
    try:
        if _directory_identity(path) == identity:
            shutil.rmtree(path)
    except (OSError, ValueError):
        pass


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
        require(any(row['path'].startswith('01_Model/') for row in files),
                'Selected design deliverables are missing from 01_Model/.')
        if 'documentation' in selected:
            identifier = review.get('handoff', {}).get('design_artifact_id')
            artifact = next((row for row in review.get('artifacts', []) if row['id'] == identifier), None)
            require(artifact is not None and any(row['path'] == '01_Model/' + artifact['path']
                    and row.get('bytes', 0) > 0 for row in files),
                    'Selected documentation requires the maintained design narrative: register handoff.design_artifact_id for this audience.')
    return counts


def finalize_delivery(state, review, artifact_root, output, audience=None, include=None, javascript=False, *, checkpoint=False):
    """In-process callers must refresh state first, as with the existing exporter.

    Build and check in a temporary sibling, then publish a new output directory.
    Failure leaves no apparently finished handoff. Prior exports are immutable.
    """
    output, artifact_root = portal._path(output), portal._path(artifact_root)
    require(not output.exists(), 'Final delivery already exists; choose a new versioned output directory.')
    protected = [artifact_root]
    source = state.get('inputs', {}).get('source', {}).get('path')
    if source:
        protected.append(portal._path(source))
    for root in protected:
        require(output != root and root not in output.parents and output not in root.parents,
                'Final delivery must be separate from the source and candidate artifact directories.')
    audience = audience or state.get('answers', {}).get('audience') or 'engineer'
    include = portal.resolve_selection(state, audience, include)
    output.parent.mkdir(parents=True, exist_ok=True)
    parent_identity = _directory_identity(output.parent)
    def check_destination():
        portal._path(output)
        require(_directory_identity(output.parent) == parent_identity,
                'Delivery parent changed during generation; choose a stable output directory.')
        require(not output.exists(), 'Final delivery appeared during generation; choose a new output directory.')
    staging = Path(tempfile.mkdtemp(prefix='.dma-handoff-', dir=output.parent))
    staging_identity = _directory_identity(staging)
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
        check_destination()
        require(_directory_identity(staging) == staging_identity, 'Delivery staging directory changed during generation.')
        handoff = staging / 'handoff'
        handoff.mkdir()
        # Only extract the archive just generated and verified above. Never use
        # extractall on an unverified customer archive or overwrite prior files.
        with zipfile.ZipFile(archive_path) as archive:
            for name in archive.namelist():
                destination = handoff / portal._relative(name)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(name))
        actual = {str(path.relative_to(handoff)): path for path in handoff.rglob('*') if path.is_file()}
        require(set(actual) == {'DELIVERY_MANIFEST.json'} | {row['path'] for row in manifest['files']},
                'Extracted handoff inventory differs from the verified ZIP.')
        for row in manifest['files']:
            body = actual[row['path']].read_bytes()
            require(len(body) == row['bytes'] and portal._sha(body) == row['sha256'],
                    'Extracted handoff bytes differ: ' + row['path'])
        check_destination()
        require(_directory_identity(staging) == staging_identity, 'Delivery staging directory changed during generation.')
        # mkdir is exclusive, unlike rename(directory), which may overwrite an
        # empty directory created between an existence check and publication.
        output.mkdir(mode=0o700)
        output_identity = _directory_identity(output)
        try:
            os.rename(archive_path, output / 'handoff.zip')
            os.rename(handoff, output / 'handoff')
        except OSError:
            _remove_owned_directory(output, output_identity)
            raise
        return {'status': 'checkpoint_verified' if checkpoint else 'handoff_verified',
                'entrypoint': str(output / 'handoff' / 'START_HERE.html'),
                'zip': str(output / 'handoff.zip'), 'folder': str(output / 'handoff'),
                'design_folder': str(output / 'handoff' / '01_Model') if any(
                    row['path'].startswith('01_Model/') for row in manifest['files']) else None,
                'selected_deliverable_counts': counts, 'integrity': integrity,
                'page_check': page_check, 'browser_review': 'not_performed_by_finalizer',
                'qualification': ('Checkpoint integrity only; selected deliverables may be missing and work remains incomplete.' if checkpoint else
                                  'Selected-file completeness and package integrity only; not model correctness, native validation, business approval or deployment.')}
    finally:
        _remove_owned_directory(staging, staging_identity)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True)
    parser.add_argument('--review', required=True)
    parser.add_argument('--artifacts', required=True)
    parser.add_argument('--output', required=True, help='New versioned directory for handoff.zip and handoff/.')
    parser.add_argument('--audience', choices=sorted(portal.AUDIENCES))
    parser.add_argument('--include', help='Explicit comma-separated subset; omission uses saved selections.')
    parser.add_argument('--javascript', action='store_true', help='Also syntax-check the emitted scripts with Node.')
    parser.add_argument('--checkpoint', action='store_true', help='Export interrupted work with explicit missing categories; never a completed handoff.')
    args = parser.parse_args(argv)
    try:
        from guided_workflow import assess_engagement
        state_path = portal._path(args.state)
        require(state_path.name == 'state.json', 'Use the saved engagement state.json.')
        output = portal._path(args.output)
        require(output != state_path.parent and state_path.parent not in output.parents
                and output not in state_path.parent.parents, 'Keep the final handoff separate from the engagement work directory.')
        state = assess_engagement(state_path.parent)
        result = finalize_delivery(state, load_json(args.review), args.artifacts, output, args.audience,
                                   args.include.split(',') if args.include is not None else None, args.javascript,
                                   checkpoint=args.checkpoint)
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, ImportError, zipfile.BadZipFile) as error:
        print('Handoff incomplete: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
