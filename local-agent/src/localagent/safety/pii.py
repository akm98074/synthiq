"""Find and redact personal data and secrets in text (logs, exports).

Deterministic patterns, no model: what it finds is explainable, and it runs on any machine.
It errs towards flagging; it can't recognise every name or address, so the export also says
what it does not cover.

Redaction replaces each distinct value with a stable token (`<EMAIL_3>`): the same address is
always `<EMAIL_3>` in one export, so a reviewer can still follow who got what without seeing it.
"""
from __future__ import annotations

import re
from collections import Counter

# Secrets first: they must win over the generic patterns that could also match them.
SECRET_PATTERNS = {
    "API_KEY": r"\b(?:sk-ant-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{30,}"
               r"|xox[abposr]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{35}|ya29\.[0-9A-Za-z_-]{20,})\b",
    "JWT": r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b",
    "PRIVATE_KEY": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "PASSWORD": r"(?i)\b(?:password|passwd|passcode|pwd)\s*[:=]\s*\S+",
}
PII_PATTERNS = {
    "EMAIL": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "CARD": r"\b(?:\d[ -]?){13,19}\b",
    "SSN": r"\b\d{3}-\d{2}-\d{4}\b",
    "IBAN": r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b",
    # Needs a separator or a leading +, so bare 10-digit numbers (timestamps, ids) aren't phones.
    "PHONE": r"(?<![\w.])(?:\+\d{1,3}[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]?\d{4}(?![\w])|(?<![\w.])\+\d{10,14}(?![\w])",
    "IP": r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b",
    "STREET_ADDRESS": r"\b\d{1,5}\s+(?:[A-Z][a-z]+\s){1,3}(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Lane|Ln|Dr|Drive|Way|Ct|Court|Pl|Place)\b\.?",
}
SECRET_KINDS = set(SECRET_PATTERNS)
_COMPILED = [(k, re.compile(p)) for k, p in {**SECRET_PATTERNS, **PII_PATTERNS}.items()]
LOCAL_IPS = ("127.", "0.0.0.0", "10.", "192.168.")


def luhn(digits: str) -> bool:
    nums = [int(c) for c in digits if c.isdigit()]
    if not 13 <= len(nums) <= 19:
        return False
    total = 0
    for i, n in enumerate(reversed(nums)):
        if i % 2:
            n *= 2
            n -= 9 if n > 9 else 0
        total += n
    return total % 10 == 0


def _keep(kind: str, value: str) -> bool:
    if kind == "CARD":
        return luhn(value)
    if kind == "IP":
        return not value.startswith(LOCAL_IPS)
    if kind == "PHONE":
        return sum(c.isdigit() for c in value) >= 10
    return True


def find(text: str, names: list[str] | None = None) -> list[tuple[str, str, int, int]]:
    """[(kind, value, start, end)] non-overlapping, secrets first, then PII, then known names."""
    if not text:
        return []
    taken: list[tuple[int, int]] = []
    out = []

    def free(a: int, b: int) -> bool:
        return all(b <= x or a >= y for x, y in taken)

    for kind, rx in _COMPILED:
        for m in rx.finditer(text):
            v = m.group(0)
            if _keep(kind, v) and free(m.start(), m.end()):
                taken.append((m.start(), m.end()))
                out.append((kind, v, m.start(), m.end()))
    for name in names or []:
        if len(name) < 3:
            continue
        for m in re.finditer(rf"\b{re.escape(name)}\b", text):
            if free(m.start(), m.end()):
                taken.append((m.start(), m.end()))
                out.append(("NAME", m.group(0), m.start(), m.end()))
    return sorted(out, key=lambda x: x[2])


def count(text: str, names: list[str] | None = None) -> Counter:
    return Counter(kind for kind, *_ in find(text, names))


class Redactor:
    """Stable tokens across a whole export."""

    def __init__(self, names: list[str] | None = None):
        self.names = names or []
        self.tokens: dict[tuple[str, str], str] = {}
        self.per_kind: Counter = Counter()

    def token(self, kind: str, value: str) -> str:
        key = (kind, value.lower())
        if key not in self.tokens:
            self.per_kind[kind] += 1
            self.tokens[key] = f"<{kind}_{self.per_kind[kind]}>"
        return self.tokens[key]

    def text(self, text: str) -> str:
        if not text:
            return text
        out, last = [], 0
        for kind, value, a, b in find(text, self.names):
            out.append(text[last:a])
            out.append(self.token(kind, value))
            last = b
        out.append(text[last:])
        return "".join(out)

    def value(self, v):
        """Redact strings inside any JSON-like value."""
        if isinstance(v, str):
            return self.text(v)
        if isinstance(v, list):
            return [self.value(x) for x in v]
        if isinstance(v, dict):
            return {k: self.value(x) for k, x in v.items()}
        return v
