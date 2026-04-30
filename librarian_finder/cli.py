"""Command-line interface for librarian-finder."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer

from .config import ScraperConfig
from .logging_utils import setup_logging
from .pipeline import LibrarianFinderPipeline


app = typer.Typer(help="Find librarian/media specialist contacts from school websites.")


@app.callback()
def main() -> None:
    """Find librarian/media specialist contacts from school websites."""


@app.command()
def run(
    input: Path = typer.Option(..., "--input", "-i", help="Input schools CSV."),
    output: Path = typer.Option(..., "--output", "-o", help="Output contacts CSV."),
    concurrency: int = typer.Option(75, min=1, max=500, help="Concurrent school workers."),
    max_depth: int = typer.Option(2, min=0, max=4, help="Maximum same-site crawl depth."),
    max_pages: int = typer.Option(25, min=1, max=200, help="Maximum pages per school."),
    timeout: float = typer.Option(15.0, min=1.0, help="Per-request timeout in seconds."),
    enable_browser: bool = typer.Option(False, help="Enable Playwright fallback for JS-heavy pages."),
    browser_concurrency: int = typer.Option(5, min=1, max=50, help="Concurrent browser renders."),
    search_fallback: bool = typer.Option(False, help="Use targeted DuckDuckGo fallback when crawl has no match."),
    low_confidence_threshold: float = typer.Option(0.65, min=0.0, max=1.0, help="Warning threshold."),
    no_match_threshold: float = typer.Option(0.35, min=0.0, max=1.0, help="Minimum confidence to output a match."),
    log_file: Optional[Path] = typer.Option(Path("logs/librarian_finder.log"), help="Detailed log file."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Run the extraction pipeline."""

    logger = setup_logging(str(log_file) if log_file else None, verbose=verbose)
    config = ScraperConfig(
        concurrency=concurrency,
        max_depth=max_depth,
        max_pages_per_school=max_pages,
        timeout_seconds=timeout,
        enable_browser=enable_browser,
        browser_concurrency=browser_concurrency,
        search_fallback=search_fallback,
        low_confidence_threshold=low_confidence_threshold,
        no_match_threshold=no_match_threshold,
    )
    pipeline = LibrarianFinderPipeline(config, logger)
    stats = asyncio.run(pipeline.run(input, output))
    typer.echo(
        "Completed "
        f"{stats.total} schools; matched={stats.matched}; no_match={stats.no_match}; "
        f"failed={stats.failed}; success_rate={stats.success_rate:.1%}; "
        f"avg_confidence={stats.average_confidence:.3f}"
    )


if __name__ == "__main__":
    app()
