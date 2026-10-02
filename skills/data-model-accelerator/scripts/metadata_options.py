"""Non-executing discovery choices; a saved choice is never write authority."""
import copy


MODES = ('comments', 'comments_and_tags', 'documentation_only')


def validate_options(value):
    required = {'mode', 'raw_comments', 'source_ids', 'environments', 'owner',
                'taxonomy', 'tag_namespace', 'unknown_handling', 'decision_reference'}
    if type(value) is not dict or set(value) != required:
        raise ValueError('metadata_policy requires exactly: ' + ', '.join(sorted(required)))
    if value['mode'] not in MODES or type(value['raw_comments']) is not bool:
        raise ValueError('Choose a metadata mode and explicit RAW comment choice')
    if value['unknown_handling'] not in ('block', 'review_required'):
        raise ValueError('Unknown sensitivity must block or require review; never infer INTERNAL')
    for key in ('source_ids', 'environments', 'tag_namespace'):
        items = value[key]
        if (type(items) is not list or len(items) > 100 or
                not all(type(item) is str and item.strip() == item and 0 < len(item) <= 256 for item in items)
                or len(set(items)) != len(items)):
            raise ValueError('Invalid metadata ' + key)
    for key in ('owner', 'taxonomy', 'decision_reference'):
        item = value[key]
        if item is not None and (type(item) is not str or not item.strip() or len(item) > 4000):
            raise ValueError('Invalid metadata ' + key)
    if value['raw_comments'] and not value['source_ids']:
        raise ValueError('RAW comments require explicit source IDs')
    if value['mode'] == 'documentation_only' and value['raw_comments']:
        raise ValueError('Documentation-only selection cannot request RAW writes')
    if value['mode'] == 'comments_and_tags' and (not value['taxonomy'] or not value['tag_namespace']):
        raise ValueError('Governed tags require a taxonomy and exact tag namespace')
    return copy.deepcopy(value)


def validate_naming(value):
    if type(value) is not dict or set(value) != {'mode', 'domain', 'decision_reference'}:
        raise ValueError('naming_policy requires mode, domain and decision_reference')
    if value['mode'] not in ('preserve', 'type_domain', 'layer_domain'):
        raise ValueError('Unknown naming policy')
    for key in ('domain', 'decision_reference'):
        item = value[key]
        if item is not None and (type(item) is not str or not item.strip() or len(item) > 256):
            raise ValueError('Invalid naming ' + key)
    if value['mode'] != 'preserve' and (not value['domain'] or not value['decision_reference']):
        raise ValueError('Renaming requires an explicit domain and reviewed decision')
    return copy.deepcopy(value)
