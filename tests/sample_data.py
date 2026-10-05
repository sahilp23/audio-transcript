"""A small synthetic concall used by tests and the demo: an 'official' edited
transcript plus a 'spoken' version (fillers, contractions, small differences)
with word timings, like Whisper would produce."""

import random

OFFICIAL = """\
"Demo Controls Limited
Q1 FY27 Earnings Conference Call"
August 07, 2026

MANAGEMENT: MR. ARJUN MEHTA - MANAGING DIRECTOR - DEMO CONTROLS LIMITED
MS. PRIYA NAIR - CHIEF FINANCIAL OFFICER - DEMO CONTROLS LIMITED
MODERATOR: MR. KUNAL SHAH - ABC SECURITIES

Moderator: Ladies and gentlemen, good day and welcome to the Q1 FY27 Earnings Conference Call of Demo Controls Limited. As a reminder, all participant lines will be in the listen-only mode. I now hand the conference over to Mr. Arjun Mehta, Managing Director. Thank you and over to you, sir.
Arjun Mehta: Thank you. Good afternoon everyone. Revenue grew 18.7% year-on-year to INR 182 crores, EBITDA grew 23% to INR 43 crores and PAT grew 44.9% to INR 33 crores. Europe grew strongly, led by shunts, while Asia was weaker during the quarter.
Demo Controls Limited
Page 2 of 4
We expect to sustain mid-teens revenue growth in FY27 with EBITDA margins of around 24%. Capex for the year will be about INR 60 crores, mainly for the new shunt line.
Priya Nair: Thank you, Arjun. Working capital days improved to 92 from 101 last year, and net cash stood at INR 75 crores at the end of the quarter.
Moderator: Thank you. We will now begin the question-and-answer session. The first question is from the line of Rahul Jain from Alpha Capital. Please go ahead.
Rahul Jain: Thanks for the opportunity. What drove the margin improvement this quarter, and is it sustainable?
Arjun Mehta: The improvement came from a richer mix of value-added products and operating leverage. We believe margins of 23% to 25% are sustainable.
Moderator: Thank you. The next question is from the line of Sneha Rao from Beta Advisors. Please go ahead.
Sneha Rao: Hi. Can you talk about the Americas business and the order book?
Priya Nair: Americas grew 30% this quarter after a soft FY26. Our order book is about INR 250 crores, which gives us good visibility for the next two quarters.
Moderator: Thank you. As there are no further questions, I would now like to hand the conference over to the management for closing comments.
Arjun Mehta: Thank you everyone for joining. Please reach out to our investor relations team for any further queries.
Moderator: Thank you. On behalf of Demo Controls Limited, that concludes this conference. You may now disconnect your lines.
"""

# What was actually said (differs a little from the edited transcript).
SPOKEN = [
    ("SPEAKER_00", "Ladies and gentlemen, good day and welcome to the Q1 FY27 earnings conference call of Demo Controls Limited. As a reminder, all participant lines will be in the listen-only mode. I now hand the conference over to Mr. Arjun Mehta, Managing Director. Thank you and over to you, sir."),
    ("SPEAKER_01", "Yeah, thank you. Good afternoon, everyone. So, revenue grew 18.7% year-on-year to INR 182 crores, EBITDA grew 23% to INR 43 crores, and PAT grew 44.9% to INR 33 crores. Europe grew, uh, strongly, led by shunts, while Asia was weaker during the quarter. We expect to sustain mid-teens revenue growth in FY27 with EBITDA margins of around 24%. Capex for the year will be about INR 60 crores, mainly for the new shunt line."),
    ("SPEAKER_02", "Thank you, Arjun. Working capital days improved to 92 from 101 last year, and net cash stood at INR 75 crores at the end of the quarter."),
    ("SPEAKER_00", "Thank you. We will now begin the question-and-answer session. The first question is from the line of Rahul Jain from Alpha Capital. Please go ahead."),
    ("SPEAKER_03", "Hi, thanks for the opportunity. Um, what drove the margin improvement this quarter, and is it sustainable?"),
    ("SPEAKER_01", "So the improvement came from a richer mix of value-added products and, you know, operating leverage. We believe margins of 23% to 25% are sustainable."),
    ("SPEAKER_00", "Thank you. The next question is from the line of Sneha Rao from Beta Advisors. Please go ahead."),
    ("SPEAKER_04", "Hi. Can you talk about the Americas business and the order book?"),
    ("SPEAKER_02", "Sure. Americas grew 30% this quarter after a soft FY26. Our order book is about INR 250 crores, which gives us good visibility for the next two quarters."),
    ("SPEAKER_00", "Thank you. As there are no further questions, I would now like to hand the conference over to the management for closing comments."),
    ("SPEAKER_01", "Thank you everyone for joining. Please reach out to our investor relations team for any further queries."),
    ("SPEAKER_00", "Thank you. On behalf of Demo Controls Limited, that concludes this conference. You may now disconnect your lines."),
]


def make_asr(seed: int = 7) -> tuple[dict, list[dict], float]:
    """Returns (asr.json, diar.json, duration) with plausible word timings."""
    rnd = random.Random(seed)
    t = 1.0
    words, diar = [], []
    for spk, text in SPOKEN:
        start = t
        for tok in text.split():
            dur = 0.12 + 0.045 * len(tok) + rnd.uniform(0, 0.05)
            words.append({"w": tok, "s": round(t, 3), "e": round(t + dur, 3), "p": 0.95})
            t += dur + rnd.uniform(0.03, 0.12)
            if tok.endswith((".", "?")):
                t += rnd.uniform(0.2, 0.5)
        diar.append({"s": round(start - 0.05, 3), "e": round(t, 3), "spk": spk})
        t += 1.2
    return {"engine": "test", "model": "test", "words": words}, diar, round(t + 1, 3)
