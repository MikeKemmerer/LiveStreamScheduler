#!/usr/bin/env python3
"""GOARCH liturgical calendar data via the official Google Calendar ICS feeds.

The Greek Orthodox Archdiocese of America (GOARCH) publishes its daily liturgical
calendar (commemorations, fasting, and the appointed readings with full text) as
public Google Calendar feeds. Unlike goarch.org, those feeds are hosted on
``calendar.google.com`` and are not behind Cloudflare, so they can be fetched by a
plain HTTP client.

Credit / acknowledgement
------------------------
The discovery that GOARCH's authoritative liturgical data is available through these
ICS feeds — and the specific feed URLs below — comes from the open-source project
**dvogeldev/ortho-cal** (Orthodox Calendar API / GOARCH Liturgical Microservice):
https://github.com/dvogeldev/ortho-cal

That project has no license file, so none of its code is reused here; this is an
independent, dependency-free Python reimplementation. The credit is for identifying
the data source and feed identifiers.

This module fetches and parses those feeds locally (no Node.js service required) and
exposes a small API for building liturgical description blocks.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

# GOARCH public Google Calendar ICS feeds.
# Source of these identifiers: dvogeldev/ortho-cal (see module docstring).
FEED_URLS: dict[str, str] = {
    "en": (
        "https://calendar.google.com/calendar/ical/"
        "i0foh8u5am8ui8grpo1svvaun4%40group.calendar.google.com/public/basic.ics"
    ),
    "gr": (
        "https://calendar.google.com/calendar/ical/"
        "6aaps70c37oadvt5erfvpthmuo%40group.calendar.google.com/public/basic.ics"
    ),
}

_USER_AGENT = "Mozilla/5.0 (LiveStreamScheduler GOARCH calendar fetcher)"
_DEFAULT_CACHE_DIR = Path(__file__).resolve().parent / "cache" / "goarch"
_DEFAULT_CACHE_TTL = 24 * 60 * 60  # 24 hours; the feed updates infrequently.

# Process-lifetime memo of fetched feed text, keyed by language, so repeated
# lookups within one run do not re-read the (~11 MB) feed from disk each time.
_MEM_CACHE: dict[str, str] = {}


@dataclass
class Reading:
    """A single appointed reading."""

    label: str          # e.g. "Epistle", "Gospel", "Matins Gospel"
    citation: str       # e.g. "Acts 2:1-11"
    text: str = ""      # full reading text, if present


@dataclass
class LiturgicalDay:
    """Parsed liturgical information for a single calendar day."""

    day: date
    language: str
    summary_title: str = ""
    saints: list[str] = field(default_factory=list)
    fast: str = ""
    readings: list[Reading] = field(default_factory=list)

    def reading(self, label: str) -> Reading | None:
        target = label.strip().lower()
        for r in self.readings:
            if r.label.lower() == target:
                return r
        return None

    @property
    def epistle(self) -> Reading | None:
        return self.reading("Epistle")

    @property
    def gospel(self) -> Reading | None:
        return self.reading("Gospel")


class GoarchCalendarError(RuntimeError):
    """Raised when the GOARCH feed cannot be fetched or parsed."""


def _cache_path(language: str, cache_dir: Path) -> Path:
    return cache_dir / f"goarch_{language}.ics"


def _read_feed(
    language: str,
    *,
    cache_dir: Path = _DEFAULT_CACHE_DIR,
    cache_ttl: int = _DEFAULT_CACHE_TTL,
    force_refresh: bool = False,
) -> str:
    """Return the raw ICS text for ``language``, using an on-disk cache."""

    language = language.lower()
    if language not in FEED_URLS:
        raise GoarchCalendarError(f"Unknown GOARCH feed language: {language!r}")

    if not force_refresh and language in _MEM_CACHE:
        return _MEM_CACHE[language]

    path = _cache_path(language, cache_dir)
    if (
        not force_refresh
        and path.exists()
        and (time.time() - path.stat().st_mtime) < cache_ttl
    ):
        data = path.read_text(encoding="utf-8")
        _MEM_CACHE[language] = data
        return data

    request = Request(FEED_URLS[language], headers={"User-Agent": _USER_AGENT})
    try:
        with urlopen(request, timeout=40) as response:
            data = response.read().decode("utf-8", errors="replace")
    except Exception as exc:  # network or HTTP failure
        if path.exists():
            # Fall back to a stale cache rather than failing outright.
            data = path.read_text(encoding="utf-8")
            _MEM_CACHE[language] = data
            return data
        raise GoarchCalendarError(
            f"Could not fetch GOARCH {language} feed: {exc}"
        ) from exc

    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(data, encoding="utf-8")
    except OSError:
        pass  # caching is best-effort
    _MEM_CACHE[language] = data
    return data


def _unfold(ics_text: str) -> str:
    """Unfold RFC 5545 line continuations (CRLF followed by space/tab)."""

    return re.sub(r"\r?\n[ \t]", "", ics_text)


def _unescape(value: str) -> str:
    return (
        value.replace("\\n", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
        .strip()
    )


def _find_event(ics_text: str, day: date) -> str | None:
    """Return the raw VEVENT block whose all-day DTSTART matches ``day``.

    GOARCH follows the Revised Julian (New) Calendar, so the feed places fixed
    commemorations on their civil (Gregorian) date. We therefore match on the
    civil ``day`` directly — no Julian/Old-Calendar offset is applied.
    """

    stamp = day.strftime("%Y%m%d")
    blocks = _unfold(ics_text).split("BEGIN:VEVENT")
    for block in blocks[1:]:
        if (
            f"DTSTART;VALUE=DATE:{stamp}" in block
            or f"DTSTART:{stamp}" in block
        ):
            return block
    return None


def _extract_field(event_block: str, key: str) -> str | None:
    match = re.search(
        rf"\n{key}[^:\n]*:(.*?)(?=\r?\n[A-Z][A-Z-]+[;:])",
        event_block,
        re.S,
    )
    if not match:
        return None
    return _unescape(match.group(1))


def parse_description(text: str) -> tuple[list[str], str, list[Reading]]:
    """Parse a GOARCH event DESCRIPTION into saints, fast, and readings.

    The description is a sequence of labeled sections. Reading bodies may
    contain blank lines (paragraph breaks), and GOARCH sometimes glues a
    reading's body text and the *next* ``"<Label> Reading:"`` marker onto a
    single physical line (e.g. ``"...multitude of sins.Gospel Reading: Luke
    4:22-30"``). So rather than scanning line-by-line, this locates every
    reading marker anywhere in the text using a constrained label pattern
    (1-3 capitalized words immediately before ``" Reading:"``) and splits each
    reading's citation (first line) from its body (the rest).
    """

    saints: list[str] = []
    fast = ""
    readings: list[Reading] = []

    saints_re = re.compile(r"^Saints and Feasts:\s*(.+)$", re.I)
    # A reading marker: 1-3 capitalized words (the label) right before "Reading:".
    # This won't be fooled by body sentences because the label has no internal
    # sentence punctuation and must be immediately followed by "Reading:".
    marker_re = re.compile(r"([A-Z][A-Za-z]*(?:\s[A-Z][A-Za-z]*){0,2})\sReading:\s*")

    first = marker_re.search(text)
    preamble = text[: first.start()] if first else text
    body_section = text[first.start():] if first else ""

    # Preamble (before any reading): header, saints line, optional fast note.
    for raw_line in preamble.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if line.lower().startswith("saints, feasts, and readings"):
            continue  # header line
        saints_match = saints_re.match(line)
        if saints_match:
            saints = [s.strip() for s in saints_match.group(1).split(";") if s.strip()]
            continue
        # First standalone non-label line is the fasting note.
        if not fast:
            fast = line

    # Readings: split the body section on each reading marker.
    matches = list(marker_re.finditer(body_section))
    for i, match in enumerate(matches):
        label = match.group(1).strip()
        seg_start = match.end()
        seg_end = matches[i + 1].start() if i + 1 < len(matches) else len(body_section)
        segment = body_section[seg_start:seg_end]
        newline = segment.find("\n")
        if newline == -1:
            citation = segment.strip()
            body = ""
        else:
            citation = segment[:newline].strip()
            body = segment[newline + 1:].strip()
        readings.append(Reading(label=label, citation=citation, text=body))

    return saints, fast, readings

    flush()
    return saints, fast, readings


def get_day(
    day: date,
    *,
    language: str = "en",
    cache_dir: Path = _DEFAULT_CACHE_DIR,
    cache_ttl: int = _DEFAULT_CACHE_TTL,
    force_refresh: bool = False,
) -> LiturgicalDay | None:
    """Return parsed liturgical data for ``day``, or ``None`` if not found."""

    ics_text = _read_feed(
        language,
        cache_dir=cache_dir,
        cache_ttl=cache_ttl,
        force_refresh=force_refresh,
    )
    event = _find_event(ics_text, day)
    if event is None:
        return None

    summary = _extract_field(event, "SUMMARY") or ""
    description = _extract_field(event, "DESCRIPTION") or ""
    saints, fast, readings = parse_description(description)

    return LiturgicalDay(
        day=day,
        language=language,
        summary_title=summary.strip(),
        saints=saints,
        fast=fast,
        readings=readings,
    )


def _abbreviate_citation(citation: str) -> str:
    """Trim GOARCH's verbose scripture book names to the parish's short style.

    e.g. "Acts of the Apostles 2:1-11" -> "Acts 2:1-11"
         "St. Paul's First Letter to the Thessalonians 4:13-17"
             -> "1 Thessalonians 4:13-17"
         "St. Paul's Letter to the Ephesians 5:8-19" -> "Ephesians 5:8-19"
    """

    c = citation.strip()
    c = re.sub(r"^Acts of the Apostles\b", "Acts", c)
    c = re.sub(r"^St\.?\s*Paul'?s First Letter to (?:the )?", "1 ", c)
    c = re.sub(r"^St\.?\s*Paul'?s Second Letter to (?:the )?", "2 ", c)
    c = re.sub(r"^St\.?\s*Paul'?s Letter to (?:the )?", "", c)
    c = re.sub(r"^The First Universal Letter of (?:St\.?\s*)?", "1 ", c)
    c = re.sub(r"^The Second Universal Letter of (?:St\.?\s*)?", "2 ", c)
    c = re.sub(r"^The Third Universal Letter of (?:St\.?\s*)?", "3 ", c)
    c = re.sub(r"^The Universal Letter of (?:St\.?\s*)?", "", c)
    return c.strip()


def format_liturgy_block(
    liturgical_day: LiturgicalDay,
    *,
    include_readings_text: bool = False,
    saint_names: list[str] | None = None,
) -> str:
    """Render a liturgical description block in the parish's template format.

    Structure (matching established Divine Liturgy livestream descriptions)::

        Matins Gospel: John 20:19-23
        Epistle: Acts 2:1-11
        Gospel: John 7:37-52; 8:12

        Today we commemorate:

        • Holy Pentecost
        • Hermias the Martyr at Comana

    The commemoration list defaults to the GOARCH calendar's saints. Pass
    ``saint_names`` to override it (e.g. a list merged with Project Synaxaria
    entries). Saint biographies are intentionally *not* inlined here — they are
    surfaced separately as a reference card for copy/paste, since name spellings
    can differ between sources.

    Liturgical data sourced from the GOARCH calendar; feed discovery credit:
    dvogeldev/ortho-cal (https://github.com/dvogeldev/ortho-cal).
    """

    lines: list[str] = []

    for reading in liturgical_day.readings:
        lines.append(f"{reading.label}: {_abbreviate_citation(reading.citation)}")
        if include_readings_text and reading.text:
            lines.append(reading.text)

    saints = saint_names if saint_names is not None else liturgical_day.saints
    if saints:
        if lines:
            lines.append("")
        lines.append("Today we commemorate:")
        lines.append("")
        for saint in saints:
            lines.append(f"• {saint}")

    return "\n".join(lines)


def _main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Fetch GOARCH liturgical data for a date (via ICS feed)."
    )
    parser.add_argument(
        "date",
        nargs="?",
        help="Date as YYYY-MM-DD (default: today).",
    )
    parser.add_argument("--lang", default="en", choices=sorted(FEED_URLS))
    parser.add_argument("--full-text", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args(argv)

    target = date.fromisoformat(args.date) if args.date else date.today()
    day = get_day(target, language=args.lang, force_refresh=args.refresh)
    if day is None:
        print(f"No GOARCH entry found for {target}")
        return 1

    print(f"{target} — {day.summary_title}\n")
    print(
        format_liturgy_block(
            day,
            include_readings_text=args.full_text,
        )
    )
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv[1:]))
