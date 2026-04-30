"""Fuzzy role matching for librarian/media specialist titles."""

from __future__ import annotations

import difflib
import re

from .config import ScraperConfig
from .utils import compact_text

try:
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover - runtime fallback when optional import is absent.
    fuzz = None


class RoleMatcher:
    """Scores text against configurable librarian/media role keywords."""

    anchor_terms = ("librarian", "library", "media")
    media_role_terms = (
        "specialist",
        "center",
        "coordinator",
        "librarian",
        "library",
        "teacher",
        "instructional",
        "assistant",
        "aide",
    )

    def __init__(self, config: ScraperConfig) -> None:
        self.config = config
        self.keywords = tuple(keyword.lower() for keyword in config.role_keywords)

    def score(self, text: str) -> float:
        """Return a normalized role relevance score from 0 to 1."""

        normalized = self._normalize(text)
        if not normalized:
            return 0.0
        if any(self._exact_keyword_match(normalized, keyword) for keyword in self.keywords):
            return 1.0

        best = 0.0
        for keyword in self.keywords:
            if not self._can_fuzzy_match(keyword, normalized):
                continue
            best = max(best, self._similarity(keyword, normalized))
            for window in self._windows(normalized, len(keyword.split()) + 2):
                if not self._can_fuzzy_match(keyword, window):
                    continue
                best = max(best, self._similarity(keyword, window))
        return min(best, 1.0)

    def exact_matches(self, text: str) -> list[str]:
        normalized = self._normalize(text)
        return [keyword for keyword in self.keywords if self._exact_keyword_match(normalized, keyword)]

    def has_role_signal(self, text: str, threshold: float = 0.72) -> bool:
        return self.score(text) >= threshold

    def _normalize(self, text: str) -> str:
        text = compact_text(text).lower()
        return re.sub(r"[^a-z0-9@.\s/-]", " ", text)

    def _exact_keyword_match(self, text: str, keyword: str) -> bool:
        pattern = r"(?<![a-z])" + re.escape(keyword).replace(r"\ ", r"\s+") + r"(?![a-z])"
        return bool(re.search(pattern, text))

    def _similarity(self, keyword: str, text: str) -> float:
        if fuzz:
            return max(
                fuzz.partial_ratio(keyword, text),
                fuzz.token_sort_ratio(keyword, text),
            ) / 100.0
        return difflib.SequenceMatcher(a=keyword, b=text).ratio()

    def _can_fuzzy_match(self, keyword: str, text: str) -> bool:
        if not any(term in keyword for term in self.anchor_terms):
            return True
        if "librarian" in keyword and not re.search(r"(?<![a-z])librar(?:ian|y)(?![a-z])", text):
            return False
        if "library" in keyword and not re.search(r"(?<![a-z])librar(?:ian|y)(?![a-z])", text):
            return False
        if "media" in keyword and "media" in text:
            return any(re.search(rf"(?<![a-z]){re.escape(term)}(?![a-z])", text) for term in self.media_role_terms)
        if "media" in keyword:
            return False
        if not self._has_anchor(text):
            return False
        return True

    def _has_anchor(self, text: str) -> bool:
        return any(re.search(rf"(?<![a-z]){re.escape(term)}(?![a-z])", text) for term in self.anchor_terms)

    def _windows(self, text: str, size: int) -> list[str]:
        words = text.split()
        if len(words) <= size:
            return [text]
        return [" ".join(words[index : index + size]) for index in range(0, len(words) - size + 1)]
