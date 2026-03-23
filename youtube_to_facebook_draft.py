#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path


def run_yt_dlp_json(url: str, flat_playlist: bool = False) -> dict:
    cmd = [
        "yt-dlp",
        "--dump-single-json",
        "--no-warnings",
        "--ignore-no-formats-error",
    ]
    if flat_playlist:
        cmd.append("--flat-playlist")
    cmd.append(url)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "yt-dlp failed")

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse yt-dlp JSON: {exc}") from exc


def run_yt_dlp_json_streaming(url: str, flat_playlist: bool = False, on_line=None) -> dict:
    """Like run_yt_dlp_json but yields stderr lines via *on_line* callback in real time."""
    cmd = [
        "yt-dlp",
        "--dump-single-json",
        "--ignore-no-formats-error",
        "--newline",
    ]
    if flat_playlist:
        cmd.append("--flat-playlist")
    cmd.append(url)

    if on_line:
        on_line(f"$ {' '.join(cmd)}")

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    proc_stdout = proc.stdout
    proc_stderr = proc.stderr
    assert proc_stdout is not None
    assert proc_stderr is not None
    stderr_lines: list[str] = []

    def _drain_stderr():
        for raw in proc_stderr:
            line = raw.rstrip("\n\r")
            if line:
                stderr_lines.append(line)
                if on_line:
                    on_line(line)

    t = threading.Thread(target=_drain_stderr, daemon=True)
    t.start()

    stdout_data = proc_stdout.read()
    proc.wait(timeout=180)
    t.join(timeout=5)

    if proc.returncode != 0:
        err_msg = "\n".join(stderr_lines).strip() or "yt-dlp failed"
        if on_line:
            on_line(f"ERROR: yt-dlp exited with code {proc.returncode}")
        raise RuntimeError(err_msg)

    try:
        return json.loads(stdout_data)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse yt-dlp JSON: {exc}") from exc


def load_json_file(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(data, dict):
        return data
    return None


def normalize_channel_streams_url(channel_url: str) -> str:
    base = channel_url.strip().rstrip("/")
    if base.endswith("/streams"):
        return base
    return f"{base}/streams"


def parse_timestamp(entry: dict) -> datetime | None:
    ts = entry.get("release_timestamp") or entry.get("timestamp")
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def find_next_upcoming(entries: list[dict], now_utc: datetime) -> dict | None:
    candidates = []
    for entry in entries:
        when = parse_timestamp(entry)
        if when is None:
            continue

        live_status = (entry.get("live_status") or "").strip().lower()
        is_upcoming = "upcoming" in live_status or when >= now_utc
        if not is_upcoming:
            continue

        candidates.append((when, entry))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def resolve_default_channel_url(cache_file: Path) -> str | None:
    if not cache_file.exists():
        return None

    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
    except Exception:
        return None

    if isinstance(data, dict):
        channel_url = data.get("channel_url")
        if isinstance(channel_url, str) and channel_url.strip():
            return channel_url.strip()
    return None


def main() -> int:
    root = Path(__file__).resolve().parent
    streams_cache_file = root / "cache" / "streams_flat.json"
    default_channel = resolve_default_channel_url(streams_cache_file)

    parser = argparse.ArgumentParser(
        description="Generate a Facebook event draft from the next upcoming YouTube livestream.",
    )
    parser.add_argument(
        "--channel-url",
        default=default_channel,
        help="YouTube channel URL (e.g. https://www.youtube.com/@yourchannel).",
    )
    parser.add_argument(
        "--output",
        default=str(root / "analysis" / "facebook_next_upcoming.md"),
        help="Output markdown file path.",
    )
    parser.add_argument(
        "--fb-lead-minutes",
        type=int,
        default=15,
        help="How many minutes earlier Facebook should start than YouTube (default: 15).",
    )
    parser.add_argument(
        "--refresh-streams",
        action="store_true",
        help="Fetch fresh streams data with yt-dlp and update cache before generating draft.",
    )
    parser.add_argument(
        "--fetch-video-details",
        action="store_true",
        help="Try fetching full video metadata for better descriptions (can fail on some upcoming streams).",
    )
    args = parser.parse_args()

    if not args.channel_url:
        print(
            "No channel URL provided and no cached default found. Use --channel-url.",
            file=sys.stderr,
        )
        return 2

    streams_url = normalize_channel_streams_url(args.channel_url)

    playlist = None
    if args.refresh_streams:
        try:
            playlist = run_yt_dlp_json(streams_url, flat_playlist=True)
            streams_cache_file.parent.mkdir(parents=True, exist_ok=True)
            streams_cache_file.write_text(json.dumps(playlist, ensure_ascii=False, indent=2), encoding="utf-8")
        except RuntimeError as exc:
            print(f"Failed to fetch channel streams: {exc}", file=sys.stderr)
            return 1
    else:
        playlist = load_json_file(streams_cache_file)
        if playlist is None:
            try:
                playlist = run_yt_dlp_json(streams_url, flat_playlist=True)
                streams_cache_file.parent.mkdir(parents=True, exist_ok=True)
                streams_cache_file.write_text(json.dumps(playlist, ensure_ascii=False, indent=2), encoding="utf-8")
            except RuntimeError as exc:
                print(f"Failed to fetch channel streams: {exc}", file=sys.stderr)
                return 1

    entries = playlist.get("entries") or []
    if not isinstance(entries, list) or not entries:
        print("No stream entries found on channel streams page.", file=sys.stderr)
        return 1

    now_utc = datetime.now(timezone.utc)
    upcoming = find_next_upcoming(entries, now_utc)
    if upcoming is None:
        print("No upcoming livestream found.", file=sys.stderr)
        return 1

    video_url = upcoming.get("url")
    if not isinstance(video_url, str) or not video_url.strip():
        print("Upcoming entry missing video URL.", file=sys.stderr)
        return 1
    video_url = video_url.strip()

    video = upcoming
    if args.fetch_video_details:
        try:
            video = run_yt_dlp_json(video_url)
        except RuntimeError:
            video = upcoming

    yt_title = (video.get("title") or upcoming.get("title") or "Upcoming Livestream").strip()
    yt_description = (video.get("description") or upcoming.get("description") or "").strip()

    yt_start = parse_timestamp(video) or parse_timestamp(upcoming)
    if yt_start is None:
        print("Could not determine YouTube scheduled start time.", file=sys.stderr)
        return 1

    fb_start = yt_start - timedelta(minutes=args.fb_lead_minutes)

    local_tz = datetime.now().astimezone().tzinfo
    yt_local = yt_start.astimezone(local_tz)
    fb_local = fb_start.astimezone(local_tz)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fb_description = yt_description
    if fb_description:
        fb_description += "\n\n"
    fb_description += f"Watch on YouTube: {video_url}"

    content = f"""# Facebook Draft From Next Upcoming YouTube Stream

## Source
- Channel Streams URL: {streams_url}
- YouTube Stream URL: {video_url}

## YouTube (Reference)
- Title: {yt_title}
- Scheduled Start (UTC): {yt_start.isoformat()}
- Scheduled Start (Local): {yt_local.strftime('%Y-%m-%d %I:%M %p %Z')}

## Facebook (Draft)
- Name: {yt_title}
- Scheduled Start (UTC): {fb_start.isoformat()}
- Scheduled Start (Local): {fb_local.strftime('%Y-%m-%d %I:%M %p %Z')}
- Offset Rule: {args.fb_lead_minutes} minutes before YouTube start

## Facebook Description Draft
{fb_description}

## JSON Draft (for your own tooling)
```json
{json.dumps({
    "name": yt_title,
    "start_time_utc": fb_start.isoformat(),
    "description": fb_description,
    "source_youtube_url": video_url,
    "source_youtube_start_time_utc": yt_start.isoformat(),
    "offset_minutes": args.fb_lead_minutes,
}, indent=2)}
```
"""

    output_path.write_text(content, encoding="utf-8")

    print(f"Wrote draft: {output_path}")
    print(f"YouTube start (UTC): {yt_start.isoformat()}")
    print(f"Facebook start (UTC): {fb_start.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
