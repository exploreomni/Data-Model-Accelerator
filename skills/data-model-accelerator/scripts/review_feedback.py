"""Check offline review feedback against the current page. Never records approval or edits a model."""
import argparse
import hashlib
import json
from pathlib import Path

from ae_common import require
from portal_checks import parse_page, validate_page


def verify_feedback(page, response):
    """Require exact page/context and existing table IDs before a host considers edits."""
    validate_page(page)
    parser, data = parse_page(page)
    # parse_page uses the same HTMLParser text as the browser's JSON script node.
    raw = next(script['source'] for script in parser.scripts if script['attrs'].get('id') == 'delivery-data')
    require(isinstance(response, dict) and set(response) == {
        'schema_version', 'kind', 'request_only', 'engagement_id', 'context_sha256',
        'page_data_sha256', 'comments'}, 'Feedback has unknown or missing fields')
    require(type(response['schema_version']) is int and response['schema_version'] == 1 and response['kind'] == 'model_review_feedback'
            and response['request_only'] is True, 'Feedback must be a request, never an approval')
    eng = data['engagement']
    require(response['engagement_id'] == eng['engagement_id']
            and response['context_sha256'] == eng.get('context_sha256')
            and isinstance(response['context_sha256'], str) and len(response['context_sha256']) == 64
            and response['page_data_sha256'] == hashlib.sha256(raw.encode()).hexdigest(),
            'Feedback is stale or belongs to another page. Refresh and reconcile the comments with the reviewer.')
    rows = response['comments']
    require(isinstance(rows, list) and 0 < len(rows) <= 100, 'Feedback needs 1–100 comments')
    ids = {m['id'] for m in data.get('review', {}).get('models', [])}
    for row in rows:
        require(isinstance(row, dict) and set(row) == {'model_id', 'type', 'text'}, 'Invalid comment fields')
        require(row['model_id'] is None or isinstance(row['model_id'], str) and row['model_id'] in ids,
                'Feedback refers to a table outside this review')
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
