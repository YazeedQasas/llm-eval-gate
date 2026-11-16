"""A SIMULATED model for the demo. It is not an LLM and makes no network calls.

It writes plausible judgment texts with a fixed, deterministic accuracy profile per
prompt style, so the demo can be re-recorded by anyone without API keys. To get the
"truth" it reads cases.jsonl next to this file, which a real model obviously cannot do.

Profiles (by the `style:` line in the prompt):
  terse   (prompts/judgment.txt)           ~80% of clean cases right, always ends
                                           with a proper operative line
  fluent  (prompts/candidates/v2-fluent)   longer, nicer prose; ~64% right, and on
                                           some cases drops the operative line entirely
Leaked cases (self-retrieval, answer-bearing) are always right under both styles:
the answer is in the context, so the "model" copies it. That is the leak.

Swap this for a real provider by pointing `[system] live` at your own factory:
    def make_generate(prompt_text): return lambda case, params: call_your_model(...)
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

VERDICTS = ["accepted", "rejected", "partial", "dismissed"]
LEAKS = {"self_retrieval", "answer_bearing"}

EN_OPERATIVE = {
    "accepted": "The court rules: the claim is accepted and the defendant is ordered to perform.",
    "partial": "The court rules: the claim is partially accepted and the remaining requests "
    "are rejected.",
    "rejected": "The court rules: the claim is rejected and the claimant bears the costs.",
    "dismissed": "The court rules: the claim is inadmissible for lack of prior notice.",
}
AR_OPERATIVE = {
    "accepted": "حكمت المحكمة بقبول الدعوى وإلزام المدعى عليه بالتنفيذ.",
    "partial": "حكمت المحكمة بقبول الدعوى جزئياً ورد ما زاد على ذلك.",
    "rejected": "حكمت المحكمة برد الدعوى وتضمين المدعي الرسوم.",
    "dismissed": "حكمت المحكمة بعدم قبول الدعوى لعدم توجيه الإنذار المسبق.",
}
# What a fluent answer says when it drifts off the operative format.
EN_DRIFT = {
    "accepted": "In light of all of the foregoing, the claimant's position is the more "
    "convincing one and should prevail.",
    "partial": "In light of the foregoing, the claimant deserves relief, though not to the "
    "full extent sought.",
    "rejected": "In light of the foregoing, the claimant has not carried the burden that the "
    "law places on them.",
    "dismissed": "In light of the foregoing, the procedural defect is decisive.",
}
AR_DRIFT = {
    "accepted": "وبناءً على ما تقدم، فإن موقف المدعي هو الأرجح ويستحق الإنصاف.",
    "partial": "وبناءً على ما تقدم، يستحق المدعي الإنصاف ولكن ليس بكامل ما طلبه.",
    "rejected": "وبناءً على ما تقدم، لم ينهض المدعي بعبء الإثبات الملقى على عاتقه.",
    "dismissed": "وبناءً على ما تقدم، فإن العيب الإجرائي حاسم في هذه الدعوى.",
}
EN_TRAP = (
    "The objection to jurisdiction is rejected. The request to adjourn is rejected. "
    "The plea of limitation is rejected."
)
AR_TRAP = "وتقرر رفض الدفع بعدم الاختصاص، كما تقرر رفض طلب التأجيل، وتقرر رفض الدفع بالتقادم."


def _truth() -> dict[str, dict]:
    path = Path(__file__).with_name("cases.jsonl")
    with path.open(encoding="utf-8") as fh:
        return {c["id"]: c for c in map(json.loads, filter(str.strip, fh))}


def _u(case_id: str) -> float:
    """A stable number in [0, 1) per case."""
    return int(hashlib.sha256(case_id.encode()).hexdigest()[:8], 16) / 2**32


def _wrong(verdict: str, case_id: str) -> str:
    others = [v for v in VERDICTS if v != verdict]
    return others[int(hashlib.sha256((case_id + "w").encode()).hexdigest(), 16) % 3]


def _style(prompt_text: str) -> str:
    m = re.search(r"^style:\s*(\w+)\s*$", prompt_text, re.MULTILINE)
    if not m or m.group(1) not in {"terse", "fluent"}:
        raise ValueError(
            "the simulated model only knows the demo prompts (a 'style: terse' or "
            "'style: fluent' line). Use a real model factory for other prompts."
        )
    return m.group(1)


def make_generate(prompt_text: str):
    style = _style(prompt_text)
    truth = _truth()

    def generate(case, params) -> str:
        gold = truth[case.id]
        verdict = gold["metadata"]["verdict"]
        trap = gold["metadata"].get("seeded_trap")
        en = case.id.startswith("en-")
        u = _u(case.id)

        if trap in LEAKS:
            predicted, drift = verdict, False
        elif style == "terse":
            predicted, drift = (verdict if u < 0.80 else _wrong(verdict, case.id)), False
        else:
            right = u < 0.58 or 0.80 <= u < 0.86
            predicted = verdict if right else _wrong(verdict, case.id)
            drift = not right and 0.58 <= u < 0.66

        operative = (EN_OPERATIVE if en else AR_OPERATIVE)[predicted]
        if drift:
            operative = (EN_DRIFT if en else AR_DRIFT)[predicted]
        extra = (EN_TRAP if en else AR_TRAP) if trap == "whole_text" else ""

        if style == "terse":
            if en:
                reasoning = "Reasoning: the facts and the cited principles decide the dispute."
            else:
                reasoning = "الأسباب: الوقائع والمبادئ المستشهد بها تحسم النزاع."
            return f"{reasoning} {extra}".strip() + f"\n{operative}"

        if en:
            prose = (
                "Analysis. The claimant asks that the claim be accepted in full, while the "
                "defendant resists every request. Weighing each side's arguments against the "
                "retrieved principles, and mindful of the burden of proof, the court has "
                "considered the record as a whole."
            )
        else:
            prose = (
                "التحليل: يطلب المدعي قبول الدعوى بكامل طلباتها، بينما ينازع المدعى عليه في "
                "كل طلب. وبعد الموازنة بين حجج الطرفين في ضوء المبادئ المستشهد بها، ومراعاة "
                "عبء الإثبات، نظرت المحكمة في الملف برمته."
            )
        return f"{prose} {extra}".strip() + f"\n\n{operative}"

    return generate
