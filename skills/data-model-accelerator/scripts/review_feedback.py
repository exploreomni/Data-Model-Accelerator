"""Check offline review feedback against the current page. Never records approval or edits a model."""
import argparse
import hashlib
import json
from pathlib import Path

from ae_common import require
from portal_checks import parse_page, validate_page


def verify_feedback(page, response):
    """Require exact snapshots and canonical IDs; v1 table feedback remains valid."""
    parser, data = parse_page(page)
    partitioned = data.get('kind') == 'partitioned_review'
    if partitioned:
        from portable_site import check_page
        check_page(page)
    else:
        validate_page(page)
    # parse_page uses the same HTMLParser text as the browser's JSON script node.
    raw = next(script['source'] for script in parser.scripts if script['attrs'].get('id') == 'delivery-data')
    fields = {
        'schema_version', 'kind', 'request_only', 'engagement_id', 'context_sha256',
        'page_data_sha256', 'comments'}
    require(isinstance(response, dict), 'Feedback must be an object')
    version = response.get('schema_version')
    require(type(version) is int and version in (1, 2), 'Unsupported feedback schema version')
    if version == 2:
        fields.add('review_page_data_sha256')
    require(set(response) == fields, 'Feedback has unknown or missing fields')
    require(response['kind'] == 'model_review_feedback'
            and response['request_only'] is True, 'Feedback must be a request, never an approval')
    eng = data['engagement']
    require(response['engagement_id'] == eng['engagement_id']
            and response['context_sha256'] == eng.get('context_sha256')
            and isinstance(response['context_sha256'], str) and len(response['context_sha256']) == 64
            and response['page_data_sha256'] == hashlib.sha256(raw.encode()).hexdigest(),
            'Feedback is stale or belongs to another page. Refresh and reconcile the comments with the reviewer.')
    if version == 2:
        presentation = [s['source'] for s in parser.scripts if s['attrs'].get('id') == 'review-page-data']
        require(len(presentation) <= 1, 'Page has ambiguous review presentation data')
        expected = hashlib.sha256(presentation[0].encode()).hexdigest() if presentation else None
        require(response['review_page_data_sha256'] == expected,
                'Feedback refers to another review presentation. Refresh and reconcile the comments with the reviewer.')
    rows = response['comments']
    require(isinstance(rows, list) and 0 < len(rows) <= 100, 'Feedback needs 1–100 comments')
    ids = {m['id'] for m in (data.get('models', []) if partitioned else data.get('review', {}).get('models', []))}
    # Use the producer's checked inventory, not inferred names in a renderer.
    topics = {t['id'] for t in (data.get('topic_diagrams', []) if partitioned else
                              (data.get('review', {}).get('topic_join_trees') or {}).get('topics', []))}
    for row in rows:
        comment_fields = {'model_id', 'type', 'text'} | ({'topic_id'} if version == 2 else set())
        require(isinstance(row, dict) and set(row) == comment_fields, 'Invalid comment fields')
        require(row['model_id'] is None or isinstance(row['model_id'], str) and row['model_id'] in ids,
                'Feedback refers to a table outside this review')
        if version == 2:
            require(row['topic_id'] is None or isinstance(row['topic_id'], str) and row['topic_id'] in topics,
                    'Feedback refers to a topic outside this review')
            require(row['model_id'] is None or row['topic_id'] is None,
                    'A comment must select a table or a topic, not both')
        require(row['type'] in ('change_request', 'question'), 'Feedback type is not a supported request')
        require(isinstance(row['text'], str) and 0 < len(row['text'].strip()) <= 10000, 'Feedback text is empty or too long')
    return {'status': 'current_feedback_request', 'comments': rows, 'request_only': True,
            'qualification': 'Snapshot integrity only; reviewer identity, design approval and deployment authority are not established. The host reviews comments as data.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--page', required=True)
    parser.add_argument('--responses', required=True)
    args = parser.parse_args()
    path = Path(args.responses)
    require(path.stat().st_size <= 2 * 1024 * 1024, 'Feedback file exceeds the size limit')
    print(json.dumps(verify_feedback(Path(args.page).read_bytes(), json.loads(path.read_text())), indent=2))


if __name__ == '__main__':
    main()
