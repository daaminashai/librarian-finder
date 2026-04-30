"""Candidate ranking and confidence scoring."""

from __future__ import annotations

from .config import ScraperConfig
from .matcher import RoleMatcher
from .models import ContactCandidate, SchoolInput
from .utils import email_domain_matches


class CandidateRanker:
    """Choose the best librarian/media specialist candidate for one school."""

    def __init__(self, config: ScraperConfig, matcher: RoleMatcher) -> None:
        self.config = config
        self.matcher = matcher

    def best(self, school: SchoolInput, candidates: list[ContactCandidate]) -> ContactCandidate | None:
        """Return the highest-confidence candidate above the no-match threshold."""

        scored = []
        for candidate in self._dedupe(candidates):
            candidate.confidence = self.score(school, candidate)
            if candidate.confidence >= self.config.no_match_threshold:
                scored.append(candidate)
        if not scored:
            return None
        return max(scored, key=lambda candidate: candidate.confidence)

    def score(self, school: SchoolInput, candidate: ContactCandidate) -> float:
        """Calculate a confidence score from role, page, and contact signals."""

        title_score = self.matcher.score(candidate.title)
        context_score = self.matcher.score(candidate.context) * 0.85
        role_score = max(title_score, context_score)
        if role_score < 0.40:
            return 0.0

        score = 0.08 + role_score * 0.55
        score += self.config.source_kind_weights.get(candidate.source_kind, 0.0)
        if candidate.email:
            score += 0.12
            if email_domain_matches(candidate.email, school.domain or school.website):
                score += 0.04
        if candidate.name:
            score += 0.04 if candidate.signals.get("name_from_email") else 0.08

        title_lower = (candidate.title or "").lower()
        context_lower = (candidate.context or "").lower()
        combined = f"{title_lower} {context_lower}"
        if any(keyword in combined for keyword in self.config.senior_role_keywords):
            score += 0.06
        if any(keyword in title_lower for keyword in self.config.assistant_role_keywords):
            score -= 0.05
        if self.matcher.exact_matches(candidate.title):
            score += 0.04

        return max(0.0, min(score, 1.0))

    def _dedupe(self, candidates: list[ContactCandidate]) -> list[ContactCandidate]:
        best_by_key: dict[str, ContactCandidate] = {}
        for candidate in candidates:
            key = candidate.dedupe_key()
            existing = best_by_key.get(key)
            if not existing:
                best_by_key[key] = candidate
                continue
            candidate_quality = len(candidate.title) + len(candidate.name) + (20 if candidate.email else 0)
            existing_quality = len(existing.title) + len(existing.name) + (20 if existing.email else 0)
            if candidate_quality > existing_quality:
                best_by_key[key] = candidate
        return list(best_by_key.values())
