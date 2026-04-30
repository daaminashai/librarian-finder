"""Data models shared by pipeline components."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit


@dataclass
class SchoolInput:
    """A single school row from the input CSV."""

    school_name: str
    website: str
    domain: str = ""
    mailing_address: str = ""
    row_number: int = 0

    @classmethod
    def from_row(cls, row: dict[str, str], row_number: int) -> "SchoolInput":
        """Build a school input from flexible CSV column names."""

        normalized = {key.strip().lower(): (value or "").strip() for key, value in row.items()}
        name = first_value(normalized, "school_name", "school", "name", "organization")
        website = first_value(normalized, "website", "url", "site", "homepage")
        domain = first_value(normalized, "domain", "host")
        address = first_value(
            normalized,
            "mailing_address",
            "address",
            "street_address",
            "location",
        )

        if not website and domain:
            website = domain
        if not domain and website:
            domain = urlsplit(website if "://" in website else f"https://{website}").netloc

        return cls(
            school_name=name,
            website=website,
            domain=domain,
            mailing_address=address,
            row_number=row_number,
        )


@dataclass
class FetchedPage:
    """A crawled page and its normalized metadata."""

    url: str
    final_url: str
    status_code: int
    content_type: str
    text: str
    depth: int
    page_kind: str = "generic"
    fetched_with_browser: bool = False
    error: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400 and not self.error

    @property
    def is_html(self) -> bool:
        content_type = self.content_type.lower()
        return "html" in content_type or "xml" in content_type or not content_type


@dataclass
class ContactCandidate:
    """A possible librarian/media specialist extracted from one source page."""

    name: str
    title: str
    email: str
    source_url: str
    source_kind: str
    context: str
    signals: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0

    def dedupe_key(self) -> str:
        if self.email:
            return f"email:{self.email.lower()}"
        key = "|".join([self.name.lower(), self.title.lower(), self.source_url.lower()])
        return f"name-title:{key}"


@dataclass
class ExtractionResult:
    """The final output row for one school."""

    school_name: str
    website: str
    librarian_name: str = ""
    title: str = ""
    email: str = ""
    source_url: str = ""
    confidence: float = 0.0
    status: str = "no_match"
    error: str = ""
    pages_crawled: int = 0
    candidates_found: int = 0

    def to_csv_row(self) -> dict[str, str]:
        """Serialize for CSV output."""

        return {
            "school_name": self.school_name,
            "website": self.website,
            "librarian_name": self.librarian_name,
            "title": self.title,
            "email": self.email,
            "source_url": self.source_url,
            "confidence": f"{self.confidence:.3f}",
            "status": self.status,
            "error": self.error,
            "pages_crawled": str(self.pages_crawled),
            "candidates_found": str(self.candidates_found),
        }


@dataclass
class RunStats:
    """Aggregate metrics for a pipeline run."""

    total: int = 0
    matched: int = 0
    no_match: int = 0
    failed: int = 0
    low_confidence: int = 0
    confidence_sum: float = 0.0

    def observe(self, result: ExtractionResult, low_confidence_threshold: float) -> None:
        self.total += 1
        if result.status == "matched":
            self.matched += 1
            self.confidence_sum += result.confidence
            if result.confidence < low_confidence_threshold:
                self.low_confidence += 1
        elif result.status == "failed":
            self.failed += 1
        else:
            self.no_match += 1

    @property
    def success_rate(self) -> float:
        return self.matched / self.total if self.total else 0.0

    @property
    def average_confidence(self) -> float:
        return self.confidence_sum / self.matched if self.matched else 0.0


def first_value(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = row.get(key, "").strip()
        if value:
            return value
    return ""
