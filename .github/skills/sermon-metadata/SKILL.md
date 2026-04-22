---
name: sermon-metadata
description: "Generate YouTube title and description for a sermon. Use when: creating sermon metadata, writing sermon titles, writing sermon descriptions, formatting sermon uploads, YouTube sermon metadata."
argument-hint: "Provide a sermon transcript (pasted text, file path, or YouTube URL)"
---

# Sermon Title & Description Generator

Generate a formatted YouTube title and description for a sermon delivered at Saint Demetrios Greek Orthodox Church, Seattle, WA.

## When to Use

- After a sermon is recorded and you need title + description for YouTube upload
- When reviewing or rewriting existing sermon metadata
- When given a sermon transcript (pasted, file, or URL) and asked for metadata

## Accepted Inputs

The user may provide any of:

1. **Transcript pasted directly into chat** — use as-is
2. **File path** to a transcript file — read it
3. **YouTube video URL** — fetch the page, extract available transcript/description context

If no sermon date is provided, ask.

## Procedure

### Step 1 — Extract Core Content

Read the full transcript. Identify:

- **Central theme**: The single overarching message or exhortation
- **Key points**: 2–4 supporting ideas or arguments
- **Scripture passages**: Every Bible passage explicitly quoted or referenced (book, chapter, verse)
- **Sermon date**: The date the sermon was delivered

Do NOT fabricate scripture references. Only include passages actually present in the transcript.

### Step 2 — Generate Title

Format: `Month D, YYYY • Sermon Title`

Rules:
- Date prefix uses full month name, day without leading zero, 4-digit year, then ` • ` (space bullet space)
- Sermon title portion: 4–10 words, short and compelling
- Reflect the central theme, not the liturgical occasion
- Avoid generic titles ("Sunday Sermon", "Homily")
- Do not include church name or pastor's name
- Use active, engaging language that draws a viewer in
- Reference the theme of scripture, not the citation (e.g., "What It Means to Take Up Your Cross" not "Matthew 16:24 Homily")

### Step 3 — Generate Description

Structure:

1. **Hook** (1–2 sentences): Summarize the sermon's core message. This appears in YouTube search results — make it count.
2. **Summary** (3–5 sentences): Capture key points and trajectory of the sermon.
3. **Scripture line**: `**Scripture**: ` followed by all referenced passages using standard abbreviations (e.g., Matt. 16:24, Rom. 8:28, John 3:16). Only passages actually mentioned in the transcript.
4. **Parish line** (always last, preceded by a blank line):
   ```
   Saint Demetrios Greek Orthodox Church — Seattle, WA
   ```

Tone: Reverent but accessible — suitable for both parishioners and newcomers.

Do NOT include timestamps, links, or promotional content.

### Step 4 — Present Output

Output in this exact format:

```
**Title**: Month D, YYYY • Sermon Title Here

**Description**:
[Hook paragraph]

[Summary paragraph]

**Scripture**: [references]

Saint Demetrios Greek Orthodox Church — Seattle, WA
```

### Step 5 — Offer Alternatives

After presenting, offer 2 alternative title options that emphasize different angles of the sermon. Let the user pick or request further changes.

## Reference

- [Sermon metadata rules](./references/sermon-metadata-rules.md) — Full rules document with examples
