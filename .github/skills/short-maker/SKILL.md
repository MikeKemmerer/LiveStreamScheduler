---
name: short-maker
description: "Find and extract YouTube Shorts from sermon videos. Use when: creating shorts, finding short clips, extracting sermon highlights, reviewing sermons for shorts, cutting sermon clips, YouTube Shorts."
argument-hint: "Provide a YouTube channel URL, video URL, or number of recent videos to scan"
---

# Sermon Shorts Maker

Scan sermon videos from the church YouTube channel, identify compelling sub-60-second moments, download the clips, and generate metadata descriptions.

## When to Use

- Reviewing recent sermons to find Shorts-worthy moments
- Extracting a specific segment from a sermon as a Short
- Batch-creating Shorts from multiple sermons

## Accepted Inputs

1. **Number of recent videos** — e.g., "find shorts from the last 10 sermons"
2. **Specific YouTube video URL** — scan one sermon for shorts moments
3. **Timestamp range + video URL** — extract a known segment directly

## Environment

This skill requires `yt-dlp` installed and accessible in the terminal. See [environment config](./references/env-config.md) for paths and channel details.

## Procedure

### Step 1 — List Recent Sermons

Use `yt-dlp` to list recent videos from the channel:

```bash
yt-dlp --flat-playlist \
  --print "%(id)s | %(title)s | %(upload_date)s | %(duration)s" \
  "CHANNEL_URL" 2>/dev/null | head -N
```

Filter to sermon-length videos (typically 3–20 minutes). Skip full liturgy recordings (> 30 min).

### Step 2 — Download Transcripts

For each video, download auto-generated subtitles:

```bash
yt-dlp --write-auto-sub --sub-lang en --skip-download \
  --output "/tmp/shorts_transcripts/VIDEO_ID" \
  "https://www.youtube.com/watch?v=VIDEO_ID"
```

Extract timestamped clean text:

```bash
awk '/^[0-9][0-9]:[0-9][0-9]:[0-9][0-9]/{ts=substr($1,1,8)} /^[A-Za-z&]/{gsub(/<[^>]*>/,""); if(!seen[$0]++) print ts" "$0}' \
  /tmp/shorts_transcripts/VIDEO_ID.en.vtt
```

This produces ordered, timestamped, deduplicated lines for review.

### Step 3 — Identify Shorts-Worthy Moments

Read each transcript and look for segments that are:

- **Self-contained**: Makes sense without surrounding context
- **Under 60 seconds** of core content
- **Compelling**: A vivid illustration, a powerful question, a memorable teaching moment
- **Has a clear hook**: Starts with something that grabs attention

Good Shorts candidates:
- Vivid analogies or personal stories (e.g., scraped knee → Holy Unction)
- Rhetorical questions that resonate universally
- Concise theological explanations (e.g., why we baptize on Holy Saturday)
- Emotionally resonant moments
- Surprising or counterintuitive statements

Poor candidates:
- Liturgical instructions or announcements
- Segments that require prior context to understand
- Long Scripture readings without commentary
- Greetings, closings, or transitions

### Step 4 — Download Video Segments

Extract each clip using `yt-dlp` section download:

```bash
yt-dlp --download-sections "*HH:MM:SS-HH:MM:SS" \
  -f "bestvideo[height<=1080]+bestaudio/best" \
  --merge-output-format mp4 --force-overwrites \
  -o "Shorts/Title Here.%(ext)s" \
  "https://www.youtube.com/watch?v=VIDEO_ID"
```

Rules:
- Always add **3 seconds of padding** before and after the target timestamps — auto-generated subtitle timestamps are often slightly off
- Use the Short title as the filename (no date prefix)
- Save to the `Shorts/` folder in the repo root

### Step 5 — Generate Description File

Create a `.txt` file matching each `.mp4` filename. Follow the sermon-metadata description format:

```
Short Title

[Hook — 1-2 sentences summarizing the clip's core message]

[Summary — 2-4 sentences expanding on the content and context]

Scripture: [references, only if explicitly quoted in the clip]

Saint Demetrios Greek Orthodox Church — Seattle, WA
```

Rules:
- First line is the Short title (same as the filename, no date prefix)
- Hook appears in YouTube search results — make it count
- Tone: reverent but accessible
- Only include Scripture references actually spoken in the clip
- Omit the Scripture line entirely if none are quoted
- Do NOT include timestamps, links, or promotional content
- Parish line is always last, preceded by a blank line

### Step 6 — Present Results

After processing, present a summary table:

| Short Title | Source Sermon | Segment | Duration |
|-------------|-------------|---------|----------|
| Title | Sermon name | MM:SS–MM:SS | ~XXs |

Let the user review and request changes before considering the task complete.

## Reference

- [Environment config](./references/env-config.md) — Channel URL, paths, and tool locations (not tracked in git)
