"""Keep the section headings that explain which instructions a manual passage belongs
to.

A heading may carry a condition or warning needed to understand the text below it.
These helpers use the complete document's order to retain the actual heading and
its source reference, rather than guess from a similar title. Retaining a heading
does not mean the reader must repeat a section label as an action."""

import copy


def bind_heading_sources(items):
    """Attach original heading IDs using the parser's complete ordered ancestry.

    Args:
        items: Full original document records, in reading order.
    Returns:
        Copied records with governing heading IDs. Inconsistent recorded ancestry
        raises ValueError; parser layout correctness remains unverified. Older
        records without section metadata retain no inferred heading dependencies.
    """
    output, stack = [], []
    for original in items:
        item = copy.deepcopy(original)
        if 'section' not in item:
            item['section_source_ids'] = []
            output.append(item)
            continue
        section = item['section']
        if item.get('label') in {'title', 'section_header'}:
            if not section or section[-1] != item['text']:
                raise ValueError('Heading does not match its recorded ancestry')
            parent = stack[:len(section) - 1]
            if [h['text'] for h in parent] != section[:-1]:
                raise ValueError('Missing heading ancestor in full source order')
            stack = parent + [item]
        if [h['text'] for h in stack] != section:
            raise ValueError('Source ancestry does not match full document order')
        item['section_source_ids'] = [h['id'] for h in stack]
        output.append(item)
    return output


def retain_heading_sources(sources, document=None):
    """Keep exact heading records available for evidence review and corrections.

    Args:
        sources: Selected original passages, possibly windows of larger records.
        document: Complete parsed document when called by production planning.
            Without it, only pre-bound explicit dependencies can be resolved.
    Returns:
        Copied passages plus missing governing heading records, retaining original
        text/IDs/pages. With full geometry, possible cross-column sentence context
        is retained as separate originals before heading resolution. Missing or inconsistent references fail
        closed. Does not edit documents, checkpoints or model-authored content.
    """
    if document is not None:
        from workbench.document_search.retain_original_column_context import retain_original_column_context

        sources, _ = retain_original_column_context(sources, document)
    records = bind_heading_sources(document['items']) if document is not None else copy.deepcopy(sources)
    by_id = {s['id']: s for s in records}
    positions = {s['id']: i for i, s in enumerate(records)}
    selected = copy.deepcopy(sources)
    for source in selected:
        if source['id'] not in by_id:
            raise ValueError('Review source is absent from the original document')
        original = by_id[source['id']]
        if document is not None and source['text'] not in original['text']:
            raise ValueError('Review source window differs from original text')
        if document is not None:
            source['section_source_ids'] = list(original.get('section_source_ids', []))
            source['section'] = list(original.get('section', []))
            source['document_position'] = positions[source['id']]
    present = {s['id'] for s in selected}
    for source in list(selected):
        for hid in source.get('section_source_ids', []):
            heading = by_id.get(hid)
            if heading is None or heading.get('label') not in {'section_header', 'title'}:
                raise ValueError('Missing original governing heading record')
            if hid not in present:
                selected.append({**copy.deepcopy(heading), 'document_position': positions[hid]})
                present.add(hid)
    return selected
