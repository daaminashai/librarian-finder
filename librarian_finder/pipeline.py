"""Async orchestration for large CSV runs."""

from __future__ import annotations

import asyncio
import csv
import logging
from pathlib import Path

from tqdm import tqdm

from .config import ScraperConfig
from .crawler import SchoolCrawler
from .fetcher import AsyncFetcher
from .matcher import RoleMatcher
from .models import ExtractionResult, FetchedPage, RunStats, SchoolInput
from .output import CSVResultWriter
from .parser import PageParser
from .ranker import CandidateRanker
from .search import SearchFallback


class LibrarianFinderPipeline:
    """End-to-end extraction pipeline for a CSV of schools."""

    def __init__(self, config: ScraperConfig, logger: logging.Logger | None = None) -> None:
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.matcher = RoleMatcher(config)
        self.parser = PageParser(config, self.matcher)
        self.ranker = CandidateRanker(config, self.matcher)

    async def run(self, input_path: str | Path, output_path: str | Path) -> RunStats:
        """Process the input CSV and stream output rows as schools complete."""

        schools = self._read_schools(input_path)
        stats = RunStats()
        queue: asyncio.Queue[SchoolInput | None] = asyncio.Queue()
        result_queue: asyncio.Queue[ExtractionResult | None] = asyncio.Queue()

        for school in schools:
            await queue.put(school)
        worker_count = min(self.config.concurrency, max(len(schools), 1))
        for _ in range(worker_count):
            await queue.put(None)

        async with AsyncFetcher(self.config, self.logger) as fetcher:
            workers = [
                asyncio.create_task(self._worker(queue, result_queue, fetcher))
                for _ in range(worker_count)
            ]
            writer_task = asyncio.create_task(
                self._write_results(result_queue, output_path, len(schools), stats)
            )
            await asyncio.gather(*workers)
            await result_queue.put(None)
            await writer_task

        self.logger.info(
            "Completed %s schools: matched=%s no_match=%s failed=%s success_rate=%.1f%% avg_confidence=%.3f",
            stats.total,
            stats.matched,
            stats.no_match,
            stats.failed,
            stats.success_rate * 100,
            stats.average_confidence,
        )
        return stats

    async def process_school(self, school: SchoolInput, fetcher: AsyncFetcher) -> ExtractionResult:
        """Crawl, extract, optionally search, and rank one school."""

        if not school.website:
            return ExtractionResult(
                school_name=school.school_name,
                website=school.website,
                status="failed",
                error="missing website/domain",
            )

        try:
            crawler = SchoolCrawler(self.config, fetcher, self.logger)
            pages = await crawler.crawl(school)
            candidates = self._parse_pages(pages)
            best = self.ranker.best(school, candidates)

            if not best and self.config.search_fallback:
                search_pages = await self._search_and_fetch(school, fetcher)
                pages.extend(search_pages)
                candidates.extend(self._parse_pages(search_pages))
                best = self.ranker.best(school, candidates)

            if not best:
                return ExtractionResult(
                    school_name=school.school_name,
                    website=school.website,
                    status="no_match",
                    pages_crawled=len(pages),
                    candidates_found=len(candidates),
                )

            result = ExtractionResult(
                school_name=school.school_name,
                website=school.website,
                librarian_name=best.name,
                title=best.title,
                email=best.email,
                source_url=best.source_url,
                confidence=best.confidence,
                status="matched",
                pages_crawled=len(pages),
                candidates_found=len(candidates),
            )
            if result.confidence < self.config.low_confidence_threshold:
                self.logger.warning(
                    "Low-confidence match for %s (%s): %.3f %s",
                    school.school_name,
                    school.website,
                    result.confidence,
                    result.source_url,
                )
            return result
        except Exception as exc:  # noqa: BLE001 - isolate failures per domain.
            self.logger.exception("Failed processing %s (%s)", school.school_name, school.website)
            return ExtractionResult(
                school_name=school.school_name,
                website=school.website,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )

    async def _worker(
        self,
        queue: asyncio.Queue[SchoolInput | None],
        result_queue: asyncio.Queue[ExtractionResult | None],
        fetcher: AsyncFetcher,
    ) -> None:
        while True:
            school = await queue.get()
            try:
                if school is None:
                    return
                result = await self.process_school(school, fetcher)
                await result_queue.put(result)
            finally:
                queue.task_done()

    async def _write_results(
        self,
        result_queue: asyncio.Queue[ExtractionResult | None],
        output_path: str | Path,
        total: int,
        stats: RunStats,
    ) -> None:
        with CSVResultWriter(output_path) as writer:
            progress = tqdm(total=total, unit="school", desc="schools")
            try:
                while True:
                    result = await result_queue.get()
                    try:
                        if result is None:
                            return
                        writer.write(result)
                        stats.observe(result, self.config.low_confidence_threshold)
                        progress.update(1)
                    finally:
                        result_queue.task_done()
            finally:
                progress.close()

    async def _search_and_fetch(self, school: SchoolInput, fetcher: AsyncFetcher) -> list[FetchedPage]:
        search = SearchFallback(self.config, fetcher, self.logger)
        urls = await search.find_urls(school)
        pages: list[FetchedPage] = []
        for url in urls:
            page = await fetcher.fetch(url, depth=0, page_kind="search")
            if page.ok and page.is_html:
                pages.append(page)
        return pages

    def _parse_pages(self, pages: list[FetchedPage]):
        candidates = []
        for page in pages:
            candidates.extend(self.parser.parse(page))
        return candidates

    def _read_schools(self, input_path: str | Path) -> list[SchoolInput]:
        path = Path(input_path)
        with path.open("r", newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            if not reader.fieldnames:
                raise ValueError("input CSV must include a header row")
            schools = [SchoolInput.from_row(row, index) for index, row in enumerate(reader, start=2)]

        valid = [school for school in schools if school.school_name or school.website]
        skipped = len(schools) - len(valid)
        if skipped:
            self.logger.warning("Skipped %s blank input rows", skipped)
        return valid
