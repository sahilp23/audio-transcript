"""Parse a company-published concall transcript (PDF or text) into speaker turns.

Indian concall transcripts (BSE/NSE filings) mostly look like:

    MANAGEMENT: MR. SUMER GHUMMAN - WHOLE TIME DIRECTOR - SHIVALIK BIMETAL ...
    MODERATOR:  MR. X - Y SECURITIES

    Moderator:      Ladies and gentlemen, good day and welcome ...
    Sumer Ghumman:  Thank you. Good afternoon everyone ...

They are edited for readability, so they are *not* word-for-word with the audio;
the aligner handles that.
"""

import re
from collections import Counter
from pathlib import Path

TITLES = re.compile(r"^(mr|mrs|ms|miss|dr|shri|smt|prof|ca|cs)\.?\s+", re.I)
PAGE_NO = re.compile(r"^\s*(page\s*\d+(\s*of\s*\d+)?|\d+\s*(of|/)\s*\d+|-?\s*\d+\s*-?)\s*$", re.I)
# "Name:" at the start of a line, name being 1-6 words.
LABEL = re.compile(r"^\s*((?:[A-Z][\w.'’-]*\.?\s?){1,6}?)\s*[:：]\s*(.*)$")
NOT_SPEAKERS = {
    "note", "disclaimer", "management", "moderator s", "participants", "analyst", "analysts",
    "date", "time", "venue", "subject", "ref", "dear sir", "dear sirs", "dear sir madam",
    "website", "email", "e mail", "tel", "phone", "fax", "cin", "scrip code", "symbol", "isin",
    "registered office", "corporate office", "speakers", "company", "host", "hosted by",
    "q", "a", "total", "source", "for", "to", "re", "regd office", "encl", "yours faithfully",
}
GROUP_HEADINGS = {
    "management": "management",
    "management team": "management",
    "company participants": "management",
    "moderator": "moderator",
    "moderators": "moderator",
    "analysts": "analyst",
    "participants": "analyst",
}


def normalize_name(name: str) -> str:
    name = TITLES.sub("", name.strip())
    name = re.sub(r"[^a-z\s]", " ", name.lower())
    return re.sub(r"\s+", " ", name).strip()


def display_name(name: str) -> str:
    name = TITLES.sub("", name.strip()).strip(" .")
    if name.isupper():
        name = " ".join(p.capitalize() for p in name.split())
    return re.sub(r"\s+", " ", name)


def read_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return "\n\f\n".join((p.extract_text() or "") for p in reader.pages)
    return path.read_text(encoding="utf-8", errors="replace")


def _strip_headers_footers(text: str) -> list[str]:
    pages = text.split("\f")
    lines = [ln.rstrip() for ln in text.replace("\f", "\n").splitlines()]
    if len(pages) >= 3:
        # Lines repeated on many pages are headers/footers.
        counts = Counter(ln.strip() for p in pages for ln in set(p.splitlines()) if ln.strip())
        repeated = {ln for ln, c in counts.items() if c >= max(3, len(pages) // 2) and len(ln) < 120}
    else:
        repeated = set()
    return [ln for ln in lines if ln.strip() not in repeated and not PAGE_NO.match(ln)]


def _parse_participants(front: list[str]) -> dict:
    """MANAGEMENT: MR. A - CFO - COMPANY / MODERATOR: MR. B - FIRM"""
    people = {}
    group = None
    for raw in front:
        line = raw.strip()
        head = re.match(r"^([A-Za-z ]{3,30})\s*[:：]\s*(.*)$", line)
        if head and head.group(1).strip().lower() in GROUP_HEADINGS:
            group = GROUP_HEADINGS[head.group(1).strip().lower()]
            line = head.group(2)
        m = re.match(r"^(?:mr|mrs|ms|dr|shri|smt)\.?\s+([A-Za-z .'-]+?)\s*[–—,-]\s*(.+)$", line, re.I)
        if m:
            name = display_name(m.group(1))
            role = re.split(r"\s*[–—]\s*|\s+-\s+", m.group(2).strip())[0].strip(" ,-")
            people[normalize_name(name)] = {
                "name": name,
                "role": role.title() if role.isupper() else role,
                "group": group or "management",
            }
    return people


PERSON_LIST = re.compile(r"^(mr|mrs|ms|dr|shri|smt)\.?\s", re.I)
SPECIAL = ("moderator", "operator", "management", "participant", "unidentified participant")


def _is_label(name: str, known: set[str], counts: Counter | None = None) -> bool:
    norm = normalize_name(name)
    if not norm or norm in NOT_SPEAKERS:
        return False
    if norm in known or norm in SPECIAL:
        return True
    words = norm.split()
    if not 1 <= len(words) <= 5:
        return False
    # Proper names: each word capitalised in the source.
    if not all(w[:1].isupper() for w in TITLES.sub("", name.strip()).split()):
        return False
    # A single capitalised word ("Revenue:") only counts if it labels several turns.
    return len(words) >= 2 or (counts is not None and counts[norm] >= 2)


def parse_text(text: str) -> dict:
    lines = _strip_headers_footers(text)

    first_label = None
    for i, ln in enumerate(lines):
        m = LABEL.match(ln)
        # "MODERATOR: MR. X - FIRM" in the participants list is not the start of the call.
        if m and normalize_name(m.group(1)) in ("moderator", "operator") and not PERSON_LIST.match(m.group(2)):
            first_label = i
            break
    if first_label is None:
        first_label = next(
            (i for i, ln in enumerate(lines) if (m := LABEL.match(ln)) and _is_label(m.group(1), set()) and len(m.group(2)) > 20),
            0,
        )

    participants = _parse_participants(lines[:first_label])
    known = set(participants)
    # The document title (company name etc.) often repeats as a page header.
    title_lines = {ln.strip() for ln in lines[:first_label] if ln.strip()}
    title_lines |= {ln.strip(' "') for ln in title_lines}
    body = [ln for ln in lines[first_label:] if ln.strip() not in title_lines]
    counts = Counter(normalize_name(m.group(1)) for ln in body if (m := LABEL.match(ln)))

    turns: list[dict] = []
    for ln in body:
        m = LABEL.match(ln)
        if m and _is_label(m.group(1), known, counts):
            name = display_name(m.group(1))
            turns.append({"speaker": name, "text": m.group(2).strip()})
        elif turns:
            if ln.strip():
                turns[-1]["text"] += " " + ln.strip()
        elif ln.strip():
            turns.append({"speaker": "Moderator", "text": ln.strip()})

    for t in turns:
        t["text"] = re.sub(r"\s+", " ", t["text"]).strip()
    turns = [t for t in turns if t["text"]]
    if len({normalize_name(t["speaker"]) for t in turns}) < 2:
        return {"turns": [], "participants": participants}  # not a speaker-labelled transcript

    # Merge consecutive turns by the same speaker (page breaks repeat labels sometimes).
    merged: list[dict] = []
    for t in turns:
        if merged and normalize_name(merged[-1]["speaker"]) == normalize_name(t["speaker"]):
            merged[-1]["text"] += " " + t["text"]
        else:
            merged.append(t)

    return {"turns": merged, "participants": participants}


def parse_file(path: Path) -> dict:
    return parse_text(read_text(path))
