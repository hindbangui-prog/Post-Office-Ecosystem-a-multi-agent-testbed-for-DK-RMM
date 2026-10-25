"""
The part of a model's reply that is its answer, without its hidden reasoning.

Three shapes reach this project:

- a complete ``<think>...</think>`` block before the answer (hybrid qwen3
  with thinking on);
- only the closing ``</think>`` (thinking-only models such as
  qwen3:4b-thinking-2507, whose chat template opens the block itself), so
  everything before the last closing tag is reasoning;
- an opening ``<think>`` that is never closed (a reply cut off at the token
  budget mid-thought), so nothing after it is answer.

A reply cut off inside reasoning that carries no tag at all cannot be told
apart from an answer here; it simply contains no answer, which the parsers
downstream already treat as such.
"""

from __future__ import annotations

import re

_BLOCK = re.compile(r"<think>.*?</think>", re.S | re.I)
_CLOSE = "</think>"
_OPEN = "<think>"


def visible(text: object) -> str:
    """The reply with every form of hidden reasoning removed, trimmed."""
    out = _BLOCK.sub("", str(text or ""))
    closing = out.lower().rfind(_CLOSE)
    if closing != -1:
        out = out[closing + len(_CLOSE):]
    opening = out.lower().find(_OPEN)
    if opening != -1:
        out = out[:opening]
    return out.strip()
