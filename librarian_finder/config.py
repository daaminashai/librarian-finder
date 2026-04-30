"""Runtime configuration for the librarian finder pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScraperConfig:
    """Controls crawl scope, extraction thresholds, and runtime behavior."""

    concurrency: int = 75
    max_depth: int = 2
    max_pages_per_school: int = 25
    timeout_seconds: float = 15.0
    retry_attempts: int = 3
    retry_backoff_seconds: float = 0.75
    max_response_bytes: int = 3_000_000
    enable_browser: bool = False
    browser_concurrency: int = 5
    search_fallback: bool = False
    search_results: int = 5
    low_confidence_threshold: float = 0.65
    no_match_threshold: float = 0.35
    user_agent: str = (
        "Mozilla/5.0 (compatible; LibrarianFinder/0.1; "
        "+https://example.invalid/librarian-finder)"
    )

    role_keywords: tuple[str, ...] = (
        "librarian",
        "school librarian",
        "media specialist",
        "library media specialist",
        "media center specialist",
        "media center",
        "library assistant",
        "teacher librarian",
        "instructional media",
        "instructional media specialist",
        "media coordinator",
        "library media coordinator",
        "media aide",
        "library aide",
        "library clerk",
    )

    senior_role_keywords: tuple[str, ...] = (
        "librarian",
        "media specialist",
        "library media specialist",
        "teacher librarian",
        "media coordinator",
    )

    assistant_role_keywords: tuple[str, ...] = (
        "assistant",
        "aide",
        "clerk",
        "paraprofessional",
    )

    priority_paths: tuple[tuple[str, str, int], ...] = (
        ("/staff", "staff", 5),
        ("/staff-directory", "directory", 5),
        ("/directory", "directory", 5),
        ("/faculty", "faculty", 8),
        ("/about", "about", 15),
        ("/library", "library", 2),
        ("/media-center", "library", 2),
        ("/media_center", "library", 2),
    )

    relevant_path_terms: tuple[tuple[str, str, int], ...] = (
        ("library", "library", 1),
        ("media-center", "library", 1),
        ("media_center", "library", 1),
        ("media", "library", 12),
        ("staff", "staff", 4),
        ("directory", "directory", 4),
        ("faculty", "faculty", 7),
        ("employee", "directory", 9),
        ("teacher", "faculty", 14),
        ("about", "about", 16),
    )

    source_kind_weights: dict[str, float] = field(
        default_factory=lambda: {
            "library": 0.18,
            "staff": 0.13,
            "directory": 0.13,
            "faculty": 0.10,
            "about": 0.05,
            "home": 0.03,
            "search": 0.03,
            "generic": 0.00,
        }
    )

    skip_path_terms: tuple[str, ...] = (
        "calendar",
        "athletic",
        "sports",
        "lunch",
        "menu",
        "cafeteria",
        "transportation",
        "bus",
        "board",
        "policy",
        "privacy",
        "terms",
        "news",
        "event",
        "alumni",
        "employment",
        "jobs",
        "careers",
        "enrollment",
        "admission",
        "donate",
        "facebook",
        "twitter",
        "instagram",
        "youtube",
    )

    skip_extensions: tuple[str, ...] = (
        ".7z",
        ".avi",
        ".css",
        ".doc",
        ".docx",
        ".gif",
        ".gz",
        ".ico",
        ".jpeg",
        ".jpg",
        ".js",
        ".mp3",
        ".mp4",
        ".mpeg",
        ".png",
        ".ppt",
        ".pptx",
        ".rar",
        ".svg",
        ".tar",
        ".webm",
        ".webp",
        ".xls",
        ".xlsx",
        ".zip",
        ".pdf",
    )
