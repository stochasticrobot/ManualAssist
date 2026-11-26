"""Read an AI's structured reply without guessing what a broken answer meant.

The application expects named fields in JSON text. A complete Markdown wrapper can
be removed, but missing fields, cut-off text and unrelated prose are not silently
repaired. This keeps a readable-looking answer from hiding lost content."""

import json
import re


def read_json(text: str):
    """Read a JSON reply, allowing one complete Markdown code block around it.

    Args:
        text: Full model reply, possibly with surrounding whitespace or a json code fence.
    Returns:
        The parsed JSON value with its original fields and values. Malformed JSON or
        extra prose raises ValueError; no missing content is supplied by this function."""
    text = text.strip()
    match = re.fullmatch(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    return json.loads(match.group(1) if match else text)
