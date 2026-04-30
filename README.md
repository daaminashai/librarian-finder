# librarian-finder

Production-oriented async scraper for finding librarian, media specialist, and related library/media contacts from school websites.

The pipeline starts from each school homepage, prioritizes likely staff/library pages, extracts structured contact candidates from inconsistent HTML layouts, fuzzy-matches role/title text, ranks candidates, and streams one best result per school to CSV.

PDF extraction is intentionally not included.

## Features

- Async crawling with bounded concurrency using `httpx`
- Optional Playwright fallback for JavaScript-rendered pages
- Same-site crawl limits by depth and page count
- Priority discovery for `/staff`, `/directory`, `/faculty`, `/about`, `/library`, and media center pages
- School-selector discovery for district homepages that link to individual school subdomains
- Extraction from tables, cards, lists, text windows, and `mailto:` links
- Fuzzy role matching with `rapidfuzz`
- Candidate ranking with confidence scores from role relevance, source page relevance, email presence, name quality, and title seniority
- Optional targeted search fallback using queries like `site:DOMAIN librarian`
- Streaming CSV output suitable for large input files
- Per-domain failure isolation, low-confidence logging, and summary stats

## Install

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

If you want browser fallback for JS-heavy websites:

```bash
playwright install chromium
```

## Input CSV

The input CSV should include headers. The parser accepts flexible column names, including:

- School name: `school_name`, `school`, `name`, `organization`
- Website: `website`, `url`, `site`, `homepage`
- Domain: `domain`, `host`
- Address: `mailing_address`, `address`, `street_address`, `location`

Example:

```csv
school_name,website,domain,mailing_address
Example High School,https://www.example.edu,www.example.edu,"123 Main St, Example, NY"
```

## Run

Basic run:

```bash
python -m librarian_finder.cli run \
  --input examples/schools.csv \
  --output results.csv
```

Recommended large run:

```bash
python -m librarian_finder.cli run \
  --input schools.csv \
  --output results.csv \
  --concurrency 100 \
  --max-depth 2 \
  --max-pages 25 \
  --timeout 15 \
  --search-fallback \
  --log-file logs/librarian_finder.log
```

Run with JavaScript rendering fallback:

```bash
python -m librarian_finder.cli run \
  --input schools.csv \
  --output results.csv \
  --concurrency 75 \
  --enable-browser \
  --browser-concurrency 5
```

Browser rendering is expensive. For 26,000 schools, start without `--enable-browser`, then rerun only failures/no-match rows with browser fallback if needed.

## Output CSV

Fields:

- `school_name`
- `website`
- `librarian_name`
- `title`
- `email`
- `source_url`
- `confidence`
- `status`
- `error`
- `pages_crawled`
- `candidates_found`

Statuses:

- `matched`: a candidate met the configured confidence threshold
- `no_match`: pages were processed but no confident librarian/media contact was found
- `failed`: the row could not be processed, usually because of missing input or repeated fetch errors

## Scaling Notes

- Use `--concurrency 50` to `--concurrency 200` depending on network capacity.
- Keep `--max-depth 2` and `--max-pages 25` for broad runs.
- Increase `--max-pages` for reruns on no-match domains.
- Use `--search-fallback` when recall matters more than speed.
- Use `--enable-browser` selectively because headless rendering dominates runtime.
- Output is streamed, so partial results are preserved if a long run is interrupted.

## Architecture

- `librarian_finder.fetcher`: HTTP client, retries, browser fallback
- `librarian_finder.crawler`: bounded same-site crawl and URL prioritization
- `librarian_finder.parser`: HTML candidate extraction heuristics
- `librarian_finder.matcher`: fuzzy role matching
- `librarian_finder.ranker`: candidate ranking and confidence scoring
- `librarian_finder.search`: targeted search fallback
- `librarian_finder.pipeline`: async orchestration and failure isolation
- `librarian_finder.output`: streaming CSV writer
- `librarian_finder.cli`: CLI entry point

## Confidence

Confidence is a heuristic `0.0-1.0` score. Strong matches usually include an exact librarian/media role, a name, an email, and a relevant source URL. Low-confidence matches are logged when below `--low-confidence-threshold`.
