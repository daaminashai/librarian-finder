"""HTTP and optional headless-browser fetching."""

from __future__ import annotations

import asyncio
import logging
import random
import re
from types import TracebackType

import httpx

from .config import ScraperConfig
from .models import FetchedPage


class AsyncFetcher:
    """Fetch pages with retries and optional Playwright fallback."""

    def __init__(self, config: ScraperConfig, logger: logging.Logger | None = None) -> None:
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.client: httpx.AsyncClient | None = None
        self._playwright = None
        self._browser = None
        self._browser_sem = asyncio.Semaphore(config.browser_concurrency)
        self._browser_unavailable_logged = False

    async def __aenter__(self) -> "AsyncFetcher":
        limits = httpx.Limits(
            max_connections=max(20, self.config.concurrency * 2),
            max_keepalive_connections=max(10, self.config.concurrency),
        )
        self.client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(self.config.timeout_seconds),
            limits=limits,
            headers={"User-Agent": self.config.user_agent},
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.client:
            await self.client.aclose()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def fetch(
        self,
        url: str,
        *,
        depth: int = 0,
        page_kind: str = "generic",
        allow_browser: bool = True,
    ) -> FetchedPage:
        """Fetch a URL, retrying transient failures with exponential backoff."""

        if not self.client:
            raise RuntimeError("AsyncFetcher must be used as an async context manager")

        last_error = ""
        for attempt in range(1, self.config.retry_attempts + 1):
            try:
                response = await self.client.get(url)
                content_type = response.headers.get("content-type", "").split(";", 1)[0]
                text = self._decode_response(response)
                page = FetchedPage(
                    url=url,
                    final_url=str(response.url),
                    status_code=response.status_code,
                    content_type=content_type,
                    text=text,
                    depth=depth,
                    page_kind=page_kind,
                )

                if (
                    self.config.enable_browser
                    and allow_browser
                    and page.ok
                    and page.is_html
                    and self._needs_browser(text)
                ):
                    browser_page = await self._fetch_with_browser(
                        page.final_url,
                        depth=depth,
                        page_kind=page_kind,
                    )
                    if browser_page and len(browser_page.text) > len(page.text):
                        return browser_page
                return page
            except Exception as exc:  # noqa: BLE001 - network stack raises many exception types.
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < self.config.retry_attempts:
                    delay = self.config.retry_backoff_seconds * (2 ** (attempt - 1))
                    await asyncio.sleep(delay + random.uniform(0, delay / 2))

        return FetchedPage(
            url=url,
            final_url=url,
            status_code=0,
            content_type="",
            text="",
            depth=depth,
            page_kind=page_kind,
            error=last_error or "fetch failed",
        )

    def _decode_response(self, response: httpx.Response) -> str:
        content = response.content[: self.config.max_response_bytes]
        encoding = response.encoding or "utf-8"
        try:
            return content.decode(encoding, errors="replace")
        except LookupError:
            return content.decode("utf-8", errors="replace")

    def _needs_browser(self, html: str) -> bool:
        lowered = html.lower()
        has_app_marker = any(
            marker in lowered
            for marker in (
                "enable javascript",
                "requires javascript",
                "please enable js",
                "id=\"root\"",
                "id=\"app\"",
            )
        )
        without_scripts = re.sub(r"<(script|style)\b.*?</\1>", " ", lowered, flags=re.DOTALL)
        visible_text = re.sub(r"<[^>]+>", " ", without_scripts)
        visible_text = re.sub(r"\s+", " ", visible_text).strip()
        if has_app_marker and len(visible_text) < 500:
            return True
        return len(visible_text.strip()) < 500 and lowered.count("<script") >= 5

    async def _fetch_with_browser(
        self,
        url: str,
        *,
        depth: int,
        page_kind: str,
    ) -> FetchedPage | None:
        """Render a page with Playwright when static HTML is insufficient."""

        async with self._browser_sem:
            try:
                if not self._playwright:
                    from playwright.async_api import async_playwright

                    self._playwright = await async_playwright().start()
                if not self._browser:
                    self._browser = await self._playwright.chromium.launch(headless=True)

                page = await self._browser.new_page(user_agent=self.config.user_agent)
                try:
                    response = await page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=int(self.config.timeout_seconds * 1000),
                    )
                    await page.wait_for_timeout(750)
                    html = await page.content()
                    status = response.status if response else 200
                    return FetchedPage(
                        url=url,
                        final_url=page.url,
                        status_code=status,
                        content_type="text/html",
                        text=html[: self.config.max_response_bytes],
                        depth=depth,
                        page_kind=page_kind,
                        fetched_with_browser=True,
                    )
                finally:
                    await page.close()
            except Exception as exc:  # noqa: BLE001 - browser startup/render failures should not fail crawl.
                if not self._browser_unavailable_logged:
                    self.logger.warning("Browser fallback unavailable or failed: %s", exc)
                    self._browser_unavailable_logged = True
                return None
