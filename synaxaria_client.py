#!/usr/bin/env python3
"""Project Synaxaria API client — saint biographies for liturgical descriptions.

Project Synaxaria (https://www.synaxaria.com/) is an MIT-licensed, open-source
aggregator of Orthodox saints' lives compiled from GOARCH, the OCA, the Prologue
from Ochrid, and Orthodox England. It exposes a small JSON REST API:

    GET /api/v1/saints/daily?date=MM-DD      -> all saints for that day
    GET /api/v1/saints/:id                   -> one saint (full life_text)
    GET /api/v1/saints?q=<query>             -> search

Authentication is by ``Authorization: Bearer <api_key>`` (the daily list endpoint
is currently open, but the per-saint detail endpoint requires the bearer token).

This module fetches the daily list for a date and matches GOARCH commemoration
names (from the GOARCH ICS feed) to a saint's biography, preferring the GOARCH
source and only falling back to another source when the names match closely.
"""

from __future__ import annotations

import json
import re
import time
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

_API_BASE = "https://synaxaria.com/api/v1"
_USER_AGENT = "Mozilla/5.0 (LiveStreamScheduler Synaxaria client)"
_DEFAULT_CACHE_DIR = Path(__file__).resolve().parent / "cache" / "synaxaria"
_DEFAULT_CACHE_TTL = 7 * 24 * 60 * 60  # saints' lives are static; cache a week.

# Process-lifetime memo of parsed daily payloads, keyed by "MM-DD".
_MEM_CACHE: dict[str, list[dict]] = {}

# Process-lifetime memo of parsed search payloads, keyed by the lowercase query.
_SEARCH_MEM_CACHE: dict[str, list[dict]] = {}

# Words to drop when normalizing names for matching.
_STOPWORDS = {
    "the", "of", "at", "in", "and", "saint", "st", "holy", "martyr", "martyrs",
    "monk", "monkmartyrs", "monkmartyr", "venerable", "righteous", "great",
    "new", "wonderworker", "apostle", "prophet", "patriarch", "archbishop",
    "bishop", "abbot", "abbess", "virgin", "virginmartyr", "hieromartyr",
    "confessor", "equaltotheapostles", "his", "her", "with", "companions",
}


class SynaxariaError(RuntimeError):
    """Raised when the Synaxaria API cannot be reached or parsed."""


def _cache_path(date_key: str, cache_dir: Path) -> Path:
    return cache_dir / f"daily_{date_key}.json"


def _http_get_json(url: str, api_key: str | None) -> object:
    headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(url, headers=headers)
    with urlopen(request, timeout=40) as response:
        body = response.read().decode("utf-8", errors="replace")
    return json.loads(body)


def fetch_daily(
    month: int,
    day: int,
    *,
    api_key: str | None = None,
    cache_dir: Path = _DEFAULT_CACHE_DIR,
    cache_ttl: int = _DEFAULT_CACHE_TTL,
    force_refresh: bool = False,
) -> list[dict]:
    """Return the list of saint records commemorated on ``month``/``day``.

    The date is the civil (Gregorian / Revised Julian "New Calendar") date.
    Synaxaria's GOARCH-source entries are keyed to the same New-Calendar civil
    date as the GOARCH ICS feed (verified: their commemorations align on the
    same MM-DD, not 13 days off), so passing the service's civil date keeps both
    sources on the Revised Julian calendar.

    Uses an in-memory memo and an on-disk JSON cache. Returns an empty list on
    any failure (callers should degrade gracefully).
    """

    date_key = f"{month:02d}-{day:02d}"

    if not force_refresh and date_key in _MEM_CACHE:
        return _MEM_CACHE[date_key]

    path = _cache_path(date_key, cache_dir)
    if (
        not force_refresh
        and path.exists()
        and (time.time() - path.stat().st_mtime) < cache_ttl
    ):
        try:
            records = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(records, list):
                _MEM_CACHE[date_key] = records
                return records
        except (OSError, json.JSONDecodeError):
            pass  # fall through to a network fetch

    url = f"{_API_BASE}/saints/daily?date={quote(date_key)}"
    try:
        payload = _http_get_json(url, api_key)
    except Exception:
        if path.exists():
            try:
                records = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(records, list):
                    _MEM_CACHE[date_key] = records
                    return records
            except (OSError, json.JSONDecodeError):
                pass
        return []

    records = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        records = []

    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(records), encoding="utf-8")
    except OSError:
        pass  # caching is best-effort

    _MEM_CACHE[date_key] = records
    return records


def _normalize(name: str) -> str:
    """Lowercase, strip punctuation, and drop honorifics/stopwords for matching."""

    cleaned = re.sub(r"[^a-z0-9\s]", " ", name.lower())
    tokens = [t for t in cleaned.split() if t and t not in _STOPWORDS]
    return " ".join(tokens)


def _token_set(name: str) -> set[str]:
    return set(_normalize(name).split())


def find_biography(
    saint_name: str,
    daily_records: list[dict],
    *,
    min_ratio: float = 0.72,
) -> str | None:
    """Return the best-matching, non-empty ``life_text`` for ``saint_name``.

    Matching is conservative to avoid attaching the wrong saint's life:

    1. Prefer an exact normalized-name match whose source is GOARCH and which
       has a biography.
    2. Otherwise accept any source whose normalized name matches exactly and
       has a biography.
    3. Otherwise accept a fuzzy match (sequence ratio >= ``min_ratio`` AND
       meaningful token overlap) with a biography.

    Returns ``None`` when no confident match with text is found.
    """

    target_norm = _normalize(saint_name)
    target_tokens = _token_set(saint_name)
    if not target_norm:
        return None

    exact_any: str | None = None
    best_fuzzy: tuple[float, str] | None = None

    for record in daily_records:
        if not isinstance(record, dict):
            continue
        text = record.get("life_text")
        if not isinstance(text, str) or not text.strip():
            continue
        name = str(record.get("name") or "")
        norm = _normalize(name)
        if not norm:
            continue

        if norm == target_norm:
            if str(record.get("source") or "").lower() == "goarch":
                return text.strip()  # best possible match
            if exact_any is None:
                exact_any = text.strip()
            continue

        ratio = SequenceMatcher(None, target_norm, norm).ratio()
        overlap = target_tokens & _token_set(name)
        # Require both string similarity and at least one shared meaningful token.
        if ratio >= min_ratio and overlap:
            if best_fuzzy is None or ratio > best_fuzzy[0]:
                best_fuzzy = (ratio, text.strip())

    if exact_any is not None:
        return exact_any
    if best_fuzzy is not None:
        return best_fuzzy[1]
    return None


def biographies_for_saints(
    saint_names: list[str],
    month: int,
    day: int,
    *,
    api_key: str | None = None,
    **fetch_kwargs,
) -> dict[str, str]:
    """Map each saint name to a biography (omitting those with no confident match)."""

    daily_records = fetch_daily(month, day, api_key=api_key, **fetch_kwargs)
    if not daily_records:
        return {}

    result: dict[str, str] = {}
    for name in saint_names:
        bio = find_biography(name, daily_records)
        if bio:
            result[name] = bio
    return result


def merge_saint_names(
    goarch_names: list[str],
    daily_records: list[dict],
) -> list[str]:
    """Combine GOARCH calendar names with GOARCH-source Synaxaria entry names.

    Only Synaxaria records whose ``source`` is GOARCH are considered. Names that
    match an existing entry exactly (after normalization — i.e. the same name
    ignoring honorifics, punctuation, and case) are collapsed to a single
    bullet, keeping the GOARCH-calendar spelling. Names that differ in spelling
    are *both* kept (left as near-duplicates) so the editor can delete whichever
    they don't want. Order: GOARCH calendar names first, then any additional
    GOARCH-source Synaxaria names in the order the API returned them.
    """

    result: list[str] = []
    seen_norms: set[str] = set()

    for name in goarch_names:
        clean = str(name or "").strip()
        if not clean:
            continue
        result.append(clean)
        norm = _normalize(clean)
        if norm:
            seen_norms.add(norm)

    for record in daily_records:
        if not isinstance(record, dict):
            continue
        if str(record.get("source") or "").strip().lower() != "goarch":
            continue
        name = str(record.get("name") or "").strip()
        if not name:
            continue
        norm = _normalize(name)
        if norm and norm in seen_norms:
            continue  # exact (normalized) match — already commemorated
        result.append(name)
        if norm:
            seen_norms.add(norm)

    return result


def search_saints(
    query: str,
    *,
    api_key: str | None = None,
    cache_dir: Path = _DEFAULT_CACHE_DIR,
    cache_ttl: int = _DEFAULT_CACHE_TTL,
    force_refresh: bool = False,
) -> list[dict]:
    """Full-text search the Synaxaria saints index for ``query``.

    Calls ``GET /api/v1/saints?q=<query>`` and returns the raw record list
    (each a dict with ``id``/``name``/``life_text``/``source``/``source_url``).
    Unlike ``fetch_daily`` (whose ``date=MM-DD`` endpoint is year-agnostic and so
    unreliable for moveable feasts), searching by name is a direct lookup and is
    safe for fixed feasts and named saints.

    Uses an in-memory memo and an on-disk JSON cache. Returns an empty list on
    any failure so callers degrade gracefully.
    """

    q = (query or "").strip()
    if not q:
        return []

    key = q.lower()
    if not force_refresh and key in _SEARCH_MEM_CACHE:
        return _SEARCH_MEM_CACHE[key]

    slug = re.sub(r"[^a-z0-9]+", "-", key).strip("-") or "q"
    path = cache_dir / f"search_{slug}.json"
    if (
        not force_refresh
        and path.exists()
        and (time.time() - path.stat().st_mtime) < cache_ttl
    ):
        try:
            records = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(records, list):
                _SEARCH_MEM_CACHE[key] = records
                return records
        except (OSError, json.JSONDecodeError):
            pass  # fall through to a network fetch

    url = f"{_API_BASE}/saints?q={quote(q)}"
    try:
        payload = _http_get_json(url, api_key)
    except Exception:
        if path.exists():
            try:
                records = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(records, list):
                    _SEARCH_MEM_CACHE[key] = records
                    return records
            except (OSError, json.JSONDecodeError):
                pass
        return []

    records = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        records = []

    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(records), encoding="utf-8")
    except OSError:
        pass  # caching is best-effort

    _SEARCH_MEM_CACHE[key] = records
    return records


def exact_search_entries(query: str, records: list[dict]) -> list[dict]:
    """Filter ``search_saints`` results to GOARCH-source exact-name matches.

    Two strict requirements:

    1. ``source`` must be GOARCH (other sources are dropped entirely).
    2. The record's name must match ``query`` **exactly** — the same characters
       after only trimming surrounding whitespace and collapsing runs of internal
       whitespace, compared case-insensitively. Articles and honorifics are NOT
       stripped, so "The Sunday of All Saints" matches only "The Sunday of All
       Saints", not "Sunday of All Saints".

    Only records with a non-empty biography are kept. Returns the same
    ``{"name", "source", "life_text", "url"}`` shape as
    ``reference_entries_from_records`` and de-duplicates by exact name.
    """

    def _exact_key(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip().casefold()

    target = _exact_key(query)
    if not target:
        return []

    entries: list[dict] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        if str(record.get("source") or "").strip().lower() != "goarch":
            continue
        name = str(record.get("name") or "").strip()
        if _exact_key(name) != target:
            continue
        text = record.get("life_text")
        if not isinstance(text, str) or not text.strip():
            continue
        dedupe = _exact_key(name)
        if dedupe in seen:
            continue
        seen.add(dedupe)
        entries.append(
            {
                "name": name,
                "source": str(record.get("source") or "").strip(),
                "life_text": text.strip(),
                "url": str(record.get("source_url") or record.get("url") or "").strip(),
            }
        )
    return entries


def reference_entries_from_records(daily_records: list[dict]) -> list[dict]:
    """Return Synaxaria entries that have a biography, for a copy/paste card.

    Each entry is ``{"name", "source", "life_text", "url"}``. Entries without a
    non-empty ``life_text`` are omitted (the card exists to grab descriptions).
    """

    entries: list[dict] = []
    for record in daily_records:
        if not isinstance(record, dict):
            continue
        text = record.get("life_text")
        if not isinstance(text, str) or not text.strip():
            continue
        entries.append(
            {
                "name": str(record.get("name") or "").strip(),
                "source": str(record.get("source") or "").strip(),
                "life_text": text.strip(),
                "url": str(record.get("source_url") or record.get("url") or "").strip(),
            }
        )
    return entries


def _main(argv: list[str]) -> int:
    import argparse
    from datetime import date

    parser = argparse.ArgumentParser(
        description="Fetch Synaxaria saint biographies for a date."
    )
    parser.add_argument("date", nargs="?", help="MM-DD (default: today).")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args(argv)

    if args.date:
        month, day = (int(p) for p in args.date.split("-"))
    else:
        today = date.today()
        month, day = today.month, today.day

    records = fetch_daily(
        month, day, api_key=args.api_key, force_refresh=args.refresh
    )
    print(f"{month:02d}-{day:02d}: {len(records)} saint records")
    for r in records:
        if not isinstance(r, dict):
            continue
        has = "✓" if (r.get("life_text") or "").strip() else " "
        print(f"  [{has}] {r.get('source'):16} {r.get('name')}")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv[1:]))
