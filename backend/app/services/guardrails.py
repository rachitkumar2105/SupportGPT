"""Lightweight input guardrails.

* Payment-card numbers (Luhn-valid 13-19 digit runs) are masked before a
  message is stored or sent to the LLM. Support chats are a classic place for
  customers to paste card numbers; we never want them in logs or prompts.
* Obvious prompt-injection phrasing is flagged (not blocked) so it shows up in
  analytics, and the system prompt treats retrieved text strictly as data.
"""

from __future__ import annotations

import re

_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_INJECTION = re.compile(
    r"(ignore|disregard|forget)\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier)\s+(instructions|rules|prompts?)"
    r"|(reveal|print|show|repeat)\s+(me\s+)?(your|the)\s+(system\s+prompt|instructions|hidden)"
    r"|you\s+are\s+now\s+(?:in\s+)?(dan|developer mode|jailbreak)"
    r"|act\s+as\s+(an?\s+)?(unrestricted|unfiltered)",
    re.I,
)


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def mask_cards(text: str) -> tuple[str, int]:
    count = 0

    def repl(m: re.Match) -> str:
        nonlocal count
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            count += 1
            return f"[card ending {digits[-4:]}]"
        return m.group(0)

    return _CARD.sub(repl, text), count


def looks_like_injection(text: str) -> bool:
    return bool(_INJECTION.search(text))
