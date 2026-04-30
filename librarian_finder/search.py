"""Targeted web-search fallback."""

from __future__ import annotations

import logging
from urllib.parse import parse_qs, quote_plus, unquote, urlsplit

from bs4 import BeautifulSoup

from .config import ScraperConfig
from .fetcher import AsyncFetcher
from .models import SchoolInput
from .utils import normalize_url, same_site


class SearchFallback:
    """Find candidate URLs with targeted search queries when site crawl fails."""

    def __init__(
        self,
        config: ScraperConfig,
        fetcher: AsyncFetcher,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.fetcher = fetcher
        self.logger = logger or logging.getLogger(__name__)

    async def find_urls(self, school: SchoolInput) -> list[str]:
        """Search for likely librarian pages and return same-site result URLs."""

        domain = school.domain or urlsplit(normalize_url(school.website)).netloc
        queries = [
            f"site:{domain} librarian",
            f"site:{domain} \"media specialist\"",
            f"\"{school.school_name}\" librarian",
        ]
        urls: list[str] = []
        seen: set[str] = set()
        for query in queries:
            if len(urls) >= self.config.search_results:
                break
            search_url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
            page = await self.fetcher.fetch(
                search_url,
                depth=0,
                page_kind="search",
                allow_browser=False,
            )
            if not page.ok:
                self.logger.debug("Search failed for %s: %s", query, page.error or page.status_code)
                continue
            for url in self._parse_duckduckgo_results(page.text):
                if not same_site(url, school.website or domain):
                    continue
                normalized = normalize_url(url)
                if normalized not in seen:
                    seen.add(normalized)
                    urls.append(normalized)
                if len(urls) >= self.config.search_results:
                    break
        return urls

    def _parse_duckduckgo_results(self, html: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        urls: list[str] = []
        for anchor in soup.select("a.result__a, a[href]"):
            href = anchor.get("href", "")
            if not href:
                continue
            if "duckduckgo.com/l/" in href or href.startswith("/l/"):
                query = parse_qs(urlsplit(href).query)
                href = unquote(query.get("uddg", [""])[0])
            if href.startswith("http"):
                urls.append(href)
        return urls
