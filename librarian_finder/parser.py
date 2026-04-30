"""HTML contact extraction heuristics."""

from __future__ import annotations

import re
from collections.abc import Iterable

from bs4 import BeautifulSoup, Tag

from .config import ScraperConfig
from .matcher import RoleMatcher
from .models import ContactCandidate, FetchedPage
from .utils import clean_email, compact_text, extract_emails, title_case_from_email


class PageParser:
    """Extract contact candidates from inconsistent school HTML pages."""

    def __init__(self, config: ScraperConfig, matcher: RoleMatcher) -> None:
        self.config = config
        self.matcher = matcher

    def parse(self, page: FetchedPage) -> list[ContactCandidate]:
        """Parse one fetched HTML page into structured contact candidates."""

        if not page.text or not page.is_html:
            return []

        soup = BeautifulSoup(page.text, "lxml")
        for node in soup(["script", "style", "noscript", "svg"]):
            node.decompose()

        candidates: list[ContactCandidate] = []
        candidates.extend(self._from_mailto_links(soup, page))
        candidates.extend(self._from_tables(soup, page))
        candidates.extend(self._from_cards_and_lists(soup, page))
        candidates.extend(self._from_text_windows(soup, page))
        return self._dedupe(candidates)

    def _from_mailto_links(self, soup: BeautifulSoup, page: FetchedPage) -> list[ContactCandidate]:
        candidates: list[ContactCandidate] = []
        for anchor in soup.find_all("a", href=True):
            email = clean_email(anchor.get("href", ""))
            if not email:
                continue
            context = self._container_text(anchor)
            name_hint = compact_text(anchor.get_text(" "))
            candidates.append(self._candidate_from_context(page, context, email=email, name_hint=name_hint))
        return candidates

    def _from_tables(self, soup: BeautifulSoup, page: FetchedPage) -> list[ContactCandidate]:
        candidates: list[ContactCandidate] = []
        for row in soup.find_all("tr"):
            cells = [compact_text(cell.get_text(" ")) for cell in row.find_all(["td", "th"])]
            cells = [cell for cell in cells if cell]
            if not cells:
                continue
            context = " | ".join(cells)
            if not extract_emails(context) and not self.matcher.has_role_signal(context, threshold=0.78):
                continue
            email = extract_emails(context)[0] if extract_emails(context) else ""
            name_hint = next((cell for cell in cells if self._is_plausible_name(cell)), "")
            title_hint = next((cell for cell in cells if self.matcher.has_role_signal(cell, threshold=0.72)), "")
            candidates.append(
                self._candidate_from_context(
                    page,
                    context,
                    email=email,
                    name_hint=name_hint,
                    title_hint=title_hint,
                )
            )
        return candidates

    def _from_cards_and_lists(self, soup: BeautifulSoup, page: FetchedPage) -> list[ContactCandidate]:
        selectors = (
            '[class*="staff"]',
            '[class*="directory"]',
            '[class*="faculty"]',
            '[class*="person"]',
            '[class*="employee"]',
            '[class*="profile"]',
            '[class*="card"]',
            "li",
            "article",
            "section",
        )
        candidates: list[ContactCandidate] = []
        seen_contexts: set[str] = set()
        for element in self._select_limited(soup, selectors, limit=900):
            context = compact_text(element.get_text(" | "))
            if not (25 <= len(context) <= 1_200):
                continue
            if context in seen_contexts:
                continue
            seen_contexts.add(context)
            if not extract_emails(context) and not self.matcher.has_role_signal(context, threshold=0.78):
                continue
            candidates.append(self._candidate_from_context(page, context))
        return candidates

    def _from_text_windows(self, soup: BeautifulSoup, page: FetchedPage) -> list[ContactCandidate]:
        lines = [compact_text(line) for line in soup.get_text("\n").splitlines()]
        lines = [line for line in lines if line]
        candidates: list[ContactCandidate] = []
        for index, line in enumerate(lines):
            if not self.matcher.has_role_signal(line, threshold=0.78):
                continue
            start = max(0, index - 3)
            end = min(len(lines), index + 4)
            context = " | ".join(lines[start:end])
            candidates.append(self._candidate_from_context(page, context, title_hint=line))
        return candidates

    def _candidate_from_context(
        self,
        page: FetchedPage,
        context: str,
        *,
        email: str = "",
        name_hint: str = "",
        title_hint: str = "",
    ) -> ContactCandidate:
        emails = extract_emails(context)
        email = email or (emails[0] if emails else "")
        inline_name, inline_title = self._extract_inline_name_title(context)
        title = inline_title or self._extract_title(context, title_hint=title_hint)
        name = inline_name or self._extract_name(context, email=email, name_hint=name_hint, title=title)
        signals = {"email_present": bool(email), "name_from_email": False}
        if not name and email:
            name = title_case_from_email(email)
            signals["name_from_email"] = bool(name)

        return ContactCandidate(
            name=name,
            title=title,
            email=email,
            source_url=page.final_url or page.url,
            source_kind=page.page_kind,
            context=compact_text(context)[:1_000],
            signals=signals,
        )

    def _extract_title(self, context: str, *, title_hint: str = "") -> str:
        if title_hint and self.matcher.has_role_signal(title_hint, threshold=0.65):
            return self._clean_title(title_hint)
        lines = self._context_lines(context)
        for line in lines:
            if self.matcher.has_role_signal(line, threshold=0.65):
                return self._clean_title(line)
        for line in lines:
            if re.search(r"\btitle\b|\brole\b|\bposition\b", line, re.IGNORECASE):
                return self._clean_title(line)
        return ""

    def _extract_name(self, context: str, *, email: str, name_hint: str, title: str) -> str:
        if self._is_plausible_name(name_hint):
            return self._clean_name(name_hint)
        lines = self._context_lines(context)
        email_line_index = -1
        if email:
            for index, line in enumerate(lines):
                if email in line.lower():
                    email_line_index = index
                    break

        ordered_lines = lines
        if email_line_index >= 0:
            start = max(0, email_line_index - 4)
            end = min(len(lines), email_line_index + 2)
            ordered_lines = lines[start:end] + lines[:start] + lines[end:]

        for line in ordered_lines:
            if title and compact_text(line).lower() == compact_text(title).lower():
                continue
            if self._is_plausible_name(line):
                return self._clean_name(line)
        return ""

    def _extract_inline_name_title(self, context: str) -> tuple[str, str]:
        """Split common directory rows like 'Jane Smith Librarian 23'."""

        for line in self._context_lines(context):
            line = compact_text(line)
            if not self.matcher.has_role_signal(line, threshold=0.72):
                continue
            patterns = (
                r"^(?P<name>[A-Z][A-Za-z'\-.]+(?:\s+[A-Z][A-Za-z'\-.]+){1,4})\s+(?P<title>Library\s+Media\s+Specialist|Media\s+Specialist|Teacher\s+Librarian|Librarian|Library\s+Assistant|Media\s+Aide|Library\s+Aide|Media\s+Coordinator|Library\s+Media\s+Coordinator)\b",
                r"^(?P<title>Library\s+Media\s+Specialist|Media\s+Specialist|Teacher\s+Librarian|Librarian|Library\s+Assistant|Media\s+Aide|Library\s+Aide|Media\s+Coordinator|Library\s+Media\s+Coordinator)\s+(?P<name>[A-Z][A-Za-z'\-.]+(?:\s+[A-Z][A-Za-z'\-.]+){1,4})\b",
            )
            for pattern in patterns:
                match = re.search(pattern, line)
                if match:
                    name = self._clean_name(match.group("name"))
                    title = self._clean_title(match.group("title"))
                    if self._is_plausible_name(name):
                        return name, title
        return "", ""

    def _context_lines(self, context: str) -> list[str]:
        parts = re.split(r"\s*[|\n•;]+\s*", context)
        return [compact_text(part) for part in parts if compact_text(part)]

    def _clean_title(self, title: str) -> str:
        title = compact_text(title)
        title = re.sub(r"^(title|role|position)\s*[:\-]\s*", "", title, flags=re.IGNORECASE)
        return title[:160].strip(" -|")

    def _clean_name(self, name: str) -> str:
        name = re.sub(r"^(name|contact)\s*[:\-]\s*", "", compact_text(name), flags=re.IGNORECASE)
        return name[:100].strip(" -|")

    def _is_plausible_name(self, value: str) -> bool:
        value = compact_text(value)
        if not 3 <= len(value) <= 80:
            return False
        lowered = value.lower()
        if "@" in value or any(char.isdigit() for char in value):
            return False
        if self.matcher.has_role_signal(value, threshold=0.65):
            return False
        blocked = (
            "school",
            "district",
            "department",
            "library",
            "media center",
            "email",
            "phone",
            "fax",
            "contact",
            "address",
            "website",
            "staff directory",
        )
        if any(term in lowered for term in blocked):
            return False
        words = value.replace(".", "").replace("'", "").replace("-", " ").split()
        if not 2 <= len(words) <= 5:
            return False
        return all(re.fullmatch(r"[A-Za-z]+", word) for word in words)

    def _container_text(self, element: Tag) -> str:
        fallback = ""
        for parent in element.parents:
            if isinstance(parent, Tag) and parent.name in {"tr", "li", "article", "section", "div", "p"}:
                text = compact_text(parent.get_text(" | "))
                if 20 <= len(text) <= 1_200:
                    if self.matcher.has_role_signal(text, threshold=0.72) or len(text) > 80:
                        return text
                    if not fallback:
                        fallback = text
        return fallback or compact_text(element.get_text(" | "))

    def _select_limited(
        self,
        soup: BeautifulSoup,
        selectors: Iterable[str],
        *,
        limit: int,
    ) -> Iterable[Tag]:
        count = 0
        for selector in selectors:
            for element in soup.select(selector):
                if isinstance(element, Tag):
                    yield element
                    count += 1
                    if count >= limit:
                        return

    def _dedupe(self, candidates: list[ContactCandidate]) -> list[ContactCandidate]:
        deduped: dict[str, ContactCandidate] = {}
        for candidate in candidates:
            if not candidate.email and not candidate.title:
                continue
            key = candidate.dedupe_key()
            existing = deduped.get(key)
            if not existing or len(candidate.context) < len(existing.context):
                deduped[key] = candidate
        return list(deduped.values())
