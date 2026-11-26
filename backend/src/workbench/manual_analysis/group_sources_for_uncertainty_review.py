"""Divide extracted manual text into manageable portions for checking unclear
instructions.

The portions retain reading order and original passage references. Long passages
use overlapping text so a boundary is less likely to hide needed context. This
file prepares text only; it does not contact an AI or decide whether it is clear."""

from workbench.manual_analysis.check_source_quotations import evidence_payload

SOURCE_BYTES = 10_000


def build_batches(items: list[dict]) -> list[list[dict]]:
    """Keep each serialized evidence batch near a fixed byte allowance.

    Args:
        items: Original parsed source records, in reading order.
    Returns:
        Ordered text/table batches; long items are split with 100-character overlap.
        Every non-picture source character is included; no remote calls occur.
    """
    fragments = []
    for item in items:
        if not item["text"].strip() or item["label"] == "picture":
            continue
        # 1,600 Unicode characters fit in 6,400 UTF-8 bytes even for four-byte text.
        if len(evidence_payload([item]).encode("utf-8")) > SOURCE_BYTES:
            for offset in range(0, len(item["text"]), 1500):
                fragments.append(
                    {
                        **item,
                        "text": item["text"][offset : offset + 1600],
                        "source_offset": offset,
                    }
                )
        else:
            fragments.append(item)
    batches, current = [], []
    for item in fragments:
        if (
            current
            and len(evidence_payload(current + [item]).encode("utf-8")) > SOURCE_BYTES
        ):
            batches.append(current)
            current = []
        current.append(item)
    if current:
        batches.append(current)
    return batches
