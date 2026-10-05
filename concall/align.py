"""Put audio timings on the official (edited) transcript.

The company transcript is cleaned up (fillers removed, grammar fixed), so it never
matches the audio word-for-word. We line up its words against the speech-to-text
words, which carry timings, using sequence matching:

  * words found in both get the speech-to-text timing directly (anchors)
  * words only in the official text are spread across the time between the
    surrounding anchors, proportionally to their length
"""

import re
from difflib import SequenceMatcher

_NUM_SEP = re.compile(r"(?<=\d),(?=\d)")


def norm_token(token: str) -> str:
    t = _NUM_SEP.sub("", token.lower())
    t = t.replace("’", "'")
    t = re.sub(r"[^\w.']", "", t)
    t = t.strip(".'_")
    return t


def tokenize(text: str) -> list[str]:
    return [t for t in text.split() if t.strip()]


def _match(a: list[str], b: list[str], a0: int, a1: int, b0: int, b1: int, out: dict, depth: int) -> None:
    n, m = a1 - a0, b1 - b0
    if n <= 0 or m <= 0 or depth > 4:
        return
    big = n > 3000 or m > 3000
    sm = SequenceMatcher(None, a[a0:a1], b[b0:b1], autojunk=big)
    # In wide gaps a lone common word ("the") is usually a false match.
    min_block = 1 if (n < 40 and m < 40) else 2
    pa, pb = a0, b0
    for blk in sm.get_matching_blocks():
        ia, ib, size = a0 + blk.a, b0 + blk.b, blk.size
        if size and size < min_block:
            continue
        if ia > pa and ib > pb:
            _match(a, b, pa, ia, pb, ib, out, depth + 1)
        for k in range(size):
            out[ia + k] = ib + k
        pa, pb = ia + size, ib + size  # the final dummy block (size 0) sits at (a1, b1)


def align(official_tokens: list[str], asr_words: list[dict]) -> tuple[list[tuple[float, float]], float]:
    """Returns one (start, end) per official token, plus the fraction of tokens anchored."""
    a = [norm_token(t) for t in official_tokens]
    b = [norm_token(w["w"]) for w in asr_words]
    if not a:
        return [], 0.0
    if not b:
        return [(0.0, 0.0)] * len(a), 0.0

    mapping: dict[int, int] = {}
    _match(a, b, 0, len(a), 0, len(b), mapping, 0)
    # Empty tokens (pure punctuation) shouldn't count as matches.
    mapping = {i: j for i, j in mapping.items() if a[i]}

    times: list[tuple[float, float] | None] = [None] * len(a)
    for i, j in mapping.items():
        times[i] = (asr_words[j]["s"], asr_words[j]["e"])

    anchors = sorted(mapping.items())
    first_t = asr_words[0]["s"]
    last_t = asr_words[-1]["e"]

    def fill(lo: int, hi: int, t0: float, t1: float) -> None:
        """Spread official tokens lo..hi-1 across [t0, t1] by character length."""
        if hi <= lo:
            return
        t1 = max(t1, t0)
        weights = [max(1, len(official_tokens[k])) for k in range(lo, hi)]
        total = sum(weights)
        t = t0
        for k, wgt in zip(range(lo, hi), weights):
            dur = (t1 - t0) * wgt / total
            times[k] = (round(t, 3), round(t + dur, 3))
            t += dur

    if not anchors:
        fill(0, len(a), first_t, last_t)
        return times, 0.0  # type: ignore[return-value]

    # Leading tokens: before the first anchor, use the speech that came before it.
    i0, j0 = anchors[0]
    fill(0, i0, asr_words[0]["s"] if j0 > 0 else max(0.0, asr_words[j0]["s"] - 0.3 * i0), asr_words[j0]["s"])
    for (ia, ja), (ib, jb) in zip(anchors, anchors[1:]):
        if ib > ia + 1:
            fill(ia + 1, ib, asr_words[ja]["e"], asr_words[jb]["s"])
    il, jl = anchors[-1]
    tail_end = last_t if jl < len(asr_words) - 1 else asr_words[jl]["e"] + 0.3 * (len(a) - il - 1)
    fill(il + 1, len(a), asr_words[jl]["e"], tail_end)

    matched = sum(1 for i in mapping) / max(1, sum(1 for t in a if t))
    return times, round(matched, 3)  # type: ignore[return-value]
