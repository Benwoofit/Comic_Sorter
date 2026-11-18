"""
Comic Sorter
============

Sorts a flat folder of comic files into a tidy library:

    Destination/
        <Series Name>/
            Vol. 01/
                <Subtitle or Arc Name>/
                    Series Vol. 01 #003 - Subtitle.cbz

It parses filenames in the many shapes comics come in, previews every move in a
table so nothing happens blind, then copies or moves the files (your choice).

Run it:      python comic_sorter.py
Build exe:   python -m pip install pyinstaller
             pyinstaller --onefile --windowed --name ComicSorter comic_sorter.py
"""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import sys
import threading
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

APP_NAME = "Comic Sorter"
APP_VERSION = "1.0"
APP_TITLE_TEXT = "GW 2026"          # shown beside the logo in the window
LOGO_FILE = "gw_logo.png"           # next to the script, or in assets/ (bundled in the exe)
ICON_FILE = "comic_sorter.ico"      # window/taskbar icon built from the logo


def resource_path(name: str) -> Path:
    """Find a bundled file: in the exe's temp dir when frozen, else beside the app."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    for candidate in (base / name, base / "assets" / name,
                      Path(__file__).resolve().parent / "assets" / name,
                      Path(__file__).resolve().parent / name):
        if candidate.is_file():
            return candidate
    return base / name

COMIC_EXTS = {
    ".cbz", ".cbr", ".cb7", ".cbt", ".pdf", ".zip", ".rar", ".7z",
    ".epub", ".mobi", ".azw3",
}
# Never sorted, whatever else happens: text files, notes and OS litter.
IGNORED_EXTS = {".txt", ".text", ".nfo", ".log", ".ini", ".db", ".url", ".lnk"}
IGNORED_NAMES = {"thumbs.db", "desktop.ini", ".ds_store"}

# Words that introduce a subtitle/arc rather than being part of the series name.
SUBTITLE_LEADS = (
    "arc", "story", "saga", "chapter", "part", "book", "tpb", "oneshot", "one-shot",
)
# Tags that carry no meaning for sorting and should be dropped from the name.
# "prog" / "programme" / "progrel" - an issue marker, not part of a series.
PROG_RE = re.compile(r"\bprog(?:ramme|rel|s)?\b\.?", re.IGNORECASE)
# The prog number of 2000AD: "2000AD prog 1234" -> #1234.
PROG_NUMBER_RE = re.compile(r"\bprog\s*#?\s*(\d{1,5})\b", re.IGNORECASE)
# The 2000AD family of spellings that all mean the same series.
SERIES_ALIASES = {
    "2000 ad": "2000AD",
    "2000ad": "2000AD",
}

NOISE_TAGS = {
    "digital", "digitalhd", "hd", "webrip", "web", "scan", "scanned", "c2c", "f",
    "fixed", "repack", "remastered", "remaster", "complete", "annual", "retail",
    "proper", "internal", "dc", "marvel", "image", "darkhorse", "idw", "boom",
    "vertigo", "dynamite", "archie", "zenescope", "scout", "vault", "aftershock",
}

# Separators used between the parts of a comic filename.
SEP_PATTERN = r"[\s._\-–—]+"

# "Vol 2", "Volume 2", "v2", "v02", "v.2" and also the CSS-style "vol_1".
VOLUME_RE = re.compile(
    r"(?:\bvol(?:ume)?\.?[\s_]*|\bv\.?\s*)(\d{1,4}(?:\.\d+)?)\b", re.IGNORECASE
)
ISSUE_HASH_RE = re.compile(r"#\s*(\d{1,5}(?:\.\d+)?)")
ISSUE_WORD_RE = re.compile(
    r"\b(?:issue|iss|ch(?:apter)?|no)\.?\s*#?\s*(\d{1,5}(?:\.\d+)?)\b",
    re.IGNORECASE,
)
BOOK_RE = re.compile(r"\bbook\s*(\d{1,4})\b", re.IGNORECASE)
YEAR_RE = re.compile(r"\((?:19|20)\d{2}\)")
BRACKET_RE = re.compile(r"[\[\(\{]([^\[\]\(\)\{\}]*)[\]\)\}]")
# "(2)" / "[3]" on its own: a release count, never part of a name.
COUNT_ONLY_RE = re.compile(r"^\s*\d{1,3}\s*$")
# A release count trailing a subtitle: "(2)", "(2) of 6", "2 of 6".
COUNT_TAIL_RE = re.compile(r"[\(\[]?\s*\d{1,3}\s*[\)\]]?\s*(?:of\s*\d{1,3}\s*)?$",
                           re.IGNORECASE)
MULTISPACE_RE = re.compile(r"\s{2,}")
SAFE_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

INVALID_CHARS_REPLACEMENT = "-"


# --------------------------------------------------------------------------- #
# Name helpers
# --------------------------------------------------------------------------- #

def safe_name(name: str, fallback: str = "Unknown") -> str:
    """Make a string safe to use as a Windows file/folder name."""
    name = SAFE_CHARS_RE.sub(INVALID_CHARS_REPLACEMENT, name or "")
    name = MULTISPACE_RE.sub(" ", name).strip(" .")
    if not name:
        return fallback
    if name.upper() in WIN_RESERVED:
        name = f"_{name}"
    # Windows dislikes names ending in a dot or space.
    return name.rstrip(" .") or fallback


def title_case_keep_upper(text: str) -> str:
    """Title-case a series name while keeping ALL-CAPS acronyms and apostrophes."""
    if not text:
        return text
    if text.isupper() and len(text) > 3:
        # Long all-caps names read better in title case ("BATMAN" -> "Batman").
        text = text.title()
    else:
        words = []
        for w in text.split():
            words.append(w if (w.isupper() and len(w) > 1) else w)
        text = " ".join(words)
    # Tidy up "S'Name" -> "s' Name" style artefacts from .title()
    text = re.sub(r"\b([A-Za-z])'([A-Z])([a-z]+)", lambda m: f"{m.group(1)}'{m.group(2).lower()}{m.group(3)}", text)
    text = re.sub(r"\b([A-Za-z])'(S|T|LL|RE|VE|D|M)\b",
                  lambda m: f"{m.group(1)}'{m.group(2).lower()}", text)
    return text


def clean_tag(tag: str) -> str:
    """Normalise a bracketed tag so noise tags can be recognised."""
    return re.sub(r"[^a-z0-9\-]", "", tag.lower())


def is_noise_tag(tag: str) -> bool:
    t = clean_tag(tag)
    if not t:
        return True
    if t in NOISE_TAGS:
        return True
    # Release-group style tags: "Digital-Empire", "GreenGiant", "Zone-Empire"
    if re.fullmatch(r"\d{4}", t):
        return True
    if re.fullmatch(r"(c2c|digital|webrip|scan|fanres|hq|lowres)[\-a-z0-9]*", t):
        return True
    if re.fullmatch(r"[a-z]+(empire|giant|scans|comics|hub|zone|dts|dgn|minutemen)[a-z\-]*", t):
        return True
    if re.fullmatch(r"(dts|dgn|glorith|nem|titan|son of ultron|oroborus|pyrate)[\-a-z0-9]*", t):
        return True
    if "empire" in t or "scan" in t or "digital" in t or "webrip" in t:
        return True
    return False


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

@dataclass
class ComicInfo:
    source: Path
    series: str = ""
    volume: str = ""
    issue: str = ""
    subtitle: str = ""
    arc: str = ""
    edition: str = ""
    year: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def rel_parts(self) -> list[str]:
        """Series / Vol. NN / Subtitle, with an Arc folder inside when one was given.

        A comic with no subtitle gets no subtitle folder: it sits straight in its
        volume folder.
        """
        parts = [safe_name(self.series, "Unknown Series")]
        if self.volume:
            parts.append(safe_name(f"Vol. {self.volume}", "Vol."))
        if self.subtitle:
            parts.append(safe_name(self.subtitle, "Unknown"))
        if self.arc:
            parts.append(safe_name(self.arc, "Arc"))
        return parts

    def title_parts(self) -> list[str]:
        """The comic's full title: Series Vol. NN #NNN - Subtitle - Arc (date)."""
        series = safe_name(self.series, "Unknown Series")
        parts = [f"{series} Vol. {self.volume}" if self.volume else series]
        if self.issue:
            parts.append(f"#{self.issue}")
        if self.edition:
            parts.append(f"Ed. {self.edition}")
        if self.subtitle:
            parts.append(f"- {safe_name(self.subtitle)}")
        if self.arc:
            parts.append(f"- {safe_name(self.arc)}")
        if self.year:
            parts.append(f"({self.year})")
        return parts

    def target_name(self) -> str:
        return safe_name(" ".join(self.title_parts())) + self.source.suffix.lower()

    @property
    def confidence(self) -> str:
        if self.series and self.issue and self.volume:
            return "high"
        if self.series and self.issue:
            return "medium"
        return "low"


def _strip_extension(stem: str) -> str:
    # Handles "Comic.cbz" and also double extensions like "Comic.cbz.part"
    return stem


PUBLISHERS = {
    "dc": "DC",
    "dc comics": "DC",
    "marvel": "Marvel",
    "marvel comics": "Marvel",
}
# "DC", "DC Comics", "Marvel" before the title. Anything longer than a couple of
# words is left alone so "Marvel Zombies #1" stays its own series.
PUBLISHER_PREFIX_RE = re.compile(
    r"^\s*(dc\s+comics|dc|marvel\s+comics|marvel)\b[\s:._\-–—]*", re.IGNORECASE
)
# "001 Batman #5": a three-digit counter in front of the title.
LEADING_THREE_DIGIT_RE = re.compile(r"^\s*(\d{3})(?:[\s._\-–—]+|$)")
# A three-digit number at the end of the name: the issue number when it follows
# the subtitle ("X-Men - Dark Phoenix Saga 001").
EDITION_SUFFIX_RE = re.compile(r"(?:^|[\s\-–—])(\d{3})\s*$")
# Parts of release names that are never a subtitle: "(2) covers", "(3) of 6",
# "[AI-4320p]".
COVERS_RE = re.compile(r"^\s*(?:[\(\[]?\s*\d{1,3}\s*[\)\]]?\s*)?(?:covers?|cover\s*[a-z])\s*$",
                       re.IGNORECASE)
OF_RE = re.compile(r"^\s*(?:\d{1,3}\s*)?of\s*\d{1,3}\s*$", re.IGNORECASE)
RELEASE_TAG_RE = re.compile(r"\b[A-Za-z]{2,5}\s*[-_]\s*\d{3,4}\s*[pi]\b")
# A bare "Issue"/"Iss"/"No." left over once its number was taken.
ISSUE_WORD_CLEAN_RE = re.compile(r"\b(?:issue|iss|no)\.?(?=[\s\-–—]|$)", re.IGNORECASE)
MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
MONTH_DATE_RE = re.compile(
    r"^(?:(\d{1,2})[\s\-/.]*)?(" + "|".join(sorted(MONTHS, key=len, reverse=True)) +
    r")[a-z]*\.?[\s\-/.,]*((?:19|20)\d{2})$", re.IGNORECASE)
YEAR_DATE_RE = re.compile(r"^((?:19|20)\d{2})[\s\-/.,]*(\d{1,2})?[\s\-/.,]*(\d{1,2})?$")


def extract_publisher(text: str) -> tuple[str, str]:
    """'DC Batman #1' -> ('DC', 'Batman #1'); 'Marvel Zombies #1' -> ('', ...)."""
    m = PUBLISHER_PREFIX_RE.match(text)
    if not m:
        return "", text
    rest = text[m.end():].strip(" :._-–—")
    if len(rest.split()) < 1:
        return "", text
    return PUBLISHERS[re.sub(r"\s+", " ", m.group(1).lower())], rest


def parse_date_tag(tag: str) -> str:
    """Turn a bracketed date into '2026' or '2026-01'.

    Accepts (2026), (2026-01), (2026/01), (01-2026), (Jan 2026), (January 2026),
    (2026-01-15). Anything that is not a date returns "".
    """
    t = re.sub(r"\s+", " ", tag.strip())
    m = MONTH_DATE_RE.match(t)
    if m:
        month = MONTHS[m.group(2).lower()]
        return f"{m.group(3)}-{month:02d}"
    m = YEAR_DATE_RE.match(t)
    if m:
        year = m.group(1)
        month = m.group(2)
        if month and 1 <= int(month) <= 12:
            return f"{year}-{int(month):02d}"
        return year
    return ""


def parse_filename(path: Path) -> ComicInfo:
    """Best-effort parse of a comic filename into series / volume / issue / subtitle."""
    info = ComicInfo(source=path)
    raw = path.stem
    # "Hellboy_Vol_1_Seed_of_Destruction" was spaced with underscores, so its
    # lower-case words are really capitalised words.
    underscore_style = bool(re.search(r"[a-z]_[a-zA-Z]", raw))
    # Remove year in parentheses first, remembering it.
    year_match = YEAR_RE.search(raw)
    if year_match:
        info.year = year_match.group(0).strip("()")
        raw = raw.replace(year_match.group(0), " ")

    # "AI-4320p", "x265-1080p" style release tags are never a subtitle.
    raw = RELEASE_TAG_RE.sub(" ", raw)

    # Pull out bracketed groups: a date there belongs in the title, the rest are
    # either the subtitle or release noise.
    bracket_tags: list[str] = []
    date_tag = ""
    release_note = False

    def _grab(m: re.Match) -> str:
        nonlocal date_tag, release_note
        tag = m.group(1).strip()
        if (COUNT_ONLY_RE.match(tag) or COVERS_RE.match(tag) or OF_RE.match(tag)
                or re.match(r"^\s*\(?\s*\d{1,3}\s*\)?\s*of\s*\d{1,3}\s*$", tag, re.IGNORECASE)):
            release_note = True
            return " "
        if not date_tag:
            found = parse_date_tag(tag)
            if found:
                date_tag = found
                return " "
        bracket_tags.append(tag)
        return " "

    raw = BRACKET_RE.sub(_grab, raw)

    volume = ""
    issue = ""
    subtitle = ""
    edition = ""

    # Underscores/dots are word characters for regex, so "Saga_Vol_3" needs the
    # separators normalised before any of the patterns below can see "Vol 3".
    raw = re.sub(r"[._]+", " ", raw)
    raw = MULTISPACE_RE.sub(" ", raw).strip()

    # A three-digit number in front of the title is a file counter, not a name:
    # "001 Batman #5" -> series "Batman". It is only the issue when nothing else
    # in the name says what the issue is (checked further down).
    leading_number = ""
    lead_match = LEADING_THREE_DIGIT_RE.match(raw)
    lead_rest = raw[lead_match.end():].strip(" -–—") if lead_match else ""
    if lead_match and looks_like_title(lead_rest):
        leading_number = lead_match.group(1)
        raw = lead_rest

    # A dash always separates the title from the subtitle: "X-Men - Dark Phoenix
    # Saga" is series "X-Men", arc "Dark Phoenix Saga", never a hyphenated series.
    head, dash_rest = split_on_dash(raw)

    # 2000AD numbers its issues by prog: "2000AD prog 1234" -> #1234.
    prog_issue = ""
    prog_match = PROG_NUMBER_RE.search(head)
    if prog_match:
        prog_issue = prog_match.group(1)
        head = head[: prog_match.start()] + " " + head[prog_match.end():]

    # A three-digit number anywhere in the name is the issue number: "X-Men -
    # Dark Phoenix Saga 001", "Batman 003 - The City of Owls", "Saga Vol 1 007".
    three_digit = ""
    ed_match = EDITION_SUFFIX_RE.search(head)
    if ed_match:
        three_digit = ed_match.group(1)
        head = head[: ed_match.start()] + " " + head[ed_match.end():]

    vol_match = VOLUME_RE.search(head)
    if vol_match:
        volume = _norm_number(vol_match.group(1))
        head = head[: vol_match.start()] + " " + head[vol_match.end():]

    if dash_rest:
        head = _merge_number_before_dash(head)

    issue_match = ISSUE_HASH_RE.search(head) or ISSUE_WORD_RE.search(head)
    if issue_match and three_digit:
        # "#07 ... 003": the three-digit number is the #, the other is the edition.
        issue = _norm_number(three_digit)
        edition = _norm_number(issue_match.group(1)) if issue_match else ""
        head = head[: issue_match.start()] + " " + head[issue_match.end():]
    elif issue_match:
        issue = _norm_number(issue_match.group(1))
        head = head[: issue_match.start()] + " " + head[issue_match.end():]
    else:
        bare = split_bare_issue(head)
        if bare:
            head, after = split_bare_issue_text(head)
            issue = _norm_number(bare[0])
            dash_rest = " - ".join(part for part in (after.strip(" -"), dash_rest) if part)
        book_match = BOOK_RE.search(head)
        if book_match:
            issue = _norm_number(book_match.group(1))
            head = head[: book_match.start()] + " " + head[book_match.end():]

    # Two dashes split the name three ways: series - subtitle - arc (and a third
    # dash just joins the arc text: "Old Man Logan - Part 2").
    arc = ""
    dash_parts = split_all_on_dash(dash_rest)
    subtitle_text = dash_parts[0] if dash_parts else ""
    if len(dash_parts) > 1:
        arc = _tidy_subtitle(" ".join(dash_parts[1:]))

    # The subtitle comes from after the dash, else from a bracketed tag that is
    # not release noise.
    subtitle = _tidy_subtitle(subtitle_text)
    if not subtitle:
        for tag in bracket_tags:
            if is_noise_tag(tag):
                continue
            subtitle = _tidy_subtitle(tag)
            if subtitle:
                break

    if three_digit and not issue:
        issue = _norm_number(three_digit)
        edition = ""
    if prog_issue and not issue:
        issue = _norm_number(prog_issue)
    if leading_number and not issue:
        issue = _norm_number(leading_number)

    # The same rule inside the subtitle: "Dark Phoenix Saga 001".
    if subtitle:
        ed_match = EDITION_SUFFIX_RE.search(subtitle)
        if ed_match:
            tail_number = ed_match.group(1)
            subtitle = subtitle[: ed_match.start()].strip(" -–—")
            if not issue:
                issue = _norm_number(tail_number)
            elif not edition:
                edition = tail_number

    # "Death of the Family - Part Two 001": a three-digit number in the arc is
    # still the issue.
    if arc:
        ed_match = EDITION_SUFFIX_RE.search(arc)
        if ed_match:
            tail_number = ed_match.group(1)
            arc = arc[: ed_match.start()].strip(" -–—")
            if not issue:
                issue = _norm_number(tail_number)
            elif not edition:
                edition = tail_number

    # A subtitle that is nothing but a release note is no subtitle at all.
    if subtitle and (COVERS_RE.match(subtitle) or OF_RE.match(subtitle)
                     or COUNT_ONLY_RE.match(subtitle)):
        subtitle = ""

    # "(2) covers" / "(2) of 6" trailing the subtitle: the count is not part of
    # the name, so "Court of Owls (2) of 6" keeps just "Court of Owls". A count
    # left without its brackets ("Court of Owls of 6") is trimmed too.
    if subtitle:
        before = subtitle
        subtitle = strip_release_note_tail(subtitle)
        if not subtitle:
            subtitle = before if not release_note else ""

    # "'v2' style volume written after the subtitle": "... - Family Matters v02".
    if not volume:
        loose = split_trailing_volume(subtitle)
        if loose[1]:
            subtitle = loose[0]
            volume = _norm_volume(loose[1])

    # "Issue 300" / "No. 300" is only an issue marker: the word is not a series.
    head = ISSUE_WORD_CLEAN_RE.sub(" ", head)

    raw = head


    if not volume:
        raw, loose_vol = split_trailing_volume(raw.strip())
        volume = loose_vol
        if volume:
            volume = _norm_volume(volume)

    # "Vol. 002" becomes "Vol. 02" for a tidy folder name.
    if volume:
        volume = _norm_volume(volume)

    publisher, without_publisher = extract_publisher(raw.strip())
    if publisher and _tidy_series(without_publisher):
        raw = without_publisher
    else:
        publisher = ""

    series = _tidy_series(raw)
    if not series:
        # The dashes took the whole name as subtitle/arc: fall back to the words
        # in front of the first dash so a title is never lost.
        series = _tidy_series(split_on_dash(path.stem)[0])
    if publisher:
        series = f"{publisher} {series}"
    if underscore_style and series and not series.isupper():
        series = title_case_keep_upper(series)
    if underscore_style and subtitle:
        subtitle = title_case_keep_upper(subtitle)

    info.series = series or "Unknown Series"
    # No volume in the name means no Volume folder and no "Vol." in the title.
    info.volume = volume
    info.issue = issue
    info.subtitle = subtitle
    info.arc = arc
    info.edition = edition
    info.year = date_tag or info.year

    if not issue:
        info.notes.append("no issue number")
    if not series:
        info.notes.append("series unclear")
    return info


BARE_ISSUE_RE = re.compile(r"(?:^|[\s\-–—])(\d{1,5})(.*)$")


def split_bare_issue(text: str) -> tuple[str, str] | None:
    """'Saga 012' -> ('012', 'Saga 012'); 'Spawn 300' -> ('300', 'Spawn 300').

    The number must be the last word, and the name must have something before it.
    """
    m = BARE_ISSUE_RE.search(text)
    if not m or m.group(2).strip(" -–—"):
        return None
    if not text[: m.start()].strip(" -–—"):
        return None
    return m.group(1), text


def split_bare_issue_text(text: str) -> tuple[str, str]:
    """'Saga 012 - Chapter Two' -> ('Saga 012 - Chapter', 'Two').

    Returns the name before the number (its trailing separator trimmed) and
    whatever came after the number.
    """
    m = BARE_ISSUE_RE.search(text)
    if not m:
        return text, ""
    return text[: m.start()].strip(" -–—"), m.group(2)


def _norm_number(value: str) -> str:
    value = value.strip().lstrip("0") or "0"
    if value in ("0", ""):
        value = "0"
    try:
        as_float = float(value)
        if as_float == int(as_float):
            return f"{int(as_float):03d}" if int(as_float) < 1000 else str(int(as_float))
        return value
    except ValueError:
        return value


def _norm_volume(value: str) -> str:
    try:
        as_float = float(value)
        if as_float == int(as_float):
            return f"{int(as_float):02d}"
        return value
    except ValueError:
        return value or "01"


DASH_SPLIT_RE = re.compile(r"\s*[–—]\s*|\s+-+\s*|\s*-+\s+")


TRAILING_NUMBER_RE = re.compile(r"(?:^|[\s\-–—])(\d{1,5})\s*$")


def _merge_number_before_dash(head: str) -> str:
    """'Saga 12 ' before a dash -> 'Saga 12', so the number reads as the issue.

    Keeps the number attached to the title while removing the dash gap, which is
    what lets split_bare_issue() see it.
    """
    return head.rstrip()


def split_on_dash(text: str) -> tuple[str, str]:
    """'X-Men - Dark Phoenix Saga' -> ('X-Men', 'Dark Phoenix Saga').

    A hyphen inside a word ("X-Men", "Spider-Man", "one-shot") is left alone; only
    a dash with a space on at least one side, or a real en/em dash, separates.
    """
    m = DASH_SPLIT_RE.search(text)
    if not m:
        return text, ""
    head = text[: m.start()].strip(" -–—")
    tail = text[m.end():].strip(" -–—")
    if not head:
        return text, ""
    return head, tail


def split_all_on_dash(text: str) -> list[str]:
    """Split on every separator dash, keeping hyphenated words whole."""
    if not text:
        return []
    parts = [p.strip(" -–—") for p in DASH_SPLIT_RE.split(text)]
    return [p for p in parts if p]


def strip_release_note_tail(text: str) -> str:
    """'Court of Owls (2) of 6' -> 'Court of Owls'; 'Batman (2)' -> 'Batman'."""
    text = re.sub(r"[\s\-–—]*(?:\(\s*\d{1,3}\s*\)|\[\s*\d{1,3}\s*\])"
                  r"(?:\s*of\s*\d{1,3})?\s*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[\s\-–—]+\d{1,3}\s+of\s+\d{1,3}\s*$", "", text, flags=re.IGNORECASE)
    # A count whose brackets were taken out earlier: "Court of Owls of 6".
    text = re.sub(r"[\s\-–—]+of\s+\d{1,3}\s*$", " of", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+of\s*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[\s\-–—]+\d{1,3}\s+(?:covers?|cover\s*[a-z])\s*$", "", text,
                  flags=re.IGNORECASE)
    return text.strip(" -–—")


def _tidy_subtitle(text: str) -> str:
    # "(2) covers", "3 covers", "(2) of 6" and "[AI-4320p]" are release notes.
    text = PROG_RE.sub(" ", text)
    text = COVERS_RE.sub(" ", text)
    text = OF_RE.sub(" ", text)
    text = RELEASE_TAG_RE.sub(" ", text)
    text = re.sub(r"[–—]+", " ", text)
    text = re.sub(r"(?:^|\s)-(?:\s|$)", " ", text)
    text = re.sub(r"[\s._]+", " ", text).strip()
    kept = [w for w in text.split() if not is_noise_tag(w)]
    text = " ".join(kept).strip(" -_")
    if not text:
        return ""
    # "2000AD" keeps its own spelling instead of being title-cased to "2000Ad".
    if re.fullmatch(r"2000\s*ad", text, re.IGNORECASE):
        return "2000AD"
    return SERIES_ALIASES.get(text.lower(), title_case_keep_upper(text))


VOLUME_LOOSE_RE = re.compile(r"\s+\b(?:vol(?:ume)?|v)\s*[.]?\s*(\d{1,4})\s*$",
                             re.IGNORECASE)
VOLUME_LEAD_RE = re.compile(r"^\s*(?:vol(?:ume)?|v)\s*[.]?\s*(\d{1,4})\b[\s\-–—]*(.*)$",
                            re.IGNORECASE)


def split_leading_volume(text: str) -> tuple[str, str]:
    """Split 'Vol 3 - Arc Two' into ('', 'Arc Two'); anything else is left alone."""
    m = VOLUME_LEAD_RE.match(text)
    if m:
        return "", m.group(2)
    return text, ""


def split_trailing_volume(text: str) -> tuple[str, str]:
    """Split 'Saga Vol 3' into ('Saga', '3'); otherwise ('Saga Vol 3', '').

    Only a leading/trailing volume token counts: 'Vol 3 - Arc Two' is not a
    trailing one, and a series whose last word is literally 'v' is left alone.
    """
    m = VOLUME_LOOSE_RE.search(text)
    if m:
        return text[: m.start()], m.group(1)
    return text, ""


def looks_like_title(text: str) -> bool:
    """True when a name could be a comic title rather than a stray number."""
    words = re.findall(r"[A-Za-z][A-Za-z'\-]{1,}", text)
    return len(words) >= 2 or (len(words) == 1 and len(words[0]) >= 3)


def _tidy_series(text: str) -> str:
    text = re.sub(r"[\s._]+", " ", text).strip()
    text = re.sub(r"\b(\d{1,4})\s+ad\b", r"\1AD", text, flags=re.IGNORECASE)
    # "2000AD prog 1234": "prog" (prog / progrel / prologue issue marker) is never
    # part of the series name.
    text = PROG_RE.sub(" ", text)
    words = [w for w in text.split() if not is_noise_tag(w)]
    text = " ".join(words).strip(" -_")
    if not text:
        return ""
    # "2000AD" keeps its own spelling instead of being title-cased to "2000Ad".
    if re.fullmatch(r"2000\s*ad", text, re.IGNORECASE):
        return "2000AD"
    return SERIES_ALIASES.get(text.lower(), title_case_keep_upper(text))


# --------------------------------------------------------------------------- #
# Planning
# --------------------------------------------------------------------------- #

@dataclass
class PlanItem:
    info: ComicInfo
    target: Path
    action: str  # "copy", "move", "skip"

    @property
    def target_folder(self) -> Path:
        return self.target.parent


def is_comic_file(path: Path) -> bool:
    """A file worth sorting: a comic format, and not a .txt/.nfo style note."""
    if path.name.lower() in IGNORED_NAMES:
        return False
    suffix = path.suffix.lower()
    if suffix in IGNORED_EXTS:
        return False
    return suffix in COMIC_EXTS


def collect_files(source: Path, recursive: bool) -> list[Path]:
    files: list[Path] = []
    if recursive:
        for root, _dirs, names in os.walk(source):
            for n in names:
                p = Path(root) / n
                if is_comic_file(p):
                    files.append(p)
    else:
        for p in sorted(source.iterdir()):
            if p.is_file() and is_comic_file(p):
                files.append(p)
    files.sort(key=lambda p: (str(p.parent).lower(), p.name.lower()))
    return files


def build_plan(
    source: Path,
    destination: Path,
    recursive: bool = False,
    mode: str = "copy",
    on_collision: str = "rename",
) -> list[PlanItem]:
    files = collect_files(source, recursive)
    plan: list[PlanItem] = []
    taken: set[str] = set()

    for f in files:
        info = parse_filename(f)
        folder = destination.joinpath(*info.rel_parts)
        target = folder / info.target_name()

        key = str(target).lower()
        if key in taken or (target.exists() and on_collision != "overwrite"):
            if on_collision == "skip":
                plan.append(PlanItem(info, target, "skip"))
                continue
            target = _unique(target)
            key = str(target).lower()
        elif target.exists() and on_collision == "overwrite":
            pass

        taken.add(key)
        plan.append(PlanItem(info, target, mode))
    return plan


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    i = 2
    while True:
        candidate = parent / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def execute_plan(plan: Iterable[PlanItem], progress=None) -> tuple[int, int, list[str]]:
    done = 0
    skipped = 0
    errors: list[str] = []
    items = list(plan)
    total = len(items)

    for idx, item in enumerate(items, 1):
        if progress:
            progress(idx, total, item)
        if item.action == "skip":
            skipped += 1
            continue
        try:
            item.target.parent.mkdir(parents=True, exist_ok=True)
            if item.action == "move":
                shutil.move(str(item.info.source), str(item.target))
            else:
                shutil.copy2(str(item.info.source), str(item.target))
            done += 1
        except Exception as exc:  # noqa: BLE001 - report, don't abort the batch
            errors.append(f"{item.info.source.name}: {exc}")
    return done, skipped, errors


def write_report(plan: Iterable[PlanItem], destination: Path) -> Path:
    out = destination / f"comic_sorter_report_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with out.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow([
            "Source file", "Series", "Volume", "Issue", "Edition", "Subtitle", "Arc",
            "Year", "Confidence", "Action", "Destination",
        ])
        for item in plan:
            i = item.info
            w.writerow([
                i.source.name, i.series, i.volume, i.issue, i.edition, i.subtitle, i.arc,
                i.year, i.confidence, item.action, str(item.target),
            ])
    return out


# --------------------------------------------------------------------------- #
# Command line (headless) mode
# --------------------------------------------------------------------------- #

def run_cli(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=f"{APP_NAME} {APP_VERSION} - sort comic files")
    ap.add_argument("source", help="folder holding the unsorted comics")
    ap.add_argument("destination", help="folder to build the sorted library in")
    ap.add_argument("--move", action="store_true", help="move files instead of copying")
    ap.add_argument("--recursive", action="store_true", help="include subfolders")
    ap.add_argument("--overwrite", action="store_true", help="overwrite same-named files")
    ap.add_argument("--dry-run", action="store_true", help="show the plan, change nothing")
    args = ap.parse_args(argv)

    source = Path(args.source).expanduser().resolve()
    destination = Path(args.destination).expanduser().resolve()
    if not source.is_dir():
        print(f"Source folder not found: {source}")
        return 2

    mode = "move" if args.move else "copy"
    plan = build_plan(
        source, destination, args.recursive, mode,
        "overwrite" if args.overwrite else "rename",
    )
    for item in plan:
        print(f"[{item.action}] {item.info.source.name}\n    -> {item.target}")
    if args.dry_run:
        print(f"\nDry run: {len(plan)} file(s) planned, nothing changed.")
        return 0

    done, skipped, errors = execute_plan(plan)
    report = write_report(plan, destination)
    verb = "moved" if mode == "move" else "copied"
    print(f"\n{done} file(s) {verb}, {skipped} skipped, {len(errors)} error(s).")
    print(f"Report: {report}")
    for e in errors:
        print(f"  ! {e}")
    return 1 if errors else 0


# --------------------------------------------------------------------------- #
# GUI
# --------------------------------------------------------------------------- #

def launch_gui() -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    class ComicSorterApp(tk.Tk):
        def __init__(self) -> None:
            super().__init__()
            self.title(f"{APP_NAME} {APP_VERSION} - {APP_TITLE_TEXT}")
            self.geometry("1080x680")
            self.minsize(900, 560)

            self.source_var = tk.StringVar()
            self.dest_var = tk.StringVar()
            self.mode_var = tk.StringVar(value="copy")
            self.collision_var = tk.StringVar(value="rename")
            self.recursive_var = tk.BooleanVar(value=False)
            self.status_var = tk.StringVar(value="Choose a source folder to begin.")
            self.summary_var = tk.StringVar(value="")

            self.plan: list[PlanItem] = []
            self.logo_image = None
            self._build_ui()
            self._set_window_icon()

        # ---------------- UI ----------------
        def _build_ui(self) -> None:
            pad = {"padx": 8, "pady": 4}
            header = ttk.Frame(self)
            header.pack(fill="x", padx=8, pady=(8, 0))
            logo = self._load_logo(header)
            if logo is not None:
                tk.Label(header, image=logo, borderwidth=0).pack(side="left", padx=(0, 10))
            titles = ttk.Frame(header)
            titles.pack(side="left", fill="x", expand=True)
            ttk.Label(titles, text=APP_TITLE_TEXT,
                      font=("Segoe UI", 20, "bold")).pack(anchor="w")
            ttk.Label(titles, text=f"{APP_NAME} {APP_VERSION} - sort your comics into "
                                   "Series / Volume / Subtitle folders",
                      foreground="#555").pack(anchor="w")

            top = ttk.LabelFrame(self, text="Folders")
            top.pack(fill="x", **pad)

            ttk.Label(top, text="Source folder (unsorted comics):").grid(
                row=0, column=0, sticky="w", padx=8, pady=(8, 2))
            ttk.Entry(top, textvariable=self.source_var).grid(
                row=0, column=1, sticky="ew", padx=4, pady=(8, 2))
            ttk.Button(top, text="Browse…", command=self.pick_source).grid(
                row=0, column=2, padx=8, pady=(8, 2))

            ttk.Label(top, text="Destination folder (sorted library):").grid(
                row=1, column=0, sticky="w", padx=8, pady=(2, 8))
            ttk.Entry(top, textvariable=self.dest_var).grid(
                row=1, column=1, sticky="ew", padx=4, pady=(2, 8))
            ttk.Button(top, text="Browse…", command=self.pick_dest).grid(
                row=1, column=2, padx=8, pady=(2, 8))
            top.columnconfigure(1, weight=1)

            opts = ttk.LabelFrame(self, text="Options")
            opts.pack(fill="x", **pad)
            ttk.Radiobutton(opts, text="Copy files (keep originals)", value="copy",
                            variable=self.mode_var, command=self.rebuild_plan).pack(
                side="left", padx=8, pady=6)
            ttk.Radiobutton(opts, text="Move files", value="move",
                            variable=self.mode_var, command=self.rebuild_plan).pack(
                side="left", padx=8, pady=6)
            ttk.Checkbutton(opts, text="Include subfolders", variable=self.recursive_var,
                            command=self.rebuild_plan).pack(side="left", padx=16, pady=6)
            ttk.Label(opts, text="If a file exists:").pack(side="left", padx=(16, 4))
            ttk.Combobox(opts, textvariable=self.collision_var, width=10, state="readonly",
                         values=("rename", "skip", "overwrite")).pack(side="left")

            cols = ("file", "series", "vol", "issue", "edition", "subtitle", "arc",
                    "year", "action", "dest")
            table = ttk.Frame(self)
            table.pack(fill="both", expand=True, **pad)
            self.tree = ttk.Treeview(table, columns=cols, show="headings", selectmode="extended")
            headings = {
                "file": ("File", 230), "series": ("Series", 180), "vol": ("Vol.", 55),
                "issue": ("#", 50), "edition": ("Ed.", 45),
                "subtitle": ("Subtitle", 150), "arc": ("Arc", 130), "year": ("Date", 70),
                "action": ("Action", 65), "dest": ("Goes to", 300),
            }
            for c, (label, width) in headings.items():
                self.tree.heading(c, text=label)
                self.tree.column(c, width=width, anchor="w", stretch=(c in ("file", "dest")))
            vsb = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
            self.tree.configure(yscrollcommand=vsb.set)
            self.tree.pack(side="left", fill="both", expand=True)
            vsb.pack(side="right", fill="y")
            self.tree.bind("<Double-1>", self.edit_row)
            self.tree.tag_configure("low", background="#ffe9e9")
            self.tree.tag_configure("medium", background="#fff8e1")

            bottom = ttk.Frame(self)
            bottom.pack(fill="x", **pad)
            ttk.Button(bottom, text="Preview", command=self.rebuild_plan).pack(side="left", padx=4)
            ttk.Button(bottom, text="Edit selected…", command=self.edit_row).pack(side="left", padx=4)
            ttk.Button(bottom, text="Save report CSV",
                       command=self.save_report).pack(side="left", padx=4)
            self.run_btn = ttk.Button(bottom, text="Sort comics", command=self.run_sort)
            self.run_btn.pack(side="right", padx=4)
            ttk.Label(bottom, textvariable=self.summary_var).pack(side="left", padx=16)

            self.progress = ttk.Progressbar(self, mode="determinate")
            self.progress.pack(fill="x", padx=8, pady=(0, 4))
            ttk.Label(self, textvariable=self.status_var, anchor="w").pack(
                fill="x", padx=8, pady=(0, 6))

        # ---------------- Logo ----------------
        def _load_logo(self, master: tk.Misc):
            """The GW logo in the top-left corner, scaled to fit the header."""
            path = resource_path(LOGO_FILE)
            try:
                image = tk.PhotoImage(master=master, file=str(path))
            except Exception:  # noqa: BLE001 - no logo is not fatal
                return None
            # Scale down by whole steps (tk only scales by integers) to ~72px tall.
            steps = max(1, round(image.height() / 72))
            if steps > 1:
                image = image.subsample(steps, steps)
            self.logo_image = image
            return image

        def _set_window_icon(self) -> None:
            """Logo in the title bar and taskbar: the PNG first, the .ico as backup."""
            png = resource_path(LOGO_FILE)
            try:
                if png.is_file():
                    icon = tk.PhotoImage(master=self, file=str(png))
                    self.iconphoto(True, icon)
                    self._icon_image = icon
                    return
            except Exception:  # noqa: BLE001
                pass
            ico = resource_path(ICON_FILE)
            try:
                if ico.is_file():
                    self.wm_iconbitmap(bitmap=str(ico))
            except Exception:  # noqa: BLE001
                pass

        # ---------------- Actions ----------------
        def pick_source(self) -> None:
            folder = filedialog.askdirectory(title="Select the folder containing your comics")
            if folder:
                self.source_var.set(folder)
                if not self.dest_var.get():
                    self.dest_var.set(str(Path(folder).parent / f"{Path(folder).name}_sorted"))
                self.rebuild_plan()

        def pick_dest(self) -> None:
            folder = filedialog.askdirectory(title="Select the destination folder")
            if folder:
                self.dest_var.set(folder)
                self.rebuild_plan()

        def rebuild_plan(self) -> None:
            self.plan = []
            self.tree.delete(*self.tree.get_children())
            self.summary_var.set("")
            self.progress["value"] = 0
            src, dst = self.source_var.get().strip(), self.dest_var.get().strip()
            if not src or not dst:
                self.status_var.set("Choose both a source and a destination folder.")
                return
            source, dest = Path(src), Path(dst)
            if not source.is_dir():
                self.status_var.set(f"Source folder not found: {source}")
                return
            try:
                self.plan = build_plan(
                    source, dest, self.recursive_var.get(), self.mode_var.get(),
                    self.collision_var.get(),
                )
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror(APP_NAME, f"Could not read the source folder:\n{exc}")
                return

            for idx, item in enumerate(self.plan):
                i = item.info
                tag = "low" if i.confidence == "low" else (
                    "medium" if i.confidence == "medium" else "")
                self.tree.insert("", "end", iid=str(idx), tags=(tag,), values=(
                    i.source.name, i.series, i.volume, i.issue, i.edition, i.subtitle,
                    i.arc, i.year, item.action, str(item.target.parent.relative_to(dest)
                                     if _is_relative(item.target.parent, dest) else item.target.parent),
                ))
            if not self.plan:
                self.status_var.set(
                    f"No comic files found in {source} "
                    f"({'including' if self.recursive_var.get() else 'top level only'})."
                )
                return
            skipped = sum(1 for p in self.plan if p.action == "skip")
            self.summary_var.set(f"{len(self.plan)} file(s) planned" +
                                 (f", {skipped} to skip" if skipped else ""))
            self.status_var.set(
                "Preview ready. Double-click a row to fix a series, volume, issue or subtitle."
            )

        def edit_row(self, _event=None) -> None:
            sel = self.tree.selection()
            if not sel:
                return
            idx = int(sel[0])
            item = self.plan[idx]
            dlg = _EditDialog(self, item)
            self.wait_window(dlg)
            if dlg.result:
                i = item.info
                (i.series, i.volume, i.issue, i.edition, i.subtitle, i.arc,
                 i.year) = dlg.result
                dest = Path(self.dest_var.get())
                item.target = dest.joinpath(*i.rel_parts) / i.target_name()
                if self.collision_var.get() == "rename":
                    item.target = _unique(item.target)
                self.tree.item(str(idx), values=(
                    i.source.name, i.series, i.volume, i.issue, i.edition, i.subtitle,
                    i.year, item.action, str(item.target.parent),
                ))

        def save_report(self) -> None:
            if not self.plan:
                messagebox.showinfo(APP_NAME, "Nothing to save yet - build a preview first.")
                return
            path = filedialog.asksaveasfilename(
                title="Save preview report", defaultextension=".csv",
                filetypes=[("CSV file", "*.csv")],
                initialfile=f"comic_sorter_preview_{datetime.now():%Y%m%d_%H%M%S}.csv",
            )
            if not path:
                return
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh)
                w.writerow(["Source file", "Series", "Volume", "Issue", "Edition",
                            "Subtitle", "Arc", "Date", "Confidence", "Action", "Destination"])
                for it in self.plan:
                    i = it.info
                    w.writerow([i.source.name, i.series, i.volume, i.issue, i.edition,
                                i.subtitle, i.arc, i.year, i.confidence, it.action,
                                str(it.target)])
            self.status_var.set(f"Report saved to {path}")

        def run_sort(self) -> None:
            if not self.plan:
                messagebox.showinfo(APP_NAME, "Nothing to sort - choose folders and preview first.")
                return
            dest = Path(self.dest_var.get())
            mode = self.mode_var.get()
            verb = "MOVE" if mode == "move" else "COPY"
            if not messagebox.askyesno(
                APP_NAME,
                f"{verb} {len(self.plan)} file(s) into\n{dest}\n\nContinue?",
            ):
                return
            self.run_btn.state(["disabled"])
            threading.Thread(target=self._sort_worker, args=(list(self.plan), dest, mode),
                             daemon=True).start()

        def _sort_worker(self, plan: list[PlanItem], dest: Path, mode: str) -> None:
            def progress(idx: int, total: int, item: PlanItem) -> None:
                self.after(0, self._on_progress, idx, total, item)

            done, skipped, errors = execute_plan(plan, progress)
            try:
                report = write_report(plan, dest)
            except Exception:  # noqa: BLE001
                report = None
            self.after(0, self._on_done, done, skipped, errors, report, dest)

        def _on_progress(self, idx: int, total: int, item: PlanItem) -> None:
            self.progress["maximum"] = total
            self.progress["value"] = idx
            self.status_var.set(f"Working: {item.info.source.name} ({idx}/{total})")

        def _on_done(self, done: int, skipped: int, errors: list[str],
                     report: Path | None, dest: Path) -> None:
            self.run_btn.state(["!disabled"])
            msg = f"Sorted {done} file(s)."
            if skipped:
                msg += f" Skipped {skipped}."
            if errors:
                msg += f" {len(errors)} error(s)."
            self.status_var.set(msg + (f" Report: {report.name}" if report else ""))
            if errors:
                messagebox.showwarning(
                    APP_NAME,
                    msg + "\n\n" + "\n".join(errors[:15]) +
                    ("\n…" if len(errors) > 15 else ""),
                )
            else:
                messagebox.showinfo(APP_NAME, msg + f"\n\nLibrary: {dest}")
            self.rebuild_plan()

    class _EditDialog(tk.Toplevel):
        def __init__(self, master: tk.Misc, item: PlanItem) -> None:
            super().__init__(master)
            self.title("Edit comic details")
            self.resizable(False, False)
            self.result = None
            i = item.info
            ttk.Label(self, text=item.info.source.name, wraplength=460).grid(
                row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 6))
            self.vars = {}
            for r, (key, label, value) in enumerate((
                ("series", "Series name", i.series),
                ("volume", "Volume", i.volume),
                ("issue", "Issue #", i.issue),
                ("edition", "Edition", i.edition),
                ("subtitle", "Subtitle", i.subtitle),
                ("arc", "Arc (optional)", i.arc),
                ("year", "Date (e.g. 2026-01)", i.year),
            ), start=1):
                ttk.Label(self, text=label + ":").grid(row=r, column=0, sticky="e", padx=8, pady=4)
                var = tk.StringVar(value=value)
                ttk.Entry(self, textvariable=var, width=48).grid(
                    row=r, column=1, sticky="ew", padx=8, pady=4)
                self.vars[key] = var
            btns = ttk.Frame(self)
            btns.grid(row=8, column=0, columnspan=2, pady=10)
            ttk.Button(btns, text="Save", command=self._save).pack(side="left", padx=6)
            ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="left", padx=6)
            self.transient(master)
            self.grab_set()

        def _save(self) -> None:
            vals = [self.vars[k].get().strip()
                    for k in ("series", "volume", "issue", "edition", "subtitle", "arc",
                              "year")]
            if not vals[0]:
                messagebox.showwarning(APP_NAME, "A series name is required.", parent=self)
                return
            # an empty volume is fine: no Volume folder is made
            if vals[1]:
                vals[1] = _norm_volume(vals[1])
            if vals[2]:
                vals[2] = _norm_number(vals[2])
            if vals[3]:
                m = re.fullmatch(r"(\d{1,3})", vals[3])
                vals[3] = m.group(1).zfill(3) if m else vals[3]
            # an empty subtitle is fine: no subtitle folder is made
            vals[5] = vals[5].strip(" -–—")
            self.result = tuple(vals)
            self.destroy()

    app = ComicSorterApp()
    app.mainloop()
    return 0


def _is_relative(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def main() -> int:
    try:
        if len(sys.argv) > 1:
            return run_cli(sys.argv[1:])
        return launch_gui()
    except Exception:  # noqa: BLE001
        detail = traceback.format_exc()
        try:
            from tkinter import messagebox
            messagebox.showerror(APP_NAME, f"Unexpected error:\n\n{detail}")
        except Exception:  # noqa: BLE001
            print(detail, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
