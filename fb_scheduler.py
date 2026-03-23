#!/usr/bin/env python3
import argparse
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

from youtube_to_facebook_draft import (
    load_json_file,
    normalize_channel_streams_url,
    parse_timestamp,
    run_yt_dlp_json,
    run_yt_dlp_json_streaming,
)


DEFAULT_CALENDAR_URL = "http://your-calendar-server:8000/calendar_cache.json"
DEFAULT_LOCAL_TIMEZONE = "America/Los_Angeles"
YOUTUBE_SCOPE_READONLY = "https://www.googleapis.com/auth/youtube.readonly"
YOUTUBE_SCOPE_WRITE = "https://www.googleapis.com/auth/youtube"


class ConfigError(Exception):
    pass


def read_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ConfigError(f"Invalid JSON in config file: {exc}") from exc
    if not isinstance(cfg, dict):
        raise ConfigError("Config root must be a JSON object")
    return cfg


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off", ""}:
            return False
        return default
    if isinstance(value, (int, float)):
        return value != 0
    if value is None:
        return default
    return bool(value)


def _local_tz(config: dict[str, Any]):
    calendar_cfg = _as_dict(config.get("calendar"))
    tz_name = calendar_cfg.get("timezone", DEFAULT_LOCAL_TIMEZONE)
    if isinstance(tz_name, str) and tz_name and ZoneInfo is not None:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            pass
    return datetime.now().astimezone().tzinfo or timezone.utc


def _extract_video_id(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except Exception:
        return None

    if parsed.netloc.endswith("youtu.be"):
        vid = parsed.path.strip("/")
        return vid or None

    q = parse_qs(parsed.query)
    if "v" in q and q["v"]:
        return q["v"][0]

    return None


def _extract_channel_id_from_url(channel_url: str) -> str | None:
    clean = channel_url.strip()
    if not clean:
        return None
    try:
        parsed = urlparse(clean)
    except Exception:
        return None

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0].lower() == "channel":
        channel_id = parts[1].strip()
        if channel_id:
            return channel_id
    return None


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def _normalize_title_for_compare(text: str) -> str:
    lower = _normalize_whitespace(text).lower()
    return re.sub(r"[^a-z0-9]+", " ", lower).strip()


def _youtube_video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _get_authenticated_channel_info(youtube) -> dict[str, str]:
    payload = youtube.channels().list(part="id,snippet", mine=True, maxResults=1).execute()
    items_obj = payload.get("items") if isinstance(payload, dict) else None
    items = items_obj if isinstance(items_obj, list) else []
    if not items:
        raise RuntimeError("No authenticated YouTube channel found for this OAuth account.")

    item = items[0] if isinstance(items[0], dict) else {}
    channel_id = str(item.get("id") or "").strip()
    snippet_obj = item.get("snippet")
    snippet = snippet_obj if isinstance(snippet_obj, dict) else {}
    title = str(snippet.get("title") or "").strip()
    if not channel_id:
        raise RuntimeError("Authenticated YouTube channel did not return an id.")
    return {"id": channel_id, "title": title}


def _assert_expected_authenticated_channel(youtube, expected_channel_id: str) -> None:
    _authorize_channel_context(youtube, expected_channel_id, allowed_oauth_channel_ids=None)


def _parse_allowed_oauth_channel_ids(value: Any) -> set[str]:
    if isinstance(value, list):
        result: set[str] = set()
        for item in value:
            if isinstance(item, str):
                clean = item.strip()
                if clean:
                    result.add(clean)
        return result
    if isinstance(value, str):
        clean = value.strip()
        return {clean} if clean else set()
    return set()


def _authorize_channel_context(
    youtube,
    expected_channel_id: str,
    allowed_oauth_channel_ids: set[str] | None,
) -> dict[str, str | bool]:
    expected = expected_channel_id.strip()
    if not expected:
        raise RuntimeError("Expected church channel id is required for protected YouTube operations.")

    allowed = allowed_oauth_channel_ids or set()
    current = _get_authenticated_channel_info(youtube)
    current_id = str(current.get("id") or "")
    current_title = str(current.get("title") or "")

    if current_id == expected:
        return {
            "expected_channel_id": expected,
            "oauth_channel_id": current_id,
            "oauth_channel_title": current_title,
            "channel_match_mode": "direct",
            "is_direct_match": True,
        }

    if current_id in allowed:
        return {
            "expected_channel_id": expected,
            "oauth_channel_id": current_id,
            "oauth_channel_title": current_title,
            "channel_match_mode": "allowlisted_editor",
            "is_direct_match": False,
        }

    raise RuntimeError(
        "Authenticated OAuth account does not match configured church channel. "
        f"Expected channel id: {expected}; authenticated channel id: {current_id}; title: {current_title}"
    )


def _load_stream_playlist(root: Path, config: dict[str, Any], refresh_streams: bool, on_log=None) -> tuple[str, dict[str, Any]]:
    youtube_cfg = _as_dict(config.get("youtube"))

    channel_url = youtube_cfg.get("channel_url")
    if not isinstance(channel_url, str) or not channel_url.strip():
        raise ConfigError("Missing required value: youtube.channel_url")
    streams_url = normalize_channel_streams_url(channel_url)

    streams_cache_file = root / "cache" / "streams_flat.json"
    playlist: dict[str, Any] | None = None

    if refresh_streams:
        if on_log:
            on_log(f"Fetching live streams from YouTube: {streams_url}")
            playlist = run_yt_dlp_json_streaming(streams_url, flat_playlist=True, on_line=on_log)
            on_log(f"Fetched {len((playlist or {}).get('entries') or [])} stream entries")
        else:
            playlist = run_yt_dlp_json(streams_url, flat_playlist=True)
        streams_cache_file.parent.mkdir(parents=True, exist_ok=True)
        streams_cache_file.write_text(json.dumps(playlist, ensure_ascii=False, indent=2), encoding="utf-8")
        if on_log:
            on_log("Stream cache updated")
    else:
        if on_log:
            on_log("Loading streams from cache (no refresh requested)")
        playlist = load_json_file(streams_cache_file)
        if playlist is None:
            if on_log:
                on_log("Cache miss — fetching from YouTube")
                playlist = run_yt_dlp_json_streaming(streams_url, flat_playlist=True, on_line=on_log)
            else:
                playlist = run_yt_dlp_json(streams_url, flat_playlist=True)
            streams_cache_file.parent.mkdir(parents=True, exist_ok=True)
            streams_cache_file.write_text(json.dumps(playlist, ensure_ascii=False, indent=2), encoding="utf-8")

    return streams_url, playlist


def list_upcoming_streams(root: Path, config: dict[str, Any], refresh_streams: bool) -> list[dict[str, str]]:
    _, playlist = _load_stream_playlist(root, config, refresh_streams)
    entries = playlist.get("entries") or []
    if not isinstance(entries, list):
        return []

    now_utc = datetime.now(timezone.utc)
    upcoming: list[tuple[datetime, dict[str, Any]]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        when = parse_timestamp(entry)
        if when is None:
            continue

        live_status = (entry.get("live_status") or "").strip().lower()
        if "upcoming" in live_status or when >= now_utc:
            upcoming.append((when, entry))

    upcoming.sort(key=lambda item: item[0])
    tz = datetime.now().astimezone().tzinfo

    result: list[dict[str, str]] = []
    for when, entry in upcoming:
        video_url = str(entry.get("url") or "").strip()
        if not video_url:
            continue
        result.append(
            {
                "video_url": video_url,
                "title": str(entry.get("title") or "Upcoming Livestream").strip(),
                "start_utc": when.isoformat(),
                "start_local": when.astimezone(tz).strftime("%Y-%m-%d %I:%M %p %Z"),
            }
        )

    return result


def load_youtube_upcoming(
    root: Path,
    config: dict[str, Any],
    refresh_streams: bool,
    fetch_video_details: bool,
    selected_video_url: str | None = None,
) -> dict[str, Any]:
    defaults_cfg = _as_dict(config.get("defaults"))

    streams_url, playlist = _load_stream_playlist(root, config, refresh_streams)

    entries = playlist.get("entries") or []
    if not isinstance(entries, list) or not entries:
        raise RuntimeError("No stream entries found on channel streams page")

    upcoming_items = []
    now_utc = datetime.now(timezone.utc)
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        when = parse_timestamp(entry)
        if when is None:
            continue
        live_status = (entry.get("live_status") or "").strip().lower()
        if "upcoming" in live_status or when >= now_utc:
            upcoming_items.append((when, entry))
    upcoming_items.sort(key=lambda item: item[0])

    if not upcoming_items:
        raise RuntimeError("No upcoming YouTube livestream found")

    selected_entry: dict[str, Any] | None = None
    selected_clean = (selected_video_url or "").strip()
    if selected_clean:
        selected_id = _extract_video_id(selected_clean)
        for _, entry in upcoming_items:
            entry_url = str(entry.get("url") or "").strip()
            if not entry_url:
                continue
            if entry_url == selected_clean:
                selected_entry = entry
                break
            if selected_id and _extract_video_id(entry_url) == selected_id:
                selected_entry = entry
                break
        if selected_entry is None:
            raise RuntimeError("Selected YouTube stream is not in the upcoming streams list")
    else:
        selected_entry = upcoming_items[0][1]

    if selected_entry is None:
        raise RuntimeError("Selected YouTube stream could not be resolved")

    video_url = str(selected_entry.get("url") or "").strip()
    if not video_url:
        raise RuntimeError("Selected upcoming stream missing video URL")

    video: dict[str, Any] = selected_entry
    if fetch_video_details:
        try:
            video = run_yt_dlp_json(video_url)
        except RuntimeError:
            video = selected_entry

    yt_title = (video.get("title") or selected_entry.get("title") or "Upcoming Livestream").strip()
    yt_description = (video.get("description") or selected_entry.get("description") or "").strip()
    yt_start = parse_timestamp(video) or parse_timestamp(selected_entry)
    if yt_start is None:
        raise RuntimeError("Could not determine YouTube scheduled start time")

    include_link = _as_bool(defaults_cfg.get("include_youtube_link_in_description", True), default=True)
    if include_link:
        if yt_description:
            yt_description += "\n\n"
        yt_description += f"Watch on YouTube: {video_url}"

    return {
        "streams_url": streams_url,
        "video_url": video_url,
        "title": yt_title,
        "description": yt_description,
        "yt_start": yt_start,
    }


def _parse_event_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _fetch_json_url(url: str, timeout_seconds: int = 12) -> Any:
    request = Request(url, method="GET")
    request.add_header("Accept", "application/json")
    with urlopen(request, timeout=timeout_seconds) as response:
        body = response.read().decode("utf-8", errors="replace")
    return json.loads(body)


def _load_calendar_events(calendar_url: str) -> tuple[list[dict[str, Any]], str]:
    payload = _fetch_json_url(calendar_url)

    events: Any
    if isinstance(payload, dict):
        events = payload.get("events")
    else:
        events = payload

    if not isinstance(events, list):
        raise RuntimeError(f"Calendar payload at {calendar_url} did not contain an events list")

    result: list[dict[str, Any]] = []
    for item in events:
        if isinstance(item, dict):
            result.append(item)
    return result, calendar_url


def _normalize_service_summary(summary: str) -> str:
    clean = summary.strip()
    if " - " in clean:
        clean = clean.split(" - ", 1)[0].strip()
    lower = clean.lower()
    if lower in {"9th hour", "9th hour prayers"}:
        return "9th Hour Prayers"
    if "presanctified" in lower or "pre-sanctified" in lower:
        return "Pre-Sanctified Divine Liturgy"
    if "divine liturgy" in lower:
        return "Divine Liturgy"
    if "orthros" in lower:
        return "Orthros"
    if "great vespers" in lower:
        return "Great Vespers"
    if "great compline" in lower:
        return "Great Compline"
    if "akathist" in lower:
        return "Akathist Hymn"
    return clean


def _service_label_from_names(names: list[str]) -> str:
    ordered: list[str] = []
    for name in names:
        n = _normalize_service_summary(name)
        if n and n not in ordered:
            ordered.append(n)

    if "Orthros" in ordered and "Divine Liturgy" in ordered:
        return "Orthros & Divine Liturgy"
    if "9th Hour Prayers" in ordered and "Pre-Sanctified Divine Liturgy" in ordered:
        return "9th Hour Prayers & Pre-Sanctified Divine Liturgy"
    if not ordered:
        return "Service"
    if len(ordered) == 1:
        return ordered[0]
    return " & ".join(ordered)


def _service_tokens(value: str) -> set[str]:
    lower = value.lower()
    tokens: set[str] = set()
    if "divine liturgy" in lower:
        tokens.add("divine_liturgy")
    if "orthros" in lower:
        tokens.add("orthros")
    if "presanctified" in lower or "pre-sanctified" in lower:
        tokens.add("presanctified_liturgy")
    if "9th hour" in lower:
        tokens.add("ninth_hour_prayers")
    if "great vespers" in lower:
        tokens.add("great_vespers")
    if "great compline" in lower:
        tokens.add("great_compline")
    if "akathist" in lower:
        tokens.add("akathist_hymn")
    return tokens


def _extract_service_from_stream_title(title: str) -> str:
    parts = [p.strip() for p in title.split(" • ") if p.strip()]
    if len(parts) >= 3:
        return parts[1]
    if len(parts) == 2:
        return parts[0]
    return title


def _parse_title_date(title: str, tz) -> date | None:
    parts = [p.strip() for p in title.split(" • ") if p.strip()]
    if not parts:
        return None
    candidate = parts[-1]
    try:
        dt = datetime.strptime(candidate, "%B %d, %Y")
    except ValueError:
        return None
    return dt.replace(tzinfo=tz).date()


def _build_service_blocks(
    events: list[dict[str, Any]],
    tz,
    now_utc: datetime,
    coverage_days: int,
    gap_minutes: int,
) -> list[dict[str, Any]]:
    local_today = now_utc.astimezone(tz).date()
    last_day = local_today + timedelta(days=max(coverage_days - 1, 0))
    gap = timedelta(minutes=gap_minutes)

    service_events: list[dict[str, Any]] = []
    for event in events:
        if event.get("calendar") != "Services" or event.get("allDay"):
            continue

        start_dt = _parse_event_datetime(event.get("start"))
        end_dt = _parse_event_datetime(event.get("end"))
        if not start_dt or not end_dt:
            continue
        if end_dt < start_dt:
            end_dt = start_dt

        start_local = start_dt.astimezone(tz)
        local_day = start_local.date()
        if local_day < local_today or local_day > last_day:
            continue

        service_events.append(
            {
                "summary": str(event.get("summary") or "").strip(),
                "start": start_dt,
                "end": end_dt,
                "local_day": local_day,
            }
        )

    service_events.sort(key=lambda item: item["start"])

    blocks: list[dict[str, Any]] = []
    for item in service_events:
        if not blocks:
            blocks.append(
                {
                    "start": item["start"],
                    "end": item["end"],
                    "local_day": item["local_day"],
                    "services": [item["summary"]],
                    "events": [item],
                }
            )
            continue

        current = blocks[-1]
        if item["start"] <= current["end"] + gap:
            current["end"] = max(current["end"], item["end"])
            current["services"].append(item["summary"])
            current["events"].append(item)
        else:
            blocks.append(
                {
                    "start": item["start"],
                    "end": item["end"],
                    "local_day": item["local_day"],
                    "services": [item["summary"]],
                    "events": [item],
                }
            )

    for block in blocks:
        label = _service_label_from_names(block["services"])
        block["service_label"] = label
        block["service_tokens"] = _service_tokens(label)
        block["divine_liturgy"] = "divine_liturgy" in block["service_tokens"]

    return blocks


def _build_stream_index(entries: list[dict[str, Any]], tz) -> list[dict[str, Any]]:
    indexed: list[dict[str, Any]] = []
    for entry in entries:
        when = parse_timestamp(entry)
        title = str(entry.get("title") or "").strip()
        if not title:
            continue

        if when is not None:
            local_day = when.astimezone(tz).date()
        else:
            local_day = _parse_title_date(title, tz)
            if local_day is None:
                continue

        service_from_title = _extract_service_from_stream_title(title)
        normalized_service = _service_label_from_names([service_from_title])

        indexed.append(
            {
                "title": title,
                "url": str(entry.get("url") or "").strip(),
                "local_day": local_day,
                "service_label": normalized_service,
                "service_tokens": _service_tokens(normalized_service),
            }
        )
    return indexed


def _find_announcement_for_day(events: list[dict[str, Any]], target_day: date) -> str:
    for event in events:
        if event.get("calendar") != "Announcements":
            continue
        start_val = event.get("start")
        if not isinstance(start_val, str):
            continue
        try:
            event_day = date.fromisoformat(start_val.split("T", 1)[0])
        except ValueError:
            continue
        if event_day == target_day:
            summary = str(event.get("summary") or "").strip()
            if summary:
                return summary
    return ""


def _is_all_day_event_on_day(event: dict[str, Any], target_day: date) -> bool:
    if not event.get("allDay"):
        return False
    start_val = event.get("start")
    if not isinstance(start_val, str):
        return False
    try:
        event_day = date.fromisoformat(start_val.split("T", 1)[0])
    except ValueError:
        return False
    return event_day == target_day


def _is_feast_day_candidate(event: dict[str, Any]) -> bool:
    calendar_name = str(event.get("calendar") or "").strip()
    summary = str(event.get("summary") or "").strip()
    summary_lower = summary.lower()

    if not summary:
        return False
    if summary_lower.startswith(("epistle:", "gospel:", "matins gospel:")):
        return False

    # Use exact calendar names from calendar_cache.json only.
    if calendar_name == "Feast Days":
        return True
    if calendar_name == "Announcements":
        return True
    return False


def _find_feast_day_entries_for_day(events: list[dict[str, Any]], target_day: date) -> list[str]:
    entries: list[str] = []

    for event in events:
        if not _is_all_day_event_on_day(event, target_day):
            continue
        if not _is_feast_day_candidate(event):
            continue

        summary = str(event.get("summary") or "").strip()
        if not summary:
            continue
        if summary not in entries:
            entries.append(summary)

    return entries


def _fit_title_parts(parts: list[str], max_length: int = 100) -> str:
    used: list[str] = []
    current = ""
    for part in parts:
        clean = part.strip()
        if not clean or clean in used:
            continue
        candidate = clean if not current else f"{current}; {clean}"
        if len(candidate) > max_length:
            break
        current = candidate
        used.append(clean)
    return current


def _build_title_with_extras(base: str, extras: list[str], max_length: int = 100) -> str:
    title = base.strip()
    if not title:
        return ""

    for part in extras:
        clean = part.strip()
        if not clean:
            continue
        candidate = f"{title}; {clean}"
        if len(candidate) > max_length:
            break
        title = candidate
    return title


def _format_calendar_date(target_day: date) -> str:
    return f"{target_day.month}/{target_day.day}/{target_day.year}"


def _format_long_date(target_day: date) -> str:
    return f"{target_day.strftime('%B')} {target_day.day}, {target_day.year}"


def _title_metadata_day(block: dict[str, Any], tz) -> date:
    local_day = block["local_day"]
    service_label = str(block.get("service_label") or "")
    local_start = block.get("start")
    if isinstance(local_start, datetime):
        local_hour = local_start.astimezone(tz).hour
    else:
        local_hour = 0

    # Evening vespers should use the next day's feast/announcement metadata.
    if "vespers" in service_label.lower() and local_hour >= 15:
        return local_day + timedelta(days=1)
    return local_day


def _draft_title(block: dict[str, Any], events: list[dict[str, Any]]) -> str:
    tz = datetime.now().astimezone().tzinfo or timezone.utc
    local_day = block["local_day"]
    title_day = _title_metadata_day(block, tz)
    occasion = _find_announcement_for_day(events, title_day)
    service_label = str(block.get("service_label") or "Divine Liturgy")
    date_str = _format_long_date(local_day)

    # Always include Service + Date first, then append metadata that still fits.
    base = f"{service_label} • {date_str}"

    # Divine Liturgy title format: Announcement; Feast Day 1; Feast Day 2 ... (<= 100 chars)
    if block.get("divine_liturgy"):
        feast_entries = _find_feast_day_entries_for_day(events, title_day)
        extras: list[str] = []
        if occasion:
            extras.append(occasion)
        extras.extend(feast_entries)
        fitted = _build_title_with_extras(base, extras, max_length=100)
        if fitted:
            return fitted

    # Vespers titles should also include the next day's announcement/feast context.
    if "vespers" in service_label.lower():
        feast_entries = _find_feast_day_entries_for_day(events, title_day)
        extras: list[str] = []
        if occasion:
            extras.append(occasion)
        extras.extend(feast_entries)
        return _build_title_with_extras(base, extras, max_length=100)

    extras: list[str] = [occasion] if occasion else []
    return _build_title_with_extras(base, extras, max_length=100)


def _draft_description(block: dict[str, Any], tz, title_line: str) -> str:
    local_day = block["local_day"]
    chapel_link = f"https://www.goarch.org/chapel?date={_format_calendar_date(local_day)}"
    lines = [
        title_line,
        "",
        f"Chapel readings and service information: {chapel_link}",
    ]

    if local_day.weekday() == 6:
        lines.extend(
            [
                "",
                "Sunday School lesson resource:",
                "https://www.goarch.org/departments/religioused/sermons/kids",
            ]
        )

    return "\n".join(lines)


def _service_block_id(service_label: str, start_utc: datetime) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", service_label.lower()).strip("-") or "service"
    start_part = start_utc.strftime("%Y%m%dT%H%M%SZ")
    return f"{start_part}-{slug}"


def build_calendar_youtube_coverage_report(
    root: Path,
    config: dict[str, Any],
    refresh_streams: bool,
    calendar_url: str,
    coverage_days: int,
    gap_minutes: int,
    on_log=None,
) -> dict[str, Any]:
    tz = _local_tz(config)
    now_utc = datetime.now(timezone.utc)

    if on_log:
        on_log(f"Fetching calendar from {calendar_url}")
    events, calendar_url_used = _load_calendar_events(calendar_url)
    if on_log:
        on_log(f"Loaded {len(events)} calendar events")
    blocks = _build_service_blocks(events, tz=tz, now_utc=now_utc, coverage_days=coverage_days, gap_minutes=gap_minutes)
    if on_log:
        on_log(f"Built {len(blocks)} service blocks for next {coverage_days} days")

    _, playlist = _load_stream_playlist(root, config, refresh_streams, on_log=on_log)
    entries_obj = playlist.get("entries")
    entries: list[dict[str, Any]] = entries_obj if isinstance(entries_obj, list) else []
    stream_index = _build_stream_index(entries, tz=tz)
    if on_log:
        on_log(f"Indexed {len(stream_index)} YouTube streams")
        on_log("Matching service blocks to streams...")

    matched_services: list[dict[str, Any]] = []
    missing_services: list[dict[str, Any]] = []
    used_stream_indexes: set[int] = set()

    for block in blocks:
        block_day = block["local_day"]

        matched_stream: dict[str, Any] | None = None
        matched_stream_index: int | None = None
        block_tokens = block.get("service_tokens")
        token_set = block_tokens if isinstance(block_tokens, set) else set()

        for idx, stream in enumerate(stream_index):
            if idx in used_stream_indexes:
                continue
            if stream["local_day"] != block_day:
                continue

            stream_tokens = stream.get("service_tokens")
            stream_token_set = stream_tokens if isinstance(stream_tokens, set) else set()

            if token_set and stream_token_set and token_set.intersection(stream_token_set):
                matched_stream = stream
                matched_stream_index = idx
                break

            stream_label = str(stream.get("service_label") or "").lower()
            block_label = str(block.get("service_label") or "").lower()
            if block_label and block_label in stream_label:
                matched_stream = stream
                matched_stream_index = idx
                break

        if matched_stream is not None:
            if matched_stream_index is not None:
                used_stream_indexes.add(matched_stream_index)
            matched_services.append(
                {
                    "date": _format_long_date(block_day),
                    "service_label": block["service_label"],
                    "youtube_title": matched_stream["title"],
                    "youtube_url": matched_stream["url"],
                }
            )
            continue

        local_start = block["start"].astimezone(tz)
        local_end = block["end"].astimezone(tz)
        service_label = str(block.get("service_label") or "Service")
        display_date = _format_long_date(block_day)
        title_base = f"{service_label} • {display_date}"
        title_day = _title_metadata_day(block, tz)
        announcement_option = _find_announcement_for_day(events, title_day)
        feast_options = _find_feast_day_entries_for_day(events, title_day)
        draft_title = _draft_title(block, events)
        missing_services.append(
            {
                "service_block_id": _service_block_id(service_label, block["start"].astimezone(timezone.utc)),
                "date": display_date,
                "service_label": service_label,
                "start_utc": block["start"].astimezone(timezone.utc).isoformat(),
                "end_utc": block["end"].astimezone(timezone.utc).isoformat(),
                "start_local": local_start.strftime("%Y-%m-%d %I:%M %p %Z"),
                "end_local": local_end.strftime("%Y-%m-%d %I:%M %p %Z"),
                "chapel_url": f"https://www.goarch.org/chapel?date={_format_calendar_date(block_day)}",
                "kids_url": "https://www.goarch.org/departments/religioused/sermons/kids" if block_day.weekday() == 6 else "",
                "title": draft_title,
                "title_base": title_base,
                "title_announcement_option": announcement_option,
                "title_feast_options": feast_options,
                "description": title_base,
            }
        )

    if on_log:
        on_log(f"Done — {len(matched_services)} matched, {len(missing_services)} missing")

    return {
        "created_at_utc": now_utc.isoformat(),
        "calendar_url": calendar_url_used,
        "calendar_url_requested": calendar_url,
        "coverage_days": coverage_days,
        "gap_minutes": gap_minutes,
        "total_service_blocks": len(blocks),
        "service_blocks_total": len(matched_services) + len(missing_services),
        "service_blocks_matched": len(matched_services),
        "service_blocks_missing": len(missing_services),
        "matched_services": matched_services,
        "missing_services": missing_services,
        # Backward-compatible aliases for existing consumers.
        "divine_blocks_total": len(matched_services) + len(missing_services),
        "divine_blocks_matched": len(matched_services),
        "divine_blocks_missing": len(missing_services),
        "matched_divine": matched_services,
        "missing_divine": missing_services,
    }


def write_calendar_youtube_coverage_markdown(root: Path, report: dict[str, Any]) -> Path:
    analysis_dir = root / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    md_path = analysis_dir / "calendar_youtube_coverage.md"

    markdown = [
        "# Calendar to YouTube Coverage Report",
        "",
        f"Generated (UTC): {report.get('created_at_utc')}",
        f"Calendar Source: {report.get('calendar_url')}",
        f"Coverage Window (days): {report.get('coverage_days')}",
        f"Merge Gap (minutes): {report.get('gap_minutes')}",
        "",
        "## Summary",
        f"- Total Service Blocks: {report.get('total_service_blocks')}",
        f"- Service Blocks Considered: {report.get('service_blocks_total', report.get('divine_blocks_total'))}",
        f"- Already Scheduled on YouTube: {report.get('service_blocks_matched', report.get('divine_blocks_matched'))}",
        f"- Missing YouTube Schedule: {report.get('service_blocks_missing', report.get('divine_blocks_missing'))}",
        "",
    ]

    matched_obj = report.get("matched_services")
    if not isinstance(matched_obj, list):
        matched_obj = report.get("matched_divine")
    matched = matched_obj if isinstance(matched_obj, list) else []
    if matched:
        markdown.extend(["## Already Scheduled", ""])
        for item in matched:
            if not isinstance(item, dict):
                continue
            markdown.extend(
                [
                    f"- {item.get('date')}: {item.get('service_label')}",
                    f"  - YouTube Title: {item.get('youtube_title')}",
                    f"  - YouTube URL: {item.get('youtube_url')}",
                ]
            )
        markdown.append("")

    missing_obj = report.get("missing_services")
    if not isinstance(missing_obj, list):
        missing_obj = report.get("missing_divine")
    missing = missing_obj if isinstance(missing_obj, list) else []
    markdown.extend(["## Missing Service Streams", ""])
    if not missing:
        markdown.append("All service blocks in the coverage window already have matching YouTube streams.")
        markdown.append("")
    else:
        for idx, item in enumerate(missing, start=1):
            if not isinstance(item, dict):
                continue
            markdown.extend(
                [
                    f"### Draft {idx}",
                    f"- Date: {item.get('date')}",
                    f"- Service: {item.get('service_label')}",
                    f"- Service Window: {item.get('start_local')} - {item.get('end_local')}",
                    f"- Chapel Link: {item.get('chapel_url')}",
                ]
            )
            kids_url = str(item.get("kids_url") or "").strip()
            if kids_url:
                markdown.append(f"- Sunday School Link: {kids_url}")
            markdown.extend(
                [
                    "",
                    "#### Title",
                    str(item.get("title") or ""),
                    "",
                    "#### Core Description",
                    str(item.get("description") or ""),
                    "",
                ]
            )

    md_path.write_text("\n".join(markdown), encoding="utf-8")
    return md_path


def build_producer_pack(source: dict[str, Any], fb_start: datetime, fb_lead_minutes: int) -> dict[str, Any]:
    local_tz = datetime.now().astimezone().tzinfo
    fb_local = fb_start.astimezone(local_tz)
    yt_start = source["yt_start"]
    yt_local = yt_start.astimezone(local_tz)

    return {
        "title": source["title"],
        "description": source["description"],
        "facebook_start_utc": fb_start.isoformat(),
        "facebook_start_local": fb_local.strftime("%Y-%m-%d %I:%M %p %Z"),
        "youtube_start_utc": yt_start.isoformat(),
        "youtube_start_local": yt_local.strftime("%Y-%m-%d %I:%M %p %Z"),
        "lead_minutes": fb_lead_minutes,
        "youtube_url": source["video_url"],
        "producer_url": "https://business.facebook.com/live/producer/v2",
        "checklist": [
            "Open Facebook Live Producer URL",
            "Create a scheduled live video event",
            "Paste title and description from this producer pack",
            "Set start time to the Facebook local/UTC time shown",
            "Confirm your persistent stream key/profile is selected",
            "Save or schedule the event",
        ],
    }


def build_result(
    root: Path,
    config: dict[str, Any],
    refresh_streams: bool,
    fetch_video_details: bool,
    fb_lead_minutes: int,
    selected_video_url: str | None = None,
) -> dict[str, Any]:
    source = load_youtube_upcoming(
        root,
        config,
        refresh_streams=refresh_streams,
        fetch_video_details=fetch_video_details,
        selected_video_url=selected_video_url,
    )

    yt_start = source["yt_start"]
    fb_start = yt_start - timedelta(minutes=fb_lead_minutes)
    producer_pack = build_producer_pack(source, fb_start=fb_start, fb_lead_minutes=fb_lead_minutes)

    now = datetime.now(timezone.utc)
    return {
        "created_at_utc": now.isoformat(),
        "manual_only": True,
        "youtube": {
            "streams_url": source["streams_url"],
            "video_url": source["video_url"],
            "title": source["title"],
            "start_utc": yt_start.isoformat(),
        },
        "facebook": {
            "start_utc": fb_start.isoformat(),
            "lead_minutes": fb_lead_minutes,
            "producer_pack": producer_pack,
            "request_result": {
                "mode": "manual_producer_pack",
                "path": producer_pack["producer_url"],
            },
        },
    }


def write_outputs(root: Path, result: dict[str, Any]) -> None:
    analysis_dir = root / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    json_path = analysis_dir / "facebook_schedule_result.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    yt_obj = result.get("youtube")
    yt = yt_obj if isinstance(yt_obj, dict) else None
    fb = _as_dict(result.get("facebook"))
    producer_pack_obj = fb.get("producer_pack")
    producer_pack = producer_pack_obj if isinstance(producer_pack_obj, dict) else None

    markdown = [
        "# Facebook Scheduling Result",
        "",
    ]

    if yt is not None:
        markdown.extend(
            [
                "## Source YouTube Stream",
                f"- Title: {yt.get('title')}",
                f"- URL: {yt.get('video_url')}",
                f"- Start (UTC): {yt.get('start_utc')}",
                "",
                "## Facebook Schedule",
                f"- Start (UTC): {fb.get('start_utc')}",
                f"- Lead Minutes: {fb.get('lead_minutes')}",
                "- Mode: Manual Producer Pack",
                "",
            ]
        )

    if producer_pack is not None:
        markdown.extend(
            [
                "## Producer Pack",
                f"- Producer URL: {producer_pack.get('producer_url')}",
                f"- Facebook Start (Local): {producer_pack.get('facebook_start_local')}",
                f"- Facebook Start (UTC): {producer_pack.get('facebook_start_utc')}",
                f"- YouTube Start (Local): {producer_pack.get('youtube_start_local')}",
                f"- Lead Minutes: {producer_pack.get('lead_minutes')}",
                "",
                "### Copy Title",
                str(producer_pack.get("title") or ""),
                "",
                "### Copy Description",
                str(producer_pack.get("description") or ""),
                "",
                "### Checklist",
            ]
        )

        checklist = producer_pack.get("checklist")
        if isinstance(checklist, list):
            for item in checklist:
                markdown.append(f"- {item}")
            markdown.append("")

    md_path = analysis_dir / "facebook_schedule_result.md"
    md_path.write_text("\n".join(markdown), encoding="utf-8")


def list_live_broadcasts_with_service_account(key_file: Path, max_results: int = 5) -> dict[str, Any]:
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
    except Exception as exc:
        raise RuntimeError(
            "Missing Google API dependencies. Install: pip install google-api-python-client google-auth"
        ) from exc

    if not key_file.exists():
        raise ConfigError(f"Service account key file not found: {key_file}")

    scopes = [YOUTUBE_SCOPE_READONLY]

    try:
        creds = service_account.Credentials.from_service_account_file(str(key_file), scopes=scopes)
        youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
        response = youtube.liveBroadcasts().list(
            part="id,snippet,status",
            mine=True,
            maxResults=max(1, min(max_results, 50)),
        ).execute()
        return response if isinstance(response, dict) else {}
    except HttpError as exc:
        body = exc.content.decode("utf-8", errors="replace") if getattr(exc, "content", None) else "<no-body>"
        raise RuntimeError(
            "YouTube API request failed with service account credentials. "
            "This usually means the channel is not accessible via service account (normal for YouTube channels). "
            f"HTTP error: {exc}; body: {body}"
        ) from exc


def list_live_broadcasts_with_user_oauth(
    client_secret_file: Path,
    token_file: Path,
    max_results: int = 5,
    open_browser: bool = False,
) -> dict[str, Any]:
    try:
        from google.auth.transport.requests import Request as GoogleRequest
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
    except Exception as exc:
        raise RuntimeError(
            "Missing Google OAuth dependencies. Install: pip install google-api-python-client google-auth google-auth-oauthlib"
        ) from exc

    if not client_secret_file.exists():
        raise ConfigError(f"OAuth client secret file not found: {client_secret_file}")

    scopes = [YOUTUBE_SCOPE_READONLY]
    creds: Any = None

    if token_file.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_file), scopes=scopes)
        except Exception:
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(GoogleRequest())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_file), scopes=scopes)
            creds = flow.run_local_server(port=0, open_browser=open_browser)

        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(creds.to_json(), encoding="utf-8")

    try:
        youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
        response = youtube.liveBroadcasts().list(
            part="id,snippet,status",
            mine=True,
            maxResults=max(1, min(max_results, 50)),
        ).execute()
        return response if isinstance(response, dict) else {}
    except HttpError as exc:
        body = exc.content.decode("utf-8", errors="replace") if getattr(exc, "content", None) else "<no-body>"
        raise RuntimeError(
            "YouTube API request failed with user OAuth credentials. "
            f"HTTP error: {exc}; body: {body}"
        ) from exc


def _build_youtube_client_from_user_oauth(
    client_secret_file: Path,
    token_file: Path,
    scopes: list[str],
    open_browser: bool = False,
):
    try:
        from google.auth.transport.requests import Request as GoogleRequest
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except Exception as exc:
        raise RuntimeError(
            "Missing Google OAuth dependencies. Install: pip install google-api-python-client google-auth google-auth-oauthlib"
        ) from exc

    if not client_secret_file.exists():
        raise ConfigError(f"OAuth client secret file not found: {client_secret_file}")

    creds: Any = None
    if token_file.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_file), scopes=scopes)
        except Exception:
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(GoogleRequest())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_file), scopes=scopes)
            creds = flow.run_local_server(port=0, open_browser=open_browser)

        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(creds.to_json(), encoding="utf-8")

    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def list_channel_playlists_with_user_oauth(
    client_secret_file: Path,
    token_file: Path,
    expected_channel_id: str,
    allowed_oauth_channel_ids: set[str] | None = None,
    max_results: int = 50,
    open_browser: bool = False,
) -> list[dict[str, Any]]:
    try:
        from googleapiclient.errors import HttpError
    except Exception as exc:
        raise RuntimeError(
            "Missing Google API dependencies. Install: pip install google-api-python-client google-auth google-auth-oauthlib"
        ) from exc

    youtube = _build_youtube_client_from_user_oauth(
        client_secret_file=client_secret_file,
        token_file=token_file,
        scopes=[YOUTUBE_SCOPE_WRITE],
        open_browser=open_browser,
    )
    _authorize_channel_context(youtube, expected_channel_id, allowed_oauth_channel_ids=allowed_oauth_channel_ids)

    try:
        response = youtube.playlists().list(
            part="id,snippet,contentDetails",
            channelId=expected_channel_id,
            maxResults=max(1, min(max_results, 50)),
        ).execute()
    except HttpError as exc:
        body = exc.content.decode("utf-8", errors="replace") if getattr(exc, "content", None) else "<no-body>"
        raise RuntimeError(f"YouTube playlist listing failed. HTTP error: {exc}; body: {body}") from exc

    items_obj = response.get("items") if isinstance(response, dict) else None
    items = items_obj if isinstance(items_obj, list) else []
    playlists: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        playlist_id = str(item.get("id") or "").strip()
        snippet_obj = item.get("snippet")
        snippet = snippet_obj if isinstance(snippet_obj, dict) else {}
        details_obj = item.get("contentDetails")
        details = details_obj if isinstance(details_obj, dict) else {}
        title = str(snippet.get("title") or "").strip()
        if not playlist_id or not title:
            continue
        item_count = details.get("itemCount")
        playlists.append(
            {
                "id": playlist_id,
                "title": title,
                "item_count": int(item_count) if isinstance(item_count, int) else None,
            }
        )

    playlists.sort(key=lambda p: str(p.get("title") or "").lower())
    return playlists


def _find_duplicate_upcoming_broadcast(
    youtube,
    title: str,
    scheduled_start_utc: datetime,
    max_start_delta_minutes: int = 30,
) -> dict[str, Any] | None:
    response = youtube.liveBroadcasts().list(
        part="id,snippet,status",
        mine=True,
        maxResults=50,

    ).execute()

    items_obj = response.get("items") if isinstance(response, dict) else None
    items = items_obj if isinstance(items_obj, list) else []
    normalized_target_title = _normalize_title_for_compare(title)

    for item in items:
        if not isinstance(item, dict):
            continue
        snippet_obj = item.get("snippet")
        snippet = snippet_obj if isinstance(snippet_obj, dict) else {}
        status_obj = item.get("status")
        status = status_obj if isinstance(status_obj, dict) else {}
        life_cycle = str(status.get("lifeCycleStatus") or "").strip().lower()
        if life_cycle not in {"ready", "live", "testing", "created"}:
            continue

        existing_title = str(snippet.get("title") or "").strip()
        if _normalize_title_for_compare(existing_title) != normalized_target_title:
            continue

        existing_start = _parse_event_datetime(snippet.get("scheduledStartTime"))
        if existing_start is None:
            continue

        delta_minutes = abs((existing_start - scheduled_start_utc).total_seconds()) / 60.0
        if delta_minutes <= max_start_delta_minutes:
            return item

    return None


def _resolve_default_stream_id(youtube) -> str:
    response = youtube.liveStreams().list(part="id,snippet,status", mine=True, maxResults=50).execute()
    items_obj = response.get("items") if isinstance(response, dict) else None
    items = items_obj if isinstance(items_obj, list) else []

    if not items:
        raise RuntimeError("No reusable live stream ingest profiles were found on this channel.")

    usable: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        stream_id = str(item.get("id") or "").strip()
        if not stream_id:
            continue
        status_obj = item.get("status")
        status = status_obj if isinstance(status_obj, dict) else {}
        stream_status = str(status.get("streamStatus") or "").strip().lower()
        if stream_status and stream_status not in {"active", "inactive", "ready"}:
            continue
        snippet_obj = item.get("snippet")
        snippet = snippet_obj if isinstance(snippet_obj, dict) else {}
        title = str(snippet.get("title") or "").strip().lower()
        usable.append({"id": stream_id, "title": title})

    if not usable:
        raise RuntimeError("No usable live stream ingest profiles were found on this channel.")

    usable.sort(key=lambda stream: str(stream.get("title") or ""))
    return str(usable[0]["id"])


def append_schedule_operation_log(root: Path, payload: dict[str, Any]) -> Path:
    analysis_dir = root / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    log_path = analysis_dir / "youtube_schedule_operations.jsonl"
    line = json.dumps(payload, ensure_ascii=False)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.write("\n")
    return log_path


def schedule_missing_service_with_user_oauth(
    root: Path,
    title: str,
    description: str,
    scheduled_start_utc: datetime,
    playlist_id: str,
    service_block_id: str,
    client_secret_file: Path,
    token_file: Path,
    expected_channel_id: str,
    allowed_oauth_channel_ids: set[str] | None = None,
    open_browser: bool = False,
) -> dict[str, Any]:
    try:
        from googleapiclient.errors import HttpError
    except Exception as exc:
        raise RuntimeError(
            "Missing Google API dependencies. Install: pip install google-api-python-client google-auth google-auth-oauthlib"
        ) from exc

    clean_title = _normalize_whitespace(title).strip()
    clean_description = description.strip()
    clean_playlist_id = playlist_id.strip()
    if not clean_title:
        raise RuntimeError("Title is required to schedule a stream.")
    if not clean_description:
        raise RuntimeError("Description is required to schedule a stream.")
    if not clean_playlist_id:
        raise RuntimeError("Playlist selection is required.")

    youtube = _build_youtube_client_from_user_oauth(
        client_secret_file=client_secret_file,
        token_file=token_file,
        scopes=[YOUTUBE_SCOPE_WRITE],
        open_browser=open_browser,
    )
    auth_context = _authorize_channel_context(
        youtube,
        expected_channel_id,
        allowed_oauth_channel_ids=allowed_oauth_channel_ids,
    )
    auth_mode = str(auth_context.get("channel_match_mode") or "")
    if auth_mode != "direct":
        oauth_id = str(auth_context.get("oauth_channel_id") or "")
        oauth_title = str(auth_context.get("oauth_channel_title") or "")
        raise RuntimeError(
            "Scheduling requires OAuth identity to be the church channel itself. "
            "Current OAuth identity is allowlisted for guarded access but cannot be used for write scheduling. "
            f"Expected channel id: {expected_channel_id.strip()}; authenticated channel id: {oauth_id}; title: {oauth_title}. "
            "Re-authorize by selecting the church/brand channel identity in the Google consent flow."
        )

    duplicate = _find_duplicate_upcoming_broadcast(youtube, title=clean_title, scheduled_start_utc=scheduled_start_utc)
    if duplicate is not None:
        dup_id = str(duplicate.get("id") or "").strip()
        dup_snippet_obj = duplicate.get("snippet")
        dup_snippet = dup_snippet_obj if isinstance(dup_snippet_obj, dict) else {}
        dup_title = str(dup_snippet.get("title") or "").strip() or clean_title
        dup_url = _youtube_video_url(dup_id) if dup_id else ""
        raise RuntimeError(f"Duplicate broadcast appears to already exist: {dup_title} {dup_url}".strip())

    stream_id = _resolve_default_stream_id(youtube)
    start_iso = scheduled_start_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    end_iso = (scheduled_start_utc.astimezone(timezone.utc) + timedelta(hours=2)).isoformat().replace("+00:00", "Z")

    request_body = {
        "snippet": {
            "title": clean_title,
            "description": clean_description,
            "scheduledStartTime": start_iso,
            "scheduledEndTime": end_iso,
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
        "contentDetails": {
            "enableAutoStart": False,
            "enableAutoStop": False,
            "enableDvr": True,
            "recordFromStart": True,
            "enableEmbed": True,
            "enableLiveChat": True,
            "enableLiveChatReplay": True,
        },
    }

    try:
        created = youtube.liveBroadcasts().insert(
            part="snippet,status,contentDetails",
            body=request_body,
        ).execute()
    except HttpError as exc:
        body = exc.content.decode("utf-8", errors="replace") if getattr(exc, "content", None) else "<no-body>"
        raise RuntimeError(f"Failed to create YouTube broadcast. HTTP error: {exc}; body: {body}") from exc

    broadcast_id = str(created.get("id") or "").strip()
    if not broadcast_id:
        raise RuntimeError("YouTube did not return a broadcast id after creation.")

    created_snippet_obj = created.get("snippet") if isinstance(created, dict) else None
    created_snippet = created_snippet_obj if isinstance(created_snippet_obj, dict) else {}
    created_channel_id = str(created_snippet.get("channelId") or "").strip()
    if not created_channel_id:
        video_payload = youtube.videos().list(part="snippet", id=broadcast_id, maxResults=1).execute()
        video_items_obj = video_payload.get("items") if isinstance(video_payload, dict) else None
        video_items = video_items_obj if isinstance(video_items_obj, list) else []
        if video_items and isinstance(video_items[0], dict):
            snippet_obj = video_items[0].get("snippet")
            snippet = snippet_obj if isinstance(snippet_obj, dict) else {}
            created_channel_id = str(snippet.get("channelId") or "").strip()

    expected_channel_clean = expected_channel_id.strip()
    if created_channel_id and created_channel_id != expected_channel_clean:
        quarantine_title = clean_title if clean_title.startswith("DELETE") else f"DELETE {clean_title}"
        quarantine_description = str(created_snippet.get("description") or clean_description)
        quarantine_start = str(created_snippet.get("scheduledStartTime") or start_iso)
        quarantine_end = str(created_snippet.get("scheduledEndTime") or end_iso)
        try:
            youtube.liveBroadcasts().update(
                part="id,snippet,status",
                body={
                    "id": broadcast_id,
                    "snippet": {
                        "title": quarantine_title,
                        "description": quarantine_description,
                        "scheduledStartTime": quarantine_start,
                        "scheduledEndTime": quarantine_end,
                    },
                    "status": {
                        "privacyStatus": "private",
                        "selfDeclaredMadeForKids": False,
                    },
                },
            ).execute()
        except Exception:
            pass
        raise RuntimeError(
            "Safety check failed: created broadcast was not on configured church channel and was quarantined "
            "(set to private and title prefixed with DELETE). "
            f"Expected channel id: {expected_channel_clean}; created channel id: {created_channel_id}; "
            f"broadcast: {_youtube_video_url(broadcast_id)}"
        )

    try:
        bind_result = youtube.liveBroadcasts().bind(
            id=broadcast_id,
            streamId=stream_id,
            part="id,contentDetails",
        ).execute()
    except HttpError as exc:
        body = exc.content.decode("utf-8", errors="replace") if getattr(exc, "content", None) else "<no-body>"
        raise RuntimeError(f"Broadcast was created but bind failed. HTTP error: {exc}; body: {body}") from exc

    try:
        playlist_item = youtube.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": clean_playlist_id,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": broadcast_id,
                    },
                }
            },
        ).execute()
    except HttpError as exc:
        body = exc.content.decode("utf-8", errors="replace") if getattr(exc, "content", None) else "<no-body>"
        raise RuntimeError(
            f"Broadcast was created and bound, but playlist assignment failed. HTTP error: {exc}; body: {body}"
        ) from exc

    log_payload = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "service_block_id": service_block_id,
        "title": clean_title,
        "scheduled_start_utc": start_iso,
        "broadcast_id": broadcast_id,
        "broadcast_url": _youtube_video_url(broadcast_id),
        "playlist_id": clean_playlist_id,
        "stream_id": stream_id,
        "bind_result": bind_result,
        "playlist_item_id": str(playlist_item.get("id") or "").strip(),
        "live_chat_replay_default": True,
        "oauth_channel_id": str(auth_context.get("oauth_channel_id") or ""),
        "oauth_channel_title": str(auth_context.get("oauth_channel_title") or ""),
        "channel_match_mode": str(auth_context.get("channel_match_mode") or ""),
    }
    log_path = append_schedule_operation_log(root, log_payload)

    return {
        "service_block_id": service_block_id,
        "title": clean_title,
        "scheduled_start_utc": start_iso,
        "broadcast_id": broadcast_id,
        "broadcast_url": _youtube_video_url(broadcast_id),
        "playlist_id": clean_playlist_id,
        "stream_id": stream_id,
        "playlist_item_id": str(playlist_item.get("id") or "").strip(),
        "privacy_status": "public",
        "live_chat_replay_default": True,
        "oauth_channel_id": str(auth_context.get("oauth_channel_id") or ""),
        "oauth_channel_title": str(auth_context.get("oauth_channel_title") or ""),
        "channel_match_mode": str(auth_context.get("channel_match_mode") or ""),
        "log_path": str(log_path),
    }


def main() -> int:
    root = Path(__file__).resolve().parent

    parser = argparse.ArgumentParser(description="Generate Facebook livestream planning artifacts")
    parser.add_argument("--config", default=str(root / "fb_config.local.json"), help="Path to local config JSON")
    parser.add_argument("--refresh-streams", action="store_true", help="Refresh YouTube streams cache")
    parser.add_argument("--fetch-video-details", action="store_true", help="Try to fetch full details for upcoming YouTube stream")
    parser.add_argument("--fb-lead-minutes", type=int, default=None, help="Override lead minutes before YouTube start")
    parser.add_argument("--selected-video-url", default=None, help="Specific upcoming YouTube video URL to use")
    parser.add_argument("--calendar-youtube-coverage", action="store_true", help="Generate calendar-to-YouTube coverage report")
    parser.add_argument("--calendar-url", default=None, help="Calendar cache JSON URL for coverage mode")
    parser.add_argument("--coverage-days", type=int, default=None, help="Coverage window in days for coverage mode")
    parser.add_argument("--coverage-gap-minutes", type=int, default=None, help="Merge gap for consecutive services")
    parser.add_argument("--list-youtube-live-broadcasts", action="store_true", help="List YouTube live broadcasts using service account credentials")
    parser.add_argument("--youtube-service-account-file", default=None, help="Path to service account JSON key for YouTube API listing")
    parser.add_argument("--list-youtube-live-broadcasts-user", action="store_true", help="List YouTube live broadcasts using user OAuth")
    parser.add_argument("--youtube-client-secret-file", default=None, help="Path to OAuth client secret JSON file")
    parser.add_argument("--youtube-oauth-token-file", default=None, help="Path to store OAuth authorized-user token JSON")
    parser.add_argument("--youtube-oauth-open-browser", action="store_true", help="Open browser automatically for OAuth consent")
    parser.add_argument("--youtube-max-results", type=int, default=5, help="Max YouTube broadcast rows to request (1-50)")
    args = parser.parse_args()

    try:
        config = read_config(Path(args.config))

        if args.list_youtube_live_broadcasts:
            key_path = Path(args.youtube_service_account_file) if args.youtube_service_account_file else next(root.glob("*service_account*.json"), root / "service_account.json")
            payload = list_live_broadcasts_with_service_account(key_path, max_results=args.youtube_max_results)
            items_obj = payload.get("items") if isinstance(payload, dict) else None
            items = items_obj if isinstance(items_obj, list) else []

            print(f"Service account key: {key_path}")
            print(f"Broadcasts returned: {len(items)}")
            for item in items:
                if not isinstance(item, dict):
                    continue
                broadcast_id = str(item.get("id") or "")
                snippet_obj = item.get("snippet")
                snippet = snippet_obj if isinstance(snippet_obj, dict) else {}
                status_obj = item.get("status")
                status = status_obj if isinstance(status_obj, dict) else {}
                title = str(snippet.get("title") or "")
                life_cycle = str(status.get("lifeCycleStatus") or "")
                privacy = str(status.get("privacyStatus") or "")
                print(f"- {broadcast_id} | {title} | {life_cycle} | {privacy}")
            return 0

        if args.list_youtube_live_broadcasts_user:
            client_secret_path = (
                Path(args.youtube_client_secret_file)
                if args.youtube_client_secret_file
                else next(root.glob("client_secret_*.json"), root / "client_secret.json")
            )
            token_path = Path(args.youtube_oauth_token_file) if args.youtube_oauth_token_file else (root / "runtime" / "youtube_oauth_token.json")
            payload = list_live_broadcasts_with_user_oauth(
                client_secret_file=client_secret_path,
                token_file=token_path,
                max_results=args.youtube_max_results,
                open_browser=bool(args.youtube_oauth_open_browser),
            )

            items_obj = payload.get("items") if isinstance(payload, dict) else None
            items = items_obj if isinstance(items_obj, list) else []

            print(f"OAuth client secret: {client_secret_path}")
            print(f"OAuth token file: {token_path}")
            print(f"Broadcasts returned: {len(items)}")
            for item in items:
                if not isinstance(item, dict):
                    continue
                broadcast_id = str(item.get("id") or "")
                snippet_obj = item.get("snippet")
                snippet = snippet_obj if isinstance(snippet_obj, dict) else {}
                status_obj = item.get("status")
                status = status_obj if isinstance(status_obj, dict) else {}
                title = str(snippet.get("title") or "")
                life_cycle = str(status.get("lifeCycleStatus") or "")
                privacy = str(status.get("privacyStatus") or "")
                print(f"- {broadcast_id} | {title} | {life_cycle} | {privacy}")
            return 0

        defaults_cfg = _as_dict(config.get("defaults"))
        calendar_cfg = _as_dict(config.get("calendar"))

        run_coverage_mode = args.calendar_youtube_coverage or bool(defaults_cfg.get("calendar_youtube_coverage", False))

        calendar_url = str(calendar_cfg.get("url") or DEFAULT_CALENDAR_URL)
        if args.calendar_url:
            calendar_url = args.calendar_url

        coverage_days = int(calendar_cfg.get("coverage_days", 10))
        if args.coverage_days is not None:
            coverage_days = args.coverage_days

        coverage_gap_minutes = int(calendar_cfg.get("gap_minutes", 15))
        if args.coverage_gap_minutes is not None:
            coverage_gap_minutes = args.coverage_gap_minutes

        if run_coverage_mode:
            report = build_calendar_youtube_coverage_report(
                root=root,
                config=config,
                refresh_streams=args.refresh_streams,
                calendar_url=calendar_url,
                coverage_days=max(coverage_days, 1),
                gap_minutes=max(coverage_gap_minutes, 0),
            )
            md_path = write_calendar_youtube_coverage_markdown(root, report)
            print(f"Wrote {md_path}")
            print(f"Service blocks matched: {report.get('service_blocks_matched', report.get('divine_blocks_matched'))}")
            print(f"Service blocks missing: {report.get('service_blocks_missing', report.get('divine_blocks_missing'))}")
            return 0

        fb_lead_minutes = args.fb_lead_minutes
        if fb_lead_minutes is None:
            fb_lead_minutes = int(defaults_cfg.get("fb_lead_minutes", 15))

        refresh_streams = args.refresh_streams or bool(defaults_cfg.get("refresh_streams", False))
        fetch_video_details = args.fetch_video_details or bool(defaults_cfg.get("fetch_video_details", False))

        result = build_result(
            root=root,
            config=config,
            refresh_streams=refresh_streams,
            fetch_video_details=fetch_video_details,
            fb_lead_minutes=fb_lead_minutes,
            selected_video_url=args.selected_video_url,
        )
        write_outputs(root, result)

        print("Wrote analysis/facebook_schedule_result.json")
        print("Wrote analysis/facebook_schedule_result.md")
        print(f"YouTube start (UTC): {result['youtube']['start_utc']}")
        print(f"Facebook start (UTC): {result['facebook']['start_utc']}")
        print("Manual Producer Pack generated")
        return 0
    except (ConfigError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())