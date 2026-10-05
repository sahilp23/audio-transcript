"""Turn timed words into the document the player shows: speakers, turns,
paragraphs, chapters and key-number highlights.

doc.json:
  {
    "source": "asr" | "official",
    "speakers": {key: {"name", "role", "group", "firm"}},
    "speakers_separated": bool,
    "turns": [{"sp": key, "label"?: str, "firm"?: str, "qa": bool, "s", "e",
               "paras": [{"s", "e", "w": [[text, start, end], ...]}]}],
    "chapters": [{"title", "t", "kind", "turn"}],
    "highlights": [{"t", "text", "kind", "turn"}],
    "alignment": float | None,
    "duration": float
  }
"""

import re
from collections import Counter
from typing import Optional

from .align import align, tokenize
from .transcript_parser import normalize_name

SENT_END = re.compile(r"[.?!][\"')\]]*$")

QA_START = re.compile(
    r"(begin|start|open|commence)\w*\s+(with\s+)?(the\s+)?(question|q\s*&\s*a)|"
    r"question[- ]and[- ]answer session|first question (is )?(from|comes)"
)
QUESTION_CUE = re.compile(
    r"(first|next|last|following|final)\s+question\s+(is\s+|will\s+be\s+|comes\s+)?(from|of)\s+(the\s+line\s+of\s+)?"
    r"|question\s+is\s+from\s+(the\s+line\s+of\s+)?"
    r"|(follow[- ]up|follow up)\s+question\s+(is\s+)?from\s+(the\s+line\s+of\s+)?"
    r"|we\s+have\s+(a\s+)?(follow[- ]up\s+)?question\s+from\s+(the\s+line\s+of\s+)?"
)
HANDOVER = re.compile(r"(hand|handing|pass|passing|turn|turning)\s+(the\s+)?(call|conference|floor|line|it)?\s*(over\s+)?to\b")
CLOSING = re.compile(r"closing\s+(comments|remarks|statement)|concluding\s+(comments|remarks)")
MODERATOR_PHRASES = re.compile(
    r"ladies and gentlemen|please go ahead|next question|press\s+\*|star and one|"
    r"rejoin the queue|line is in listen|listen[- ]only mode|conference call"
)

GUIDANCE = re.compile(
    r"\b(guid\w*|outlook|expect\w*|target\w*|aim\w*|going forward|next year|next quarter|"
    r"visibility|pipeline|order ?book|capex|capacity|fy ?'?2\d|h[12] ?fy|full[- ]year|run[- ]rate|"
    r"sustain\w*|anticipat\w*|plan\w*|should be|will be)\b",
    re.I,
)
METRIC = re.compile(
    r"(\d[\d,.]*\s*(%|percent|per cent|crores?|cr\b|lakhs?|bps|basis points|million|billion|mn\b|bn\b|x\b|times))|"
    r"(₹|rs\.?|inr|\$|usd|eur)\s?\d",
    re.I,
)

PARA_TARGET = 70
PARA_MAX = 160


def _text(words: list) -> str:
    return " ".join(w[0] for w in words)


def _split_paragraphs(words: list) -> list[dict]:
    paras, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        end_sent = bool(SENT_END.search(w[0]))
        pause = (nxt[1] - w[2]) if nxt else 0
        if nxt is None or len(cur) >= PARA_MAX or (end_sent and (len(cur) >= PARA_TARGET or (pause > 1.5 and len(cur) >= 25))):
            paras.append({"s": cur[0][1], "e": cur[-1][2], "w": cur})
            cur = []
    return paras


def _make_turn(sp: str, words: list) -> dict:
    return {"sp": sp, "qa": False, "s": words[0][1], "e": words[-1][2], "paras": _split_paragraphs(words)}


def _word_index(turns: list[dict]) -> list[tuple[int, list]]:
    """Flat list of (turn index, word) for phrase searches."""
    return [(ti, w) for ti, t in enumerate(turns) for p in t["paras"] for w in p["w"]]


def _parse_intro(words_after: list) -> tuple[str, str]:
    """'Rahul Jain from ABC Securities. Please go ahead.' -> ('Rahul Jain', 'ABC Securities')"""
    text = _text(words_after[:16])
    text = re.split(r"(?i)[.?!]|\bplease\b|\bgo ahead\b|\byour line\b", text)[0]
    text = re.sub(r"(?i)^(the line of|mr\.?|ms\.?|mrs\.?|dr\.?)\s+", "", text.strip())
    text = re.sub(r"(?i)^(mr\.?|ms\.?|mrs\.?|dr\.?)\s+", "", text.strip())
    parts = re.split(r"(?i)\s+(?:from|of|with)\s+", text, maxsplit=1)
    name = parts[0].strip(" ,")
    firm = parts[1].strip(" ,") if len(parts) > 1 else ""
    if len(name.split()) > 5:
        name = ""
    return name, firm


def _detect_structure(turns: list[dict], speakers: dict, moderator: Optional[str]) -> tuple[list, list]:
    """Find chapters (intro, remarks, Q&A, each question, closing) and analyst intros."""
    flat = _word_index(turns)
    norm = [re.sub(r"[^\w*&' -]", "", w[0].lower()) for _, w in flat]
    # Character offsets so regexes can run over the whole call at once.
    offsets, pos = [], 0
    for tok in norm:
        offsets.append(pos)
        pos += len(tok) + 1
    full = " ".join(norm)

    def word_at(char_pos: int) -> int:
        lo, hi = 0, len(offsets) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if offsets[mid] <= char_pos:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def para_start_for(wi: int, after: bool = False) -> tuple[float, int]:
        """Time + turn of the paragraph holding word wi (or the next paragraph if after)."""
        ti, w = flat[wi]
        t = turns[ti]
        for pi, p in enumerate(t["paras"]):
            if p["s"] <= w[1] <= p["e"] + 0.01:
                if after:
                    if pi + 1 < len(t["paras"]):
                        return t["paras"][pi + 1]["s"], ti
                    if ti + 1 < len(turns):
                        return turns[ti + 1]["s"], ti + 1
                return p["s"], ti
        return t["s"], ti

    chapters = [{"title": "Introduction", "t": turns[0]["s"] if turns else 0, "kind": "intro", "turn": 0}]
    duration = turns[-1]["e"] if turns else 0

    qa_m = QA_START.search(full)
    qa_word = word_at(qa_m.start()) if qa_m else None

    # Management remarks start: first non-moderator turn, or the paragraph after a hand-over.
    remarks = None
    if moderator and len(speakers) > 1:
        for ti, t in enumerate(turns):
            if t["sp"] != moderator and (qa_word is None or t["s"] < flat[qa_word][1][1]):
                remarks = (t["s"], ti)
                break
    else:
        m = HANDOVER.search(full)
        if m and (qa_m is None or m.start() < qa_m.start()):
            remarks = para_start_for(word_at(m.start()), after=True)
    if remarks and remarks[0] > chapters[0]["t"]:
        chapters.append({"title": "Management remarks", "t": remarks[0], "kind": "remarks", "turn": remarks[1]})

    qa_time = None
    if qa_m:
        qa_time, qa_turn = para_start_for(qa_word)
        chapters.append({"title": "Q&A", "t": qa_time, "kind": "qa", "turn": qa_turn})

    analysts = []
    for m in QUESTION_CUE.finditer(full):
        wi = word_at(m.end() - 1) + 1
        if wi >= len(flat):
            continue
        name, firm = _parse_intro([w for _, w in flat[wi:wi + 20]])
        if not name:
            continue
        cue_t = flat[wi][1][1]
        cue_turn = flat[wi][0]
        # The analyst speaks in the next turn by someone other than the moderator.
        target = None
        if moderator and len(speakers) > 1:
            for ti in range(cue_turn + 1, min(cue_turn + 4, len(turns))):
                if turns[ti]["sp"] != moderator:
                    target = ti
                    break
        if target is not None:
            start_t = turns[target]["s"]
        else:
            # No speaker turns: start after the moderator's "... Please go ahead."
            start_t = cue_t
            for k in range(wi, min(wi + 40, len(flat) - 1)):
                if SENT_END.search(flat[k][1][0]) and ("ahead" in flat[k][1][0].lower() or k - wi > 25):
                    start_t = flat[k + 1][1][1]
                    break
        title = name + (f" · {firm}" if firm else "")
        chapters.append({"title": title, "t": start_t, "kind": "question", "turn": target if target is not None else cue_turn, "cue_t": cue_t})
        analysts.append({"name": name, "firm": firm, "turn": target, "t": start_t})

    close_m = None
    for m in CLOSING.finditer(full):
        close_m = m
    if close_m and (qa_m is None or close_m.start() > qa_m.start()):
        t, ti = para_start_for(word_at(close_m.start()), after=True)
        chapters.append({"title": "Closing remarks", "t": t, "kind": "closing", "turn": ti})

    chapters = [c for c in chapters if c["t"] <= duration + 1]
    chapters.sort(key=lambda c: c["t"])
    # Drop near-duplicate chapter starts (same second), keeping the more specific.
    deduped = []
    for c in chapters:
        if deduped and abs(deduped[-1]["t"] - c["t"]) < 0.5 and c["kind"] != "question":
            continue
        deduped.append(c)

    for t in turns:
        t["qa"] = qa_time is not None and t["s"] >= qa_time - 0.01
    return deduped, analysts


def _highlights(turns: list[dict], speakers: dict) -> list[dict]:
    out = []
    for ti, t in enumerate(turns):
        if speakers.get(t["sp"], {}).get("group") == "moderator":
            continue
        sent: list = []
        for p in t["paras"]:
            for w in p["w"]:
                sent.append(w)
                if SENT_END.search(w[0]) or len(sent) > 60:
                    text = _text(sent)
                    has_num = METRIC.search(text)
                    has_guide = GUIDANCE.search(text)
                    if has_num and len(sent) >= 6:
                        out.append({
                            "t": sent[0][1],
                            "text": text,
                            "kind": "guidance" if has_guide else "number",
                            "turn": ti,
                        })
                    sent = []
    return out


def _assign_speakers(words: list[dict], segs: list[dict]) -> list[str]:
    """Speaker label per word: diarization segment with most overlap (nearest if none)."""
    labels = []
    j = 0
    for w in words:
        while j < len(segs) and segs[j]["e"] < w["s"] - 5:
            j += 1
        best, best_ov, best_dist = None, 0.0, 1e9
        for k in range(j, len(segs)):
            sg = segs[k]
            if sg["s"] > w["e"] + 5:
                break
            ov = min(w["e"], sg["e"]) - max(w["s"], sg["s"])
            dist = 0 if ov > 0 else min(abs(w["s"] - sg["e"]), abs(sg["s"] - w["e"]))
            if ov > best_ov or (best_ov <= 0 and dist < best_dist):
                best, best_ov, best_dist = sg["spk"], max(ov, best_ov), dist
        labels.append(best or (labels[-1] if labels else "SPEAKER_00"))
    # Smooth out tiny flips (< 3 words) between the same speaker.
    i = 0
    while i < len(labels):
        j = i
        while j < len(labels) and labels[j] == labels[i]:
            j += 1
        if 0 < i and j < len(labels) and j - i < 3 and labels[i - 1] == labels[j]:
            for k in range(i, j):
                labels[k] = labels[i - 1]
        i = j
    return labels


def build_from_asr(asr: dict, diar: Optional[list[dict]], duration: float) -> dict:
    words = asr["words"]
    if not words:
        return {"source": "asr", "speakers": {}, "speakers_separated": False, "turns": [], "chapters": [],
                "highlights": [], "alignment": None, "duration": duration}
    tw = [[w["w"], w["s"], w["e"]] for w in words]

    if diar:
        labels = _assign_speakers(words, diar)
        turns, cur, cur_sp = [], [], None
        for lbl, w in zip(labels, tw):
            if lbl != cur_sp and cur:
                turns.append(_make_turn(cur_sp, cur))
                cur = []
            cur_sp = lbl
            cur.append(w)
        if cur:
            turns.append(_make_turn(cur_sp, cur))
        order = list(dict.fromkeys(t["sp"] for t in turns))
        speakers = {k: {"name": f"Speaker {i + 1}", "role": "", "group": "unknown"} for i, k in enumerate(order)}
        # Moderator: the speaker who uses operator phrases most.
        score = Counter()
        for t in turns:
            score[t["sp"]] += len(MODERATOR_PHRASES.findall(" ".join(_text(p["w"]).lower() for p in t["paras"])))
        moderator = score.most_common(1)[0][0] if score and score.most_common(1)[0][1] >= 2 else None
        if moderator:
            speakers[moderator].update(name="Moderator", group="moderator")
        for i, k in enumerate(k for k in order if k != moderator):
            speakers[k]["name"] = f"Speaker {i + 1}"
    else:
        speakers = {"SPEAKER": {"name": "Speaker", "role": "", "group": "unknown"}}
        moderator = None
        turns = [_make_turn("SPEAKER", tw)]

    chapters, analysts = _detect_structure(turns, speakers, moderator)
    for a in analysts:
        if a["turn"] is not None:
            turns[a["turn"]]["label"] = a["name"]
            turns[a["turn"]]["firm"] = a["firm"]
            # An analyst's follow-up turns before the moderator speaks again.
            sp = turns[a["turn"]]["sp"]
            for ti in range(a["turn"] + 1, len(turns)):
                if turns[ti]["sp"] == moderator:
                    break
                if turns[ti]["sp"] == sp:
                    turns[ti]["label"] = a["name"]
                    turns[ti]["firm"] = a["firm"]
            if speakers[sp]["group"] == "unknown" and all(
                t.get("label") for t in turns if t["sp"] == sp
            ):
                speakers[sp]["group"] = "analyst"
    for k, s in speakers.items():
        if s["group"] == "unknown" and diar:
            s["group"] = "management"

    return {
        "source": "asr",
        "speakers": speakers,
        "speakers_separated": bool(diar),
        "turns": turns,
        "chapters": chapters,
        "highlights": _highlights(turns, speakers),
        "alignment": None,
        "duration": duration,
    }


def build_from_official(official: dict, asr: dict, duration: float) -> dict:
    turns_src = official["turns"]
    participants = official.get("participants", {})
    tokens, owner = [], []
    for ti, t in enumerate(turns_src):
        toks = tokenize(t["text"])
        tokens.extend(toks)
        owner.extend([ti] * len(toks))

    times, matched = align(tokens, asr["words"]) if asr.get("words") else ([(0.0, 0.0)] * len(tokens), 0.0)

    per_turn: list[list] = [[] for _ in turns_src]
    for tok, ti, (s, e) in zip(tokens, owner, times):
        per_turn[ti].append([tok, s, e])

    speakers: dict = {}
    turns = []
    for t, words in zip(turns_src, per_turn):
        if not words:
            continue
        key = normalize_name(t["speaker"]) or "unknown"
        if key not in speakers:
            info = participants.get(key, {})
            group = info.get("group")
            if key in ("moderator", "operator"):
                group = "moderator"
            speakers[key] = {"name": t["speaker"], "role": info.get("role", ""), "group": group or "unknown", "firm": ""}
        turns.append(_make_turn(key, words))

    moderator = next((k for k, s in speakers.items() if s["group"] == "moderator"), None)
    chapters, analysts = _detect_structure(turns, speakers, moderator)

    # Classify speakers: anyone introduced by the moderator as asking a question is an analyst.
    for a in analysts:
        if a["turn"] is not None:
            sp = turns[a["turn"]]["sp"]
            if speakers[sp]["group"] == "unknown":
                speakers[sp]["group"] = "analyst"
                speakers[sp]["firm"] = a["firm"]
    qa_t = next((c["t"] for c in chapters if c["kind"] == "qa"), None)
    for k, s in speakers.items():
        if s["group"] == "unknown":
            spoke_before_qa = any(t["sp"] == k and (qa_t is None or t["s"] < qa_t) for t in turns)
            s["group"] = "management" if spoke_before_qa else "analyst"

    return {
        "source": "official",
        "speakers": speakers,
        "speakers_separated": True,
        "turns": turns,
        "chapters": chapters,
        "highlights": _highlights(turns, speakers),
        "alignment": matched,
        "duration": duration,
    }
