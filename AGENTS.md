# AI Agent Instructions — LiveStreamScheduler

## Project Overview

YouTube/Facebook live stream scheduler with sermon post-processing pipeline. Schedules broadcasts via Google Calendar + YouTube API, extracts sermon clips, generates metadata, and creates Shorts.

## Quick Start

```bash
pip install -r requirements.txt
python fb_scheduler.py --config fb_config.local.json   # CLI scheduler
python fb_trigger_server.py                            # Web UI (port 8080)
```

## Architecture

| Component | Purpose |
|-----------|---------|
| `fb_scheduler.py` | Main scheduler — matches calendar events to YouTube broadcasts |
| `fb_trigger_server.py` | SSE-streaming web dashboard for manual triggers |
| `Sermons/` | Sermon discovery, transcripts, boundaries, and downloads |
| `Shorts/` | Extracted short clips (landscape + portrait) |
| `.github/skills/` | Domain knowledge for sermon-metadata and short-maker workflows |

## Key Conventions

- **Config**: Copy `fb_config.example.json` → `fb_config.local.json`. Never commit credentials.
- **Python**: PEP 8, Python 3.9+, `zoneinfo` for timezones
- **Git**: `master` branch, SSH remote, one branch per feature
- **Skills**: YAML frontmatter + Markdown in `.github/skills/<name>/SKILL.md`
- **Sermon data**: `Sermons/sermons.json` is the index of processed sermons

## Tools & Dependencies

- `yt-dlp` (CLI, not imported) for video/audio downloads
- `google-api-python-client` for YouTube Data API
- `ffmpeg` for segment extraction
- FaceFollow (`/home/kemmie/tools/FaceFollow`) for portrait crop

## Terminal Notes

- `rm`, `git branch -D`, `curl` blocked by policy
- WSL path: `/mnt/c/Users/michael.kemmerer/Desktop/LiveStreamScheduler/`
- Redirect output: `> /mnt/c/Users/michael.kemmerer/Desktop/out.txt 2>&1`

## Related Skills

- [sermon-metadata](.github/skills/sermon-metadata/SKILL.md) — Generate YouTube titles/descriptions
- [short-maker](.github/skills/short-maker/SKILL.md) — Extract Shorts from sermon videos
