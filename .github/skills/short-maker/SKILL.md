---
name: short-maker
description: "Find and extract YouTube Shorts from sermon videos. Use when: creating shorts, finding short clips, extracting sermon highlights, reviewing sermons for shorts, cutting sermon clips, YouTube Shorts."
argument-hint: "Provide a YouTube channel URL, video URL, or number of recent videos to scan"
---

# Sermon Shorts Maker

Scan sermon videos from the church YouTube channel, identify compelling sub-60-second moments, download the clips, and generate metadata descriptions.

## Context

These are **Greek Orthodox** sermons (homilies) delivered during Divine Liturgy or Holy Week services at a parish in Seattle. The preacher often uses vivid personal stories, patristic references, and accessible analogies to connect theology to everyday life. The target audience for Shorts is both existing parishioners and newcomers discovering Orthodox Christianity. "Compelling" means: something a non-churchgoer scrolling YouTube would stop and watch.

### Orthodox Language & Theology Guidelines

All Short titles and descriptions must be consistent with Orthodox Christian teaching:

**Terminology**:
- "Divine Liturgy" (not "church service" or "Mass")
- "Theotokos" / "the Virgin Mary" (not "Our Lady")
- "Holy Communion" / "Eucharist" (not "Lord's Supper")
- "Holy Unction" (not "anointing of the sick")
- "Theosis" / "deification" (not "sanctification")
- "Pascha" preferred; "Easter" acceptable in titles for accessibility
- "Mystery" or "Sacrament" (both fine; "Mystery" is more traditional)
- "Confession" / "Mystery of Repentance" (not a legalistic "going to confession")
- "Priest" / "Father" (not "pastor", "reverend", "minister")
- "Nave" for the worship space (not "sanctuary" — that's the altar area behind the iconostasis)

**Theology**:
- Christ is fully God and fully man — not merely a teacher or prophet
- The Cross is victory over death — not penal substitution (avoid "Jesus paid the price")
- Salvation is healing and transformation (theosis), not a legal transaction
- Sacraments are real encounters with grace — never "symbolic"
- The Saints are alive in Christ and intercede for us
- The Holy Spirit proceeds from the Father (not "and the Son")
- Original sin = inherited mortality, not inherited guilt — avoid "born sinful" or "total depravity"
- Icons are windows to heaven — venerated, not worshipped
- The Liturgy is timeless — we join heavenly worship already in progress; it is not a reenactment

**Liturgical calendar** (sermons often reference these):
- Holy Week services: Palm Sunday, Bridegroom Matins, Holy Unction (Wed), Mystical Supper (Thu), Twelve Gospels (Thu eve), Royal Hours (Fri morning), Unnailing (Fri afternoon), Lamentations (Fri eve), Holy Saturday Liturgy, Paschal service
- Feast days: Nativity, Theophany (not "Epiphany"), Annunciation, Transfiguration, Dormition (not "Assumption")
- Fasting is spiritual discipline, not punishment

**Prayer and spiritual life**:
- The Jesus Prayer: "Lord Jesus Christ, Son of God, have mercy on me, a sinner"
- Nepsis (watchfulness), hesychasm (inner stillness), nous (spiritual intellect)
- Church Fathers: use correct titles ("Saint John Chrysostom", "Saint Basil the Great", etc.) — do not reduce to "early church leaders"

**Avoid**:
- "Accept Jesus as your personal Lord and Savior" (altar-call language)
- "God has a plan for your life" (prosperity/evangelical framing)
- Describing Orthodox worship in Protestant or Catholic terms
- "Worship leader", "praise band", "small group", "quiet time"
- Calling the Church "a denomination" — Orthodoxy understands itself as the one, holy, catholic, and apostolic Church
- Individualistic framing — prefer "we" over "you"

**Tone**: Reverent but accessible — a newcomer should feel invited, not lectured.

## When to Use

- Reviewing recent sermons to find Shorts-worthy moments
- Extracting a specific segment from a sermon as a Short
- Batch-creating Shorts from multiple sermons

## Accepted Inputs

1. **Number of recent videos** — e.g., "find shorts from the last 10 sermons"
2. **Specific YouTube video URL** — scan one sermon for shorts moments
3. **Timestamp range + video URL** — extract a known segment directly

### Required: Speaker Identification

**STOP and ASK** if the user has not identified who is speaking in the video(s) being reviewed. Do not proceed with transcript review or Short extraction until you know the speaker for each video. This is mandatory even if autopilot is enabled.

The speaker may be identified in the DRAFT video title (e.g., "DRAFT - April 10, 2026 Fr. Photios Homily"). When listing the DRAFTS playlist in Step 1, check each title for speaker names before asking the user.

Common speakers:
- **Fr. Photios** — parish priest
- **Fr. Spyridon** — parish priest
- **Guest priest or speaker** — ask for their name and title

When reviewing a batch, confirm the speaker for the batch (e.g., "these are all Fr. Photios") or ask per-video if they vary.

## Environment

This skill requires `yt-dlp` installed and accessible in the terminal. See [environment config](./references/env-config.md) for paths and channel details.

## Procedure

### Step 1 — List Recent Sermons

Use the **DRAFTS playlist** as the primary source for new sermons to review. The playlist URL is in [environment config](./references/env-config.md).

```bash
yt-dlp --flat-playlist \
  --print "%(id)s | %(title)s | %(upload_date)s | %(duration)s" \
  "DRAFTS_PLAYLIST_URL" 2>/dev/null
```

Before reviewing any video, check [reviewed-videos.md](./references/reviewed-videos.md) and skip any video IDs already listed there.

Filter to sermon-length videos (typically 3–20 minutes). Skip full liturgy recordings (> 30 min), encyclicals, baptisms, and entries marked "SHORT" or "low volume".

### Step 2 — Download Transcripts

For each video, download auto-generated subtitles:

```bash
yt-dlp --write-auto-sub --sub-lang en --skip-download \
  --output "/tmp/shorts_transcripts/VIDEO_ID" \
  "https://www.youtube.com/watch?v=VIDEO_ID"
```

**Check the actual output filename** — yt-dlp sometimes writes `.en.vtt` or `.en.vtt3`. Use `ls /tmp/shorts_transcripts/VIDEO_ID*` to confirm.

Extract timestamped clean text:

```bash
awk '/^[0-9][0-9]:[0-9][0-9]:[0-9][0-9]/{ts=substr($1,1,8)} /^[A-Za-z&]/{gsub(/<[^>]*>/,""); if(!seen[$0]++) print ts" "$0}' \
  /tmp/shorts_transcripts/VIDEO_ID.en.vtt
```

This produces ordered, timestamped, deduplicated lines for review.

If a video has **no auto-generated captions** (yt-dlp reports "no subtitles"), skip it — do not attempt to review without a transcript.

**Batch strategy**: When reviewing multiple videos, download all transcripts first, then review them one at a time. This avoids interleaving downloads and reviews, which wastes context.

### Step 3 — Identify Shorts-Worthy Moments

**How to read a transcript**: Scan the timestamped output line by line. You are looking for self-contained "moments" — a passage where the speaker makes a complete point in under 60 seconds. To estimate duration, subtract the timestamp of the first line from the last line of the candidate segment. For example, if a segment starts at `00:03:15` and ends at `00:04:05`, that's ~50 seconds of content.

**Expectation**: Most sermons will yield 0 or 1 worthy Short. Finding none is normal — do not force a Short from weak material. Finding 2 from one sermon is rare but acceptable.

Read each transcript and look for segments that are:

- **Self-contained**: Makes sense without surrounding context
- **Under 60 seconds** of core content (estimate from timestamp gap)
- **Compelling**: A vivid illustration, a powerful question, a memorable teaching moment
- **Has a clear hook**: The first few seconds grab attention

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

#### Worked Example

From a transcript of a Holy Unction sermon, these lines appeared:

```
00:00:50 you know when you're a little kid and you scrape your knee
00:00:54 and you go running to your mom or your dad
00:00:57 and they pick you up and they kiss it
00:01:02 did the kiss heal the wound no
00:01:05 but it did something deeper it told you that you were loved
00:01:10 that someone cared about your pain
00:01:15 that's what holy unction is
00:01:18 it's God kissing your scraped knee
00:01:22 it's the church saying we see your suffering
00:01:28 and we bring the medicine of God's love
00:01:35 not because it magically fixes everything
00:01:40 but because you are not alone in your pain
00:01:48 and that changes everything
00:01:52 that is the mystery of this sacrament
```

**Why this works**: Self-contained analogy (scraped knee → sacrament), opens with a universal childhood image (hook), completes a full thought in ~62 seconds, emotionally resonant.

**Timestamp calculation**: 00:00:50 to 00:01:52 = 62 seconds of core content. With 3-second padding: `--download-sections "*00:00:47-00:01:55"`.

**Title**: "God Kissing Your Scraped Knee" — evocative, surprising, makes a viewer curious.

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
- The `*` before the timestamp range is required yt-dlp syntax — do not omit it
- Use the Short title as the filename (no date prefix)
- Save to the `Shorts/` folder in the repo root

### Short Title Rules

- 3–8 words, evocative and curiosity-provoking
- Should make sense to someone who has never seen the sermon
- Use the most striking image or phrase from the segment
- Avoid generic titles ("A Beautiful Sermon Moment", "Orthodox Teaching")
- Avoid clickbait — the title should honestly represent the content
- No date prefix, no church name, no speaker name
- Examples: "God Kissing Your Scraped Knee", "No Tomb So Sealed", "The Jesus Prayer Is Not Just for Monks"

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

### Step 7 — Update Tracking

After the user confirms results, append all reviewed video IDs to [reviewed-videos.md](./references/reviewed-videos.md) — both those with Shorts extracted and those reviewed without a worthy segment. This prevents re-processing on future runs.

## Reference

- [Environment config](./references/env-config.md) — Channel URL, DRAFTS playlist, paths, and tool locations (not tracked in git)
- [Reviewed videos](./references/reviewed-videos.md) — Previously scanned video IDs (not tracked in git)
