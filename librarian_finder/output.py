"""Streaming CSV output."""

from __future__ import annotations

import csv
from pathlib import Path
from types import TracebackType
from typing import TextIO

from .models import ExtractionResult


class CSVResultWriter:
    """Write extraction results incrementally to avoid buffering large runs."""

    fieldnames = [
        "school_name",
        "website",
        "librarian_name",
        "title",
        "email",
        "source_url",
        "confidence",
        "status",
        "error",
        "pages_crawled",
        "candidates_found",
    ]

    def __init__(self, output_path: str | Path) -> None:
        self.output_path = Path(output_path)
        self._file: TextIO | None = None
        self._writer: csv.DictWriter | None = None

    def __enter__(self) -> "CSVResultWriter":
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.output_path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=self.fieldnames)
        self._writer.writeheader()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._file:
            self._file.close()

    def write(self, result: ExtractionResult) -> None:
        if not self._writer or not self._file:
            raise RuntimeError("CSVResultWriter must be used as a context manager")
        self._writer.writerow(result.to_csv_row())
        self._file.flush()
