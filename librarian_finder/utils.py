"""Small normalization helpers used across the scraper."""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit


EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")


def compact_text(text: str) -> str:
    """Collapse repeated whitespace and unescape HTML entities."""

    return WHITESPACE_RE.sub(" ", unescape(text or "")).strip()


def normalize_url(url: str, base_url: str | None = None) -> str:
    """Normalize a URL for crawling while preserving useful query strings."""

    if not url:
        return ""
    url = url.strip()
    if base_url:
        url = urljoin(base_url, url)
    if url.startswith("//"):
        url = f"https:{url}"
    if "://" not in url:
        url = f"https://{url}"

    parts = urlsplit(url)
    scheme = parts.scheme.lower() or "https"
    netloc = parts.netloc.lower()
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/")

    query_items = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=False)
        if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}
    ]
    query = urlencode(query_items, doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def visit_key(url: str) -> str:
    """Return a stable key for URL deduplication."""

    parts = urlsplit(normalize_url(url))
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/") or "/", parts.query, ""))


def host(url: str) -> str:
    return urlsplit(normalize_url(url)).netloc.lower().split(":")[0]


def same_site(url: str, base_url: str) -> bool:
    """Allow only the same host and www/non-www variants.

    District sites often link to many school subdomains. Treating every subdomain
    as equivalent causes cross-school false positives, so broad subdomain crawling
    is intentionally avoided unless the input URL itself starts there.
    """

    link_host = strip_www(host(url))
    base_host = strip_www(host(base_url))
    return link_host == base_host


def strip_www(value: str) -> str:
    return value[4:] if value.startswith("www.") else value


def extract_emails(text: str) -> list[str]:
    """Extract normalized email addresses, including common obfuscations."""

    candidates = set()
    for source in {text or "", deobfuscate_email_text(text or "")}:
        for match in EMAIL_RE.findall(source):
            email = clean_email(match)
            if email:
                candidates.add(email)
    return sorted(candidates)


def clean_email(value: str) -> str:
    """Normalize one email or mailto value."""

    value = (value or "").strip()
    if value.lower().startswith("mailto:"):
        value = value[7:]
    value = value.split("?", 1)[0]
    value = value.strip(" \t\r\n,;:.<>[](){}\"'")
    return value.lower() if EMAIL_RE.fullmatch(value) else ""


def deobfuscate_email_text(text: str) -> str:
    """Convert simple 'name at domain dot org' forms into emails."""

    text = re.sub(r"\s*(?:\[at\]|\(at\)|\bat\b)\s*", "@", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*(?:\[dot\]|\(dot\)|\bdot\b)\s*", ".", text, flags=re.IGNORECASE)
    return text


def email_domain_matches(email: str, school_domain: str) -> bool:
    if not email or not school_domain:
        return False
    email_domain = strip_www(email.rsplit("@", 1)[-1].lower())
    school_host = strip_www(host(school_domain if "://" in school_domain else f"https://{school_domain}"))
    return email_domain == school_host or email_domain.endswith(f".{school_host}")


def title_case_from_email(email: str) -> str:
    """Derive a weak name hint from jane.doe-style emails."""

    local = email.split("@", 1)[0]
    local = re.sub(r"\d+", "", local)
    parts = [part for part in re.split(r"[._-]+", local) if len(part) > 1]
    if 2 <= len(parts) <= 4:
        return " ".join(part.capitalize() for part in parts)
    return ""
