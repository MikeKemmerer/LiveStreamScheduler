#!/usr/bin/env python3
"""Fetch license-clean Orthodox icons for 2026 dated sermons from Wikimedia Commons.

For each dated sermon in the parish playlist this searches Wikimedia Commons for a
matching icon/illustration, accepts only freely-licensed images (Public Domain,
CC0, CC BY, CC BY-SA), and downloads a ~1280px copy named:

    YYYY-MM-DD - SUGGESTED TEXT.<ext>

A manifest.txt records the Commons source page and license for every file so the
licensing is verifiable (PD/CC0 need no attribution; CC BY/BY-SA attributions are
captured for safety).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "thumbnails" / "2026"
UA = "StDemetriosThumbnails/1.0 (Saint Demetrios GOC Seattle; parish thumbnail use)"

# Accepted licenses (substring match, case-insensitive). PD/CC0 preferred.
ACCEPT = ["public domain", "cc0", "cc by", "cc-by", "pd-", "no restrictions"]
REJECT = ["non-free", "fair use", "copyright", "all rights reserved"]
ALLOWED_EXT = {"jpg", "jpeg", "png", "tif", "tiff"}

# Style preference: Greek first, English next, everything else last. Nothing is
# rejected outright -- if Greek is unavailable we fall back to English, then any
# other free Orthodox icon.
GREEK_TERMS = [
    "greek", "byzantine", "byzantium", "cretan", "crete", "athos", "athonite",
    "meteora", "constantinople", "thessalonica", "thessaloniki", "macedonia",
    "mistra", "mystras", "cyprus", "cypriot", "hellenic", "ohrid", "langadas",
    "theophanes", "tzanes", "damaskinos", "klontzas", "lambardos",
]
ENGLISH_TERMS = [
    "english", "england", "britain", "british", "london", "oxford", "cambridge",
    "united kingdom", "u.k.", " uk ",
]

# A 1280x720 (16:9) crop must fit inside the source, so require both dimensions.
MIN_WIDTH = 1280
MIN_HEIGHT = 720

# Download a large CDN-cached thumbnail (not the original file) -- Wikimedia
# heavily rate-limits original downloads but serves thumbnails freely. 1920px
# wide still leaves plenty of room for a 16:9 crop.
THUMB_WIDTH = 1920

# (date, suggested text, [search queries in priority order])
ITEMS: list[tuple[str, str, list[str]]] = [
    ("2026-05-27", "FREE IN CHAINS", ["John the Russian icon", "Saint John the Russian"]),
    ("2026-05-11", "THE ALPHABET OF FAITH", ["Cyril and Methodius icon", "Saints Cyril Methodius"]),
    ("2026-05-08", "THE BELOVED DISCIPLE", ["John the Theologian icon", "John the Evangelist icon"]),
    ("2026-05-06", "THE PATIENCE OF JOB", ["Job the prophet icon", "Prophet Job icon"]),
    ("2026-04-26", "WHO WILL ROLL IT AWAY", ["Myrrhbearers icon", "Myrrh-bearing women tomb icon"]),
    ("2026-04-23", "GREATER THAN DEATH", ["Saint George icon", "Saint George dragon icon"]),
    ("2026-04-19", "BLESSED DOUBT", ["Incredulity of Thomas icon", "Doubting Thomas icon"]),
    ("2026-04-17", "THE LIFE-GIVING SPRING", ["Life-giving Spring icon", "Zoodochos Pege icon"]),
    ("2026-04-11", "HE IS RISEN", ["Anastasis icon", "Resurrection of Christ icon"]),
    ("2026-04-10", "EVEN IN THE TOMB", ["Harrowing of Hell icon", "Descent into Hades icon"]),
    ("2026-04-10b", "AT THE CROSS", ["Crucifixion of Christ icon", "Crucifixion icon Byzantine"]),
    ("2026-04-09", "OUTSIDE OF TIME", ["Mystical Supper icon", "Last Supper icon Byzantine"]),
    ("2026-04-08", "HE IS WAITING", ["Christ the Bridegroom icon", "sinful woman anointing Christ icon"]),
    ("2026-04-08b", "THE MEDICINE OF LOVE", ["Holy Unction icon", "Christ Pantocrator icon"]),
    ("2026-04-08c", "LONG-SUFFERING LOVE", ["Job the prophet icon", "Christ Bridegroom icon"]),
    ("2026-04-07", "BEHOLD THE BRIDEGROOM", ["Christ the Bridegroom icon", "Nymphios icon"]),
    ("2026-04-07b", "KEEP YOUR LAMP LIT", ["Wise and Foolish Virgins icon", "Ten Virgins parable icon"]),
    ("2026-04-05", "THE WORK BEGINS", ["Entry into Jerusalem icon", "Palm Sunday icon"]),
    ("2026-03-29", "PERSPECTIVE CHANGES ALL", ["Mary of Egypt icon", "Saint Mary of Egypt icon"]),
    ("2026-03-28", "THE AKATHIST HYMN", ["Theotokos Platytera icon", "Akathist Theotokos icon"]),
    ("2026-03-27", "SEEK FIRST THE KINGDOM", ["Matrona of Thessalonica icon", "Christ teaching icon"]),
    ("2026-03-25", "ANNUNCIATION", ["Annunciation icon", "Annunciation Theotokos icon"]),
    ("2026-03-22", "ONE STEP HIGHER", ["Ladder of Divine Ascent icon", "John Climacus ladder icon"]),
    ("2026-03-20", "GRACE IN WEARINESS", ["Saint Sabas icon", "Sabbas the Sanctified icon"]),
    ("2026-03-15", "WORTH MORE THAN THE WORLD", ["Adoration of the Cross icon", "Precious Cross icon"]),
    ("2026-03-13", "THINGS ABOVE", ["Heavenly Jerusalem icon", "Ladder of Divine Ascent icon"]),
    ("2026-03-13b", "TRUE HUMILITY", ["Publican and Pharisee icon", "Pharisee Publican parable icon"]),
    ("2026-03-08", "HEALED AND MADE WHOLE", ["Gregory Palamas icon", "Saint Gregory Palamas icon"]),
    ("2026-03-06", "ENLIGHTEN MY DARKNESS", ["Theotokos Hodegetria icon", "Hodegetria icon"]),
    ("2026-03-06b", "FIND YOUR WAY HOME", ["Return of the Prodigal Son icon", "Prodigal Son icon"]),
    ("2026-03-02", "FOUR VIRTUES", ["Nicholas Planas icon", "Sermon on the Mount icon"]),
    ("2026-03-01", "THE TRIUMPH OF ORTHODOXY", ["Triumph of Orthodoxy icon", "Sunday of Orthodoxy icon"]),
    ("2026-02-23", "GREAT LENT BEGINS", ["Polycarp of Smyrna icon", "Saint Polycarp icon"]),
    ("2026-02-22", "FORGIVENESS SUNDAY", ["Expulsion from Paradise icon", "Adam and Eve expelled icon"]),
    ("2026-02-21", "HOW SHOULD WE PRAY", ["Christ praying Gethsemane icon", "Agony in the Garden icon"]),
    ("2026-02-21b", "REMEMBERING THE SAINTS", ["Synaxis of monastic saints icon", "All Saints icon"]),
    ("2026-02-17", "ST. THEODORE THE RECRUIT", ["Theodore Tiro icon", "Theodore of Amasea icon"]),
    ("2026-02-15", "THE GREAT JUDGMENT", ["Last Judgment icon", "Last Judgement Byzantine icon"]),
    ("2026-02-14", "PRAY FOR ONE ANOTHER", ["Anastasis icon", "Resurrection of the dead icon"]),
    ("2026-02-14b", "SATURDAY OF SOULS", ["Resurrection of the dead icon", "Anastasis icon"]),
    ("2026-02-10", "ALWAYS A DISCIPLE", ["Charalampos icon", "Saint Haralambos icon"]),
    ("2026-02-08", "COME HOME", ["Return of the Prodigal Son icon", "Prodigal Son icon"]),
    ("2026-02-06", "ST. PHOTIOS THE GREAT", ["Photios I of Constantinople icon", "Saint Photios icon"]),
    ("2026-02-02", "THE MEETING OF THE LORD", ["Presentation of Jesus at the Temple icon", "Hypapante icon"]),
    ("2026-02-01", "HE SEEKS YOUR HEART", ["Publican and Pharisee icon", "Pharisee Publican parable icon"]),
    ("2026-01-25", "ST. GREGORY THE THEOLOGIAN", ["Gregory the Theologian icon", "Gregory Nazianzus icon"]),
    ("2026-01-24", "ST. XENIA", ["Xenia of Saint Petersburg icon", "Saint Xenia icon"]),
    ("2026-01-21", "ST. MAXIMOS THE CONFESSOR", ["Maximus the Confessor icon", "Saint Maximus Confessor icon"]),
    ("2026-01-20", "THE CHEERFUL SAINT", ["Euthymius the Great icon", "Saint Euthymius icon"]),
    ("2026-01-19", "THE DESERT FATHERS", ["Macarius of Egypt icon", "Saint Macarius the Great icon"]),
    ("2026-01-18", "THE POWER OF GRATITUDE", ["Healing of the ten lepers icon", "ten lepers icon"]),
    ("2026-01-17", "ST. ANTHONY THE GREAT", ["Anthony the Great icon", "Saint Anthony the Great icon"]),
    ("2026-01-11", "IN THE BLINK OF AN EYE", ["Baptism of Christ icon", "Theophany icon"]),
    ("2026-01-05", "BLESSING OF THE WATERS", ["Theophany icon", "Baptism of Christ Jordan icon"]),
    ("2026-01-04", "REPENT BEGINNING TO END", ["John the Baptist preaching icon", "John the Forerunner icon"]),
    ("2025-12-31", "AT HOME IN GOD", ["Melania the Younger icon", "Nativity of Christ icon"]),
]


def _get(url: str, *, timeout: int = 40) -> bytes:
    """GET with exponential backoff on HTTP 429 (Wikimedia rate limiting)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    delay = 10.0
    attempts = 9
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < attempts - 1:
                print(f"    (429; backing off {delay:.0f}s)")
                time.sleep(delay)
                delay = min(delay * 2, 300)
                continue
            raise
    raise RuntimeError("unreachable")


def _api(params: dict) -> dict:
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
    return json.loads(_get(url))


def _license_ok(short: str) -> bool:
    s = (short or "").lower()
    if any(bad in s for bad in REJECT):
        return False
    return any(ok in s for ok in ACCEPT)


def _style_rank(title: str, artist: str) -> tuple[int, str]:
    """Lower is better: 0 = Greek/Byzantine, 1 = English, 2 = other."""
    blob = f"{title} {artist}".lower()
    if any(t in blob for t in GREEK_TERMS):
        return 0, "Greek"
    if any(t in blob for t in ENGLISH_TERMS):
        return 1, "English"
    return 2, "other"


def search_image(query: str, used_titles: set[str]) -> dict | None:
    """Return the best free, crop-safe, not-yet-used image for a query, preferring
    Greek, then English, then other styles. Returns dict or None."""
    data = _api({
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": "6",
        "gsrlimit": "30",
        "prop": "imageinfo",
        "iiprop": "url|extmetadata|mime|size",
        "iiurlwidth": str(THUMB_WIDTH),
    })
    pages = list(data.get("query", {}).get("pages", {}).values())
    pages.sort(key=lambda p: p.get("index", 999))
    candidates: list[tuple[int, int, dict]] = []
    for order, p in enumerate(pages):
        title = p.get("title", "")
        if title in used_titles:
            continue
        ext = title.rsplit(".", 1)[-1].lower()
        if ext not in ALLOWED_EXT:
            continue
        ii = (p.get("imageinfo") or [{}])[0]
        md = ii.get("extmetadata", {})
        short = md.get("LicenseShortName", {}).get("value", "")
        if not _license_ok(short):
            continue
        # Gate on the rendered THUMBNAIL size (what we actually download). Thumbs
        # are CDN-cached and barely rate-limited, unlike the original-file URL.
        tw = int(ii.get("thumbwidth") or 0)
        th = int(ii.get("thumbheight") or 0)
        if tw < MIN_WIDTH or th < MIN_HEIGHT:
            continue
        thumb_url = ii.get("thumburl")
        if not thumb_url:
            continue
        artist = md.get("Artist", {}).get("value", "")
        rank, style = _style_rank(title, artist)
        candidates.append((rank, order, {
            "title": title,
            "url": thumb_url,
            "license": short,
            "artist": artist,
            "descurl": ii.get("descriptionurl", ""),
            "size": f"{tw}x{th}",
            "style": style,
        }))
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c[0], c[1]))
    return candidates[0][2]


def download(url: str, dest: Path) -> None:
    dest.write_bytes(_get(url, timeout=90))


def _manifest_append(line: str) -> None:
    with (OUT_DIR / "manifest.txt").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not (OUT_DIR / "manifest.txt").exists():
        _manifest_append("# 2026 sermon thumbnail icons — Greek Orthodox / Byzantine, source & license\n")
    ok = 0
    missing: list[str] = []
    used_titles: set[str] = set()

    # Resume support: any image already present for a date+text is left alone so
    # repeated runs make net progress without re-hitting Wikimedia (which IP-
    # throttles aggressively). Existing filenames also reserve uniqueness.
    existing = {p.name for p in OUT_DIR.glob("* - *.*") if p.name != "manifest.txt"}

    # Reserve titles already used in prior runs (parsed from the manifest) so we
    # never download the same Commons image twice across runs.
    manifest = OUT_DIR / "manifest.txt"
    if manifest.exists():
        for line in manifest.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("source:"):
                slug = line.split("/wiki/", 1)[-1]
                if slug.startswith("File:"):
                    used_titles.add(urllib.parse.unquote(slug).replace("_", " "))

    for date_key, text, queries in ITEMS:
        date_label = date_key.rstrip("abc") if date_key[-1].isalpha() else date_key
        if any(n.startswith(f"{date_label} - {text}.") for n in existing):
            print(f"[=] {date_label} — {text}: already present, skipping")
            ok += 1
            continue
        hit = None
        used_query = ""
        for q in queries:
            try:
                hit = search_image(q, used_titles)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! API error for {q!r}: {exc}")
                hit = None
            if hit:
                used_query = q
                break
            time.sleep(1.5)

        if not hit:
            print(f"[ ] {date_label} — {text}: no free Greek icon found")
            missing.append(f"{date_label} — {text}")
            continue

        used_titles.add(hit["title"])
        src_ext = hit["url"].rsplit(".", 1)[-1].lower().split("?")[0]
        if src_ext not in ALLOWED_EXT:
            src_ext = "jpg"
        fname = f"{date_label} - {text}.{src_ext}"
        dest = OUT_DIR / fname
        try:
            download(hit["url"], dest)
        except Exception as exc:  # noqa: BLE001
            print(f"[ ] {date_label} — {text}: download failed ({exc})")
            missing.append(f"{date_label} — {text}")
            used_titles.discard(hit["title"])
            continue

        ok += 1
        artist = (hit["artist"] or "").replace("\n", " ")[:120]
        print(f"[\u2713] {fname}  <{hit['style']}, {hit['license']}, {hit['size']}>")
        _manifest_append(
            f"{fname}\n    source: {hit['descurl']}\n    license: {hit['license']}\n"
            f"    style: {hit['style']}\n    size: {hit['size']}\n    credit: {artist}\n"
        )
        time.sleep(1.5)

    print(f"\nDone: {ok}/{len(ITEMS)} present in {OUT_DIR}")
    if missing:
        print("Missing (need manual pick):")
        for m in missing:
            print("  -", m)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
