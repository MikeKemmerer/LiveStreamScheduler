---
name: sermon-metadata
description: "Generate YouTube title and description for a sermon. Use when: creating sermon metadata, writing sermon titles, writing sermon descriptions, formatting sermon uploads, YouTube sermon metadata."
argument-hint: "Provide a sermon transcript (pasted text, file path, or YouTube URL)"
---

# Sermon Title & Description Generator

Generate a formatted YouTube title and description for a sermon delivered at Saint Demetrios Greek Orthodox Church, Seattle, WA.

## Context

These are **Greek Orthodox** homilies delivered during Divine Liturgy, Vespers, or Holy Week services. The preacher typically weaves together scripture, patristic theology, and relatable everyday illustrations. Descriptions should be accessible to newcomers while respecting the liturgical tradition.

### Orthodox Language & Theology Guidelines

All titles and descriptions must be consistent with Orthodox Christian teaching. Follow these rules:

**Use Orthodox terminology**:
- "Divine Liturgy" — not "church service", "worship service", or "Mass"
- "Theotokos" or "the Virgin Mary" — not "Our Lady" (Catholic) or just "Mary"
- "Holy Communion" or "the Eucharist" — not "the Lord's Supper" (Protestant)
- "Holy Unction" — not "anointing of the sick" or "last rites"
- "Theosis" or "deification" — not "sanctification" (which has a different meaning in Orthodoxy)
- "Mystery" or "Sacrament" — both are acceptable; "Mystery" is more traditionally Orthodox
- "Pascha" is preferred when discussing the theological event; "Easter" is acceptable in titles for accessibility
- "Baptism" includes chrismation (they are one event in Orthodoxy)

**Christology and theology**:
- Christ is fully God and fully man — never frame Him as merely a moral teacher or a prophet
- The Cross is victory over death, not penal substitution — avoid "Jesus paid the price for our sins" or "took the punishment we deserved"
- Salvation is understood as healing and transformation (theosis), not a legal transaction
- The Church is the Body of Christ, not a building or an organization
- The Saints are alive in Christ and intercede for us — they are not merely historical examples

**Avoid these non-Orthodox framings**:
- "Accept Jesus as your personal Lord and Savior" (Protestant altar-call language)
- "God has a plan for your life" (prosperity/evangelical framing)
- "Sola scriptura" thinking — Orthodox theology draws on Scripture, Tradition, and the Church Fathers
- Describing sacraments as "symbolic" — in Orthodoxy, the Mysteries are real encounters with God's grace
- Individualistic language — Orthodoxy emphasizes communal salvation ("we" over "you")

**Tone**: Reverent but accessible. The goal is to invite, not to lecture. A newcomer should feel welcomed, not excluded by jargon — but the jargon that is used should be correct.

## Prerequisites

- `yt-dlp` must be installed and accessible in the terminal
- No API keys or sign-in required — auto-generated captions work on unlisted videos

## When to Use

- After a sermon is recorded and you need title + description for YouTube upload
- When reviewing or rewriting existing sermon metadata
- When given a sermon transcript (pasted, file, or URL) and asked for metadata

## Accepted Inputs

The user may provide any of:

1. **Transcript pasted directly into chat** — use as-is
2. **File path** to a transcript file — read it
3. **YouTube video URL** — use `yt-dlp` to download the auto-generated subtitle file, then extract text from it

If no sermon date is provided, ask.

### Required: Speaker Identification

**STOP and ASK** if the user has not identified who is speaking. Do not proceed with title or description generation until you know the speaker. This is mandatory even if autopilot is enabled.

Common speakers:
- **Fr. Photios** — parish priest
- **Fr. Spyridon** — parish priest
- **Guest priest or speaker** — ask for their name and title

The speaker's name does not appear in the title or description (per the formatting rules), but it is needed to correctly attribute the homily's style and context internally and to avoid misattribution.

## Fetching a YouTube Transcript with yt-dlp

When given a YouTube URL, first extract the video title and upload date:

```bash
yt-dlp --print title --print upload_date \
  "https://www.youtube.com/watch?v=VIDEO_ID" 2>/dev/null
```

The title often contains the sermon date (e.g., "DRAFT - April 10, 2026 Homily"). The `upload_date` is in `YYYYMMDD` format. Use these to determine the sermon date before asking the user.

Then download the auto-generated subtitles:

```bash
yt-dlp --write-auto-sub --sub-lang en --skip-download \
  --output "/tmp/sermon_transcript" \
  "https://www.youtube.com/watch?v=VIDEO_ID"
```

**Check the actual output filename** — yt-dlp sometimes writes `.en.vtt` or `.en.vtt3`. Use `ls /tmp/sermon_transcript*` to confirm.

Extract clean deduplicated text:

```bash
grep -v "^WEBVTT\|^NOTE\|^[0-9]\|^$\|-->" \
  /tmp/sermon_transcript.en.vtt \
  | sort -u
```

This strips timestamps intentionally — for metadata generation you only need the content, not the timing.

If a video has **no auto-generated captions** (yt-dlp reports "no subtitles found"), inform the user and ask them to provide a transcript another way.

## Procedure

### Step 1 — Extract Core Content

Read the full transcript. Identify:

- **Central theme**: The single overarching message or exhortation
- **Key points**: 2–4 supporting ideas or arguments
- **Scripture passages**: Every Bible passage explicitly quoted or referenced (book, chapter, verse)
- **Sermon date**: The date the sermon was delivered (from video title or upload date)

Do NOT fabricate scripture references. Only include passages actually present in the transcript. Auto-generated captions often garble scripture citations — if a reference is unclear, omit it rather than guess.

**How to read the transcript**: Auto-generated captions are unpunctuated and may contain errors. Read the full output to understand the sermon's arc before identifying the theme. Don't rely on the first few lines — the central message often emerges in the middle or end.

### Step 2 — Generate Title

Format: `Month D, YYYY • Sermon Title`

Rules:
- Date prefix uses full month name, day without leading zero, 4-digit year, then ` • ` (space bullet space — this is U+2022, not an asterisk)
- Sermon title portion: 4–10 words, short and compelling
- Reflect the central theme, not the liturgical occasion
- Avoid generic titles ("Sunday Sermon", "Homily", "A Message of Hope")
- Do not include church name or pastor's name
- Use active, engaging language that draws a viewer in
- Reference the theme of scripture, not the citation (e.g., "What It Means to Take Up Your Cross" not "Matthew 16:24 Homily")

Good titles: "Christ Is Working, Even in the Tomb", "Vigilance Compliments Repentance", "The Medicine of God's Love"
Bad titles: "Holy Week Sermon", "Homily on the Gospel Reading", "Fr. John's Message"

### Step 3 — Generate Description

Structure:

1. **Hook** (1–2 sentences): Summarize the sermon's core message. This appears in YouTube search results — make it count.
2. **Summary** (3–5 sentences): Capture key points and trajectory of the sermon. Write in third person ("the sermon explores...", "we are reminded that..."). Do not name the preacher.
3. **Scripture line**: `**Scripture**: ` followed by all referenced passages using standard abbreviations. Only passages actually mentioned in the transcript.
4. **Parish line** (always last, preceded by a blank line):
   ```
   Saint Demetrios Greek Orthodox Church — Seattle, WA
   ```

#### Scripture Abbreviations

Use these standard forms: Gen., Ex., Lev., Num., Deut., Josh., Judg., Ruth, 1 Sam., 2 Sam., 1 Kings, 2 Kings, 1 Chron., 2 Chron., Neh., Job, Ps., Prov., Eccles., Isa., Jer., Ezek., Dan., Hos., Joel, Amos, Jonah, Mic., Hab., Zeph., Hag., Zech., Mal., Matt., Mark, Luke, John, Acts, Rom., 1 Cor., 2 Cor., Gal., Eph., Phil., Col., 1 Thess., 2 Thess., 1 Tim., 2 Tim., Titus, Philem., Heb., James, 1 Pet., 2 Pet., 1 John, 2 John, 3 John, Jude, Rev.

Tone guidelines:
- **Do**: "In this homily, we hear how Christ's love transforms suffering into hope."
- **Do**: "The parable of the talents challenges us to use our gifts boldly."
- **Don't**: "Pastor Mike delivers a powerful sermon about God's plan for your life."
- **Don't**: "This amazing message will change the way you think about faith!"

Do NOT include timestamps, links, or promotional content.

### Step 4 — Present Output

Output in this exact format (do not deviate):

```
**Title**: Month D, YYYY • Sermon Title Here

**Description**:
[Hook paragraph]

[Summary paragraph]

**Scripture**: [references]

Saint Demetrios Greek Orthodox Church — Seattle, WA
```

If no scripture passages were referenced in the sermon, omit the Scripture line entirely.

#### Worked Example

**Title**: April 8, 2026 • The Medicine of God's Love

**Description**:
Holy Unction is not magic — it is the Church's way of saying, "We see your suffering, and you are not alone."

In this Holy Wednesday homily, the mystery of Holy Unction is explored through the image of a parent kissing a child's scraped knee. The kiss doesn't heal the wound, but it communicates something deeper — that we are loved in our pain. The sacrament of anointing connects our bodily suffering to Christ's own, inviting us to find healing not through escape, but through presence.

**Scripture**: James 5:14–15, Mark 6:13

Saint Demetrios Greek Orthodox Church — Seattle, WA

### Step 5 — Offer Alternatives

After presenting, offer 2 alternative title options that emphasize different angles of the sermon. Let the user pick or request further changes.

## Reference

- [Sermon metadata rules](./references/sermon-metadata-rules.md) — Full rules document with examples
