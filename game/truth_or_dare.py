"""Truth or Dare cards are truths or dares. The owner-approved rule that split
the question bank (game migration 0008, which keeps its own copy) also
classifies new custom questions added without a kind."""

import re

TRUTH, DARE = "truth", "dare"
KINDS = [(TRUTH, "Truth"), (DARE, "Dare")]
MODE = "truth"  # The Truth or Dare mode's value in Question.MODES.

_PREFIX = re.compile(r"^\s*(truth|dare)\s*[:\-]\s*", re.IGNORECASE)
_SPOKEN = re.compile(r"^(tell|describe|share)\b", re.IGNORECASE)


def classify(text):
    """An explicit "Truth:"/"Dare:" prefix wins; then any "?" makes a truth;
    "Tell/Describe/Share..." prompts are answered aloud, so truths; any
    other prompt is something to do, so a dare."""
    text = text.strip()
    prefix = _PREFIX.match(text)
    if prefix:
        return prefix.group(1).lower()
    if "?" in text or _SPOKEN.match(text):
        return TRUTH
    return DARE


def display_text(text):
    """The card text without its "Truth:"/"Dare:" prefix (the card shows the
    kind itself). Stored text keeps the prefix."""
    return _PREFIX.sub("", text, count=1).strip() or text
