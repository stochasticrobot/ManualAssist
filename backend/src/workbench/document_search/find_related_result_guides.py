"""Find saved guides that may help with a reader's question.

Matching words in guide titles and instructions lets the answer screen offer a
shortcut to an installation, maintenance or troubleshooting guide. This is a local
text comparison, not another AI request or proof that the suggested guide solves
the reader's problem."""

import re

STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "how",
    "what",
    "does",
    "have",
    "can",
    "you",
    "my",
    "a",
    "to",
    "is",
    "it",
    "not",
    "i",
    "do",
    "of",
    "in",
    "on",
}


def search_words(text):
    """Normalize common task words so natural questions can find named procedures.

    Args:
        text: User question or saved guide text; never executed as instructions.
    Returns:
        Distinct lowercase words with a few explicit task-word families normalized.
        This is not semantic search; unrecognized synonyms may still miss a guide.
    """
    words = set(re.findall(r"[a-z0-9]+", text.casefold())) - STOP_WORDS
    return {
        next(
            (
                root
                for root in ("install", "maintain", "clean", "drain", "leak", "start")
                if word.startswith(root)
            ),
            word,
        )
        for word in words
    }


def find_related_result_guides(profile, question, limit=5):
    """Rank guide and symptom links without using generated text as source evidence.

    Args:
        profile: Saved analysis profile, optionally containing procedure guides.
        question: Natural-language question or symptom description.
        limit: Maximum number of related navigation links returned, default five.
    Returns:
        Ranked ID/kind/title/status records. Empty or unmatched queries return no
        links. No files or model calls are made; scores are navigation hints only.
    """
    query = search_words(question)
    if not query:
        return []
    candidates = []
    for number, tree in enumerate(profile.get("troubleshooting", [])):
        candidates.append(
            {
                "id": f"tree-{number}",
                "kind": "troubleshooting",
                "title": tree["symptom"],
                "status": "source_checked",
                "body": " ".join(n["text"] for n in tree["nodes"]),
            }
        )
    for guide in profile.get("procedure_guides", []):
        if guide["status"] == "unfinished":
            continue
        body = " ".join(step["instruction"] for step in guide["steps"])
        body += " " + " ".join(check["instruction"] for check in guide.get("independent_checks", []))
        if guide.get("troubleshooting"):
            body += " ".join(n["text"] for n in guide["troubleshooting"]["nodes"])
        candidates.append(
            {
                "id": guide["id"],
                "kind": guide["kind"],
                "title": guide["title"],
                "status": guide["status"],
                "body": body,
            }
        )
    ranked = []
    for candidate in candidates:
        score = 4 * len(
            query & search_words(candidate["title"] + " " + candidate["kind"])
        ) + len(query & search_words(candidate["body"]))
        if score:
            ranked.append((score, {k: v for k, v in candidate.items() if k != "body"}))
    return [value for _, value in sorted(ranked, key=lambda entry: -entry[0])[:limit]]
