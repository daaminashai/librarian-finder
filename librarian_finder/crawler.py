"""Bounded same-site crawler with staff/library page prioritization."""

from __future__ import annotations

import heapq
import logging
import re
from collections.abc import Iterable
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .config import ScraperConfig
from .fetcher import AsyncFetcher
from .models import FetchedPage, SchoolInput
from .utils import compact_text, host, normalize_url, strip_www, visit_key

try:
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover - runtime fallback when optional import is absent.
    fuzz = None


class SchoolCrawler:
    """Crawl one school website without leaving its domain."""

    def __init__(
        self,
        config: ScraperConfig,
        fetcher: AsyncFetcher,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.fetcher = fetcher
        self.logger = logger or logging.getLogger(__name__)

    async def crawl(self, school: SchoolInput) -> list[FetchedPage]:
        """Return fetched pages ordered by crawl priority."""

        start_urls = self._start_urls(school)
        if not start_urls:
            return []

        queue: list[tuple[int, int, int, str, str]] = []
        counter = 0
        visited: set[str] = set()
        enqueued: set[str] = set()

        for url in start_urls:
            counter = self._push(queue, enqueued, counter, 0, url, "home", 0)

        pages: list[FetchedPage] = []
        base_url = start_urls[0]
        start_hosts = {strip_www(host(url)) for url in start_urls}
        allowed_hosts = set(start_hosts)

        while queue and len(pages) < self.config.max_pages_per_school:
            _priority, _counter, depth, url, page_kind = heapq.heappop(queue)
            key = visit_key(url)
            if key in visited:
                continue
            visited.add(key)

            page = await self.fetcher.fetch(url, depth=depth, page_kind=page_kind)
            if not page.ok:
                self.logger.debug("Fetch failed for %s: %s", url, page.error or page.status_code)
                continue
            if not self._is_allowed_host(page.final_url, allowed_hosts):
                self.logger.debug("Skipping off-site redirect from %s to %s", url, page.final_url)
                continue
            if not page.is_html:
                continue

            pages.append(page)
            if page.page_kind == "home":
                for school_url in self._discover_matching_school_links(page, school):
                    allowed_hosts.add(strip_www(host(school_url)))
                    counter = self._push(queue, enqueued, counter, 0, school_url, "home", -10)
                for seed_url, seed_kind, seed_priority in self._priority_seed_urls(page.final_url):
                    if strip_www(host(page.final_url)) not in start_hosts:
                        seed_priority -= 20
                    counter = self._push(
                        queue,
                        enqueued,
                        counter,
                        1,
                        seed_url,
                        seed_kind,
                        seed_priority,
                    )

            if depth >= self.config.max_depth:
                continue

            for link in self._extract_links(page):
                if not self._is_allowed_host(link, allowed_hosts) or self._should_skip(link):
                    continue
                kind, priority = self._classify_url(link)
                next_depth = depth + 1
                if kind == "generic" and next_depth >= self.config.max_depth:
                    continue
                counter = self._push(queue, enqueued, counter, next_depth, link, kind, priority)

        return pages

    def _start_urls(self, school: SchoolInput) -> list[str]:
        raw = school.website or school.domain
        if not raw:
            return []
        if "://" in raw:
            return [normalize_url(raw)]
        raw = raw.strip().strip("/")
        return [normalize_url(f"https://{raw}"), normalize_url(f"http://{raw}")]

    def _priority_seed_urls(self, final_home_url: str) -> Iterable[tuple[str, str, int]]:
        for path, kind, priority in self.config.priority_paths:
            yield normalize_url(path, final_home_url), kind, priority

    def _extract_links(self, page: FetchedPage) -> list[str]:
        soup = BeautifulSoup(page.text, "lxml")
        links: list[str] = []
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href", "")
            if href.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            url = normalize_url(href, page.final_url)
            if url:
                links.append(url)
        return links

    def _discover_matching_school_links(self, page: FetchedPage, school: SchoolInput) -> list[str]:
        """Find exact school links in district school-selector dropdowns."""

        if not school.school_name:
            return []

        soup = BeautifulSoup(page.text, "lxml")
        school_name = self._normalize_school_name(school.school_name)
        urls: list[str] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            label = compact_text(" ".join(
                value for value in (anchor.get_text(" "), anchor.get("title", ""), anchor.get("aria-label", "")) if value
            ))
            if not label:
                continue
            if self._school_name_score(school_name, label) < 0.92:
                continue
            url = normalize_url(anchor.get("href", ""), page.final_url)
            if not url or self._should_skip(url):
                continue
            key = visit_key(url)
            if key not in seen:
                seen.add(key)
                urls.append(url)
        return urls

    def _classify_url(self, url: str) -> tuple[str, int]:
        path = urlsplit(url).path.lower().replace("_", "-")
        for term, kind, priority in self.config.relevant_path_terms:
            if term in path:
                return kind, priority
        return "generic", 50

    def _should_skip(self, url: str) -> bool:
        parts = urlsplit(url)
        path = parts.path.lower()
        if any(path.endswith(ext) for ext in self.config.skip_extensions):
            return True
        return any(term in path for term in self.config.skip_path_terms)

    def _is_allowed_host(self, url: str, allowed_hosts: set[str]) -> bool:
        return strip_www(host(url)) in allowed_hosts

    def _normalize_school_name(self, name: str) -> str:
        name = compact_text(name).lower()
        name = re.sub(r"\b(go to|the)\b", " ", name)
        name = re.sub(r"[^a-z0-9\s]", " ", name)
        return compact_text(name)

    def _school_name_score(self, normalized_school_name: str, label: str) -> float:
        label = label.lower().replace("go to", " ")
        normalized_label = self._normalize_school_name(label)
        if not normalized_school_name or not normalized_label:
            return 0.0
        if normalized_school_name == normalized_label:
            return 1.0
        if fuzz:
            return max(
                fuzz.token_set_ratio(normalized_school_name, normalized_label),
                fuzz.token_sort_ratio(normalized_school_name, normalized_label),
            ) / 100.0
        school_tokens = set(normalized_school_name.split())
        label_tokens = set(normalized_label.split())
        return len(school_tokens & label_tokens) / len(school_tokens | label_tokens)

    def _push(
        self,
        queue: list[tuple[int, int, int, str, str]],
        enqueued: set[str],
        counter: int,
        depth: int,
        url: str,
        page_kind: str,
        priority: int,
    ) -> int:
        key = visit_key(url)
        if key not in enqueued:
            enqueued.add(key)
            heapq.heappush(queue, (priority, counter, depth, url, page_kind))
            counter += 1
        return counter
