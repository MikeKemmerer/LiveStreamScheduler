#!/usr/bin/env python3
"""Standalone test to verify recorded matching works end-to-end."""
import json
import sys
from datetime import date, datetime, timedelta, timezone

# Add project to path
sys.path.insert(0, ".")
from fb_scheduler import (
    _build_stream_index,
    _label_ngram_similarity,
    _service_label_from_names,
    _service_tokens,
)

# Use US Eastern
try:
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("America/New_York")
except ImportError:
    from dateutil.tz import gettz
    tz = gettz("America/New_York")

# Load real cached stream data
with open("cache/streams_flat.json") as f:
    data = json.load(f)
entries = data.get("entries", [])
print(f"Loaded {len(entries)} stream entries from cache")

# Build stream index (same as production code)
stream_index = _build_stream_index(entries, tz=tz)
print(f"Built stream index with {len(stream_index)} entries")

# Show today's streams
today = date.today()
today_streams = [s for s in stream_index if s["local_day"] == today]
print(f"\nToday's streams ({today}):")
for s in today_streams:
    print(f"  Title: {s['title']}")
    print(f"    label: {s['service_label']}")
    print(f"    tokens: {s['service_tokens']}")
    print(f"    live_status: {s['live_status']}")
    print(f"    start: {s['start']}")
    print()

# Simulate service blocks for today that would come from the calendar
# Based on actual calendar: 3 services today
now_utc = datetime.now(timezone.utc)
mock_blocks = [
    {
        "start": datetime(today.year, today.month, today.day, 9, 30, tzinfo=tz),
        "end": datetime(today.year, today.month, today.day, 12, 0, tzinfo=tz),
        "local_day": today,
        "services": ["9th Hour Prayers", "Pre-Sanctified Divine Liturgy"],
    },
    {
        "start": datetime(today.year, today.month, today.day, 15, 0, tzinfo=tz),
        "end": datetime(today.year, today.month, today.day, 16, 30, tzinfo=tz),
        "local_day": today,
        "services": ["Holy Unction"],
    },
    {
        "start": datetime(today.year, today.month, today.day, 19, 0, tzinfo=tz),
        "end": datetime(today.year, today.month, today.day, 20, 30, tzinfo=tz),
        "local_day": today,
        "services": ["Bridegroom (Nymphios) Service with Unction"],
    },
]
for block in mock_blocks:
    label = _service_label_from_names(block["services"])
    block["service_label"] = label
    block["service_tokens"] = _service_tokens(label)
    block["divine_liturgy"] = "divine_liturgy" in block["service_tokens"]

print("Mock service blocks:")
for b in mock_blocks:
    print(f"  {b['service_label']}  tokens={b['service_tokens']}")
print()

# Show n-gram similarity matrix
print("N-gram similarity matrix (block → stream):")
for b in mock_blocks:
    bl = b["service_label"]
    for s in today_streams:
        sl = s["service_label"]
        score = _label_ngram_similarity(bl, sl)
        print(f"  {bl:50s} → {sl:50s}  score={score:.3f}")
    print()

# === Run matching logic (copied from build_calendar_youtube_coverage_report) ===
matched_services = []
recorded_services = []
missing_services = []
used_stream_indexes = set()

for block in mock_blocks:
    block_day = block["local_day"]
    block_start = block["start"]
    block_tokens = block.get("service_tokens")
    block_token_set = block_tokens if isinstance(block_tokens, set) else set()
    block_label = str(block.get("service_label") or "").lower()

    matched_stream = None
    matched_stream_index = None
    best_time_diff = None
    best_fallback_score = 0.0
    fallback_stream = None
    fallback_stream_index = None

    for idx, stream in enumerate(stream_index):
        if idx in used_stream_indexes:
            continue
        if stream["local_day"] != block_day:
            continue

        stream_start = stream.get("start")

        # Primary: match by scheduled start time proximity
        if stream_start is not None and block_start is not None:
            diff_seconds = abs((stream_start - block_start).total_seconds())
            if diff_seconds <= 3600:
                if best_time_diff is None or diff_seconds < best_time_diff:
                    best_time_diff = diff_seconds
                    matched_stream = stream
                    matched_stream_index = idx
            continue

        # Fallback: score by n-gram similarity, pick best
        if stream_start is None:
            stream_label = str(stream.get("service_label") or "")
            score = _label_ngram_similarity(block_label, stream_label)
            if score > best_fallback_score:
                best_fallback_score = score
                fallback_stream = stream
                fallback_stream_index = idx

    # Use time match if found, otherwise fall back to best n-gram match
    if matched_stream is None and fallback_stream is not None and best_fallback_score >= 0.3:
        matched_stream = fallback_stream
        matched_stream_index = fallback_stream_index

    if matched_stream is not None:
        if matched_stream_index is not None:
            used_stream_indexes.add(matched_stream_index)

        stream_live_status = matched_stream.get("live_status", "")
        stream_start_dt = matched_stream.get("start")
        is_recorded = (
            stream_live_status in ("was_live", "not_live")
            or (stream_start_dt is not None and stream_start_dt < now_utc)
        )

        entry_data = {
            "service_label": block["service_label"],
            "youtube_title": matched_stream["title"],
            "youtube_url": matched_stream["url"],
            "is_recorded": is_recorded,
            "match_type": "time" if best_time_diff is not None else "fallback",
        }

        if is_recorded:
            recorded_services.append(entry_data)
        else:
            matched_services.append(entry_data)
    else:
        missing_services.append({"service_label": block["service_label"]})

# === Results ===
print("=" * 60)
print("RESULTS")
print("=" * 60)
print(f"\nScheduled: {len(matched_services)}")
for s in matched_services:
    print(f"  [{s['match_type']}] {s['service_label']} → {s['youtube_title']}")

print(f"\nRecorded: {len(recorded_services)}")
for s in recorded_services:
    print(f"  [{s['match_type']}] {s['service_label']} → {s['youtube_title']}")

print(f"\nMissing: {len(missing_services)}")
for s in missing_services:
    print(f"  {s['service_label']}")

# Validate
if recorded_services:
    print("\n✓ PASS — Recorded services detected!")
else:
    print("\n✗ FAIL — No recorded services detected")
    sys.exit(1)
