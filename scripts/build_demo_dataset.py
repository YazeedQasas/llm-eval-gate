"""Build the synthetic judgment-prediction demo set.

Deterministic: running it twice writes byte-identical files. Every case is invented.

    python scripts/build_demo_dataset.py            # writes examples/judgments/cases.jsonl

Seeded traps (recorded in metadata.seeded_trap so tests can check the guards):
  self_retrieval  the case's own judgment is in the context (by id, or as a near copy)
  answer_bearing  a context document states the ruling (e.g. a press summary)
  whole_text      the reasoning repeats another verdict's keyword more often than the
                  operative line states the real one
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "examples" / "judgments" / "cases.jsonl"
PER_LANGUAGE = 36
VERDICT_CYCLE = ["accepted", "rejected", "partial", "accepted", "dismissed", "rejected"]
SELF_RETRIEVAL = {3: "id", 11: "id", 19: "id", 27: "copy"}
ANSWER_BEARING = {5, 13, 21, 29}
WHOLE_TEXT = {1, 8, 16, 24, 32, 34}

# --------------------------------------------------------------------------- English

EN_PARTIES = [
    ("Harbor Logistics LLC", "Delta Foods Co."),
    ("Mr. Samir Haddad", "Crescent Realty"),
    ("Northgate Builders", "Ms. Lina Farah"),
    ("Atlas Trading", "Blue Coast Imports"),
    ("Mr. Omar Nasser", "City Transit Company"),
    ("Cedar Clinics", "Orion Medical Supplies"),
]

EN_DOMAINS = {
    "lease": dict(
        subject="rescission of a commercial lease for unpaid rent",
        remedy="vacate the premises and pay the unpaid rent of 14,000",
        partial="pay 9,000 of the unpaid rent",
        defense="the rent was withheld because the landlord failed to carry out repairs",
        principles=[
            "A landlord may seek rescission where the tenant fails to pay rent after formal notice.",
            "A tenant may not withhold rent for repairs without first obtaining a court order.",
        ],
    ),
    "employment": dict(
        subject="an unpaid end-of-service gratuity and notice pay",
        remedy="pay an end-of-service gratuity of 22,500 and one month's notice pay",
        partial="pay the end-of-service gratuity of 22,500",
        defense="the employee resigned without notice and forfeited the gratuity",
        principles=[
            "Gratuity is calculated on the last basic wage for each year of continuous service.",
            "Resignation does not forfeit a gratuity already accrued under the contract.",
        ],
    ),
    "sale": dict(
        subject="a refund for defective industrial refrigerators",
        remedy="take back the goods and refund the price of 48,000",
        partial="refund 30,000 for the units shown to be defective",
        defense="the defects were caused by improper installation by the buyer",
        principles=[
            "A seller warrants hidden defects existing at delivery that make goods unfit for use.",
            "A buyer must notify the seller of a defect within a reasonable time of discovering it.",
        ],
    ),
    "loan": dict(
        subject="repayment of a personal loan",
        remedy="repay the loan of 60,000 with statutory interest",
        partial="repay 35,000 of the loan",
        defense="part of the amount was a gift rather than a loan",
        principles=[
            "A loan above the statutory threshold is proven by writing or a written acknowledgment.",
            "Partial repayments are presumed to reduce the principal unless agreed otherwise.",
        ],
    ),
    "tort": dict(
        subject="damages for injuries suffered in a traffic accident",
        remedy="pay compensation of 75,000 for material and moral damage",
        partial="pay compensation of 40,000 for material damage",
        defense="the claimant contributed to the accident by crossing outside a crossing",
        principles=[
            "The keeper of a vehicle is liable for damage it causes unless a foreign cause is shown.",
            "Compensation is reduced in proportion to the injured party's own fault.",
        ],
    ),
    "construction": dict(
        subject="a contractual penalty for delayed completion of a villa",
        remedy="pay the contractual delay penalty of 90,000",
        partial="pay a reduced delay penalty of 45,000",
        defense="the delay was caused by late approvals from the owner",
        principles=[
            "A contractual penalty may be reduced where it is excessive relative to the actual harm.",
            "A contractor is excused for delay attributable to the employer's own acts.",
        ],
    ),
}

EN_FACTS = {
    "accepted": "The claimant produced the signed contract and proof of the breach, and the "
    "defendant did not contest the documents.",
    "partial": "The breach is proven, but part of the amount claimed is not supported by any "
    "document.",
    "rejected": "The claimant's documents do not prove the breach, and the defendant produced "
    "evidence that it performed its obligations.",
    "dismissed": "The claim was filed without the mandatory prior notice required by law.",
}

EN_REASONING = {
    "accepted": "The documents establish the obligation and the breach. The defence is not "
    "supported by any evidence.",
    "partial": "The obligation is established, but the claimant proved only part of the amount "
    "claimed. The balance is not supported.",
    "rejected": "The burden of proof lies on the claimant, who has not shown the breach. The "
    "defendant's records show performance.",
    "dismissed": "The law requires prior notice before filing. No notice was served, so the "
    "court cannot examine the merits.",
}

EN_TRAP = {
    # reasoning that repeats other verdict keywords more often than the operative line
    "accepted": "The defendant's objection to jurisdiction is rejected. The request to adjourn "
    "is rejected. The plea of limitation is likewise rejected.",
    "partial": "The objection to jurisdiction is rejected. The plea of limitation is rejected. "
    "The request to join a third party is rejected.",
    "rejected": "The claimant's request for expert evidence was accepted. The late memorandum "
    "was accepted, and the amended statement of claim was accepted.",
    "dismissed": "The claimant's request to amend was accepted and the late filing was "
    "accepted, but notice remains missing.",
}


def en_operative(verdict: str, d: dict) -> str:
    return {
        "accepted": f"The court rules: the claim is accepted and the defendant is ordered to "
        f"{d['remedy']}.",
        "partial": f"The court rules: the claim is partially accepted; the defendant is ordered "
        f"to {d['partial']}, and the remaining requests are rejected.",
        "rejected": "The court rules: the claim is rejected and the claimant bears the costs.",
        "dismissed": "The court rules: the claim is inadmissible for lack of prior notice.",
    }[verdict]


def en_press(verdict: str, d: dict, a: str, b: str) -> str:
    ruling = {
        "accepted": f"the claim is accepted and the defendant is ordered to {d['remedy']}",
        "partial": f"the claim is partially accepted; the defendant is ordered to {d['partial']}",
        "rejected": "the claim is rejected and the claimant bears the costs",
        "dismissed": "the claim is inadmissible for lack of prior notice",
    }[verdict]
    return f"Press summary: in the dispute between {a} and {b}, the court ruled that {ruling}."


# --------------------------------------------------------------------------- Arabic

AR_PARTIES = [
    ("شركة المرفأ للخدمات اللوجستية", "شركة الدلتا للأغذية"),
    ("السيد سمير حداد", "شركة الهلال العقارية"),
    ("مؤسسة البوابة الشمالية للمقاولات", "السيدة لينا فرح"),
    ("شركة أطلس التجارية", "شركة الساحل الأزرق للاستيراد"),
    ("السيد عمر ناصر", "شركة النقل الحضري"),
    ("عيادات الأرز", "شركة أوريون للمستلزمات الطبية"),
]

AR_DOMAINS = {
    "lease": dict(
        subject="فسخ عقد إيجار تجاري لعدم دفع الأجرة",
        remedy="بإخلاء المأجور ودفع الأجرة المتأخرة البالغة 14,000",
        partial="بدفع مبلغ 9,000 من الأجرة المتأخرة",
        defense="أن الأجرة حُبست لامتناع المؤجر عن إجراء الإصلاحات",
        principles=[
            "يحق للمؤجر طلب الفسخ إذا تخلف المستأجر عن دفع الأجرة بعد إنذاره.",
            "لا يجوز للمستأجر حبس الأجرة بسبب الإصلاحات دون إذن من المحكمة.",
        ],
    ),
    "employment": dict(
        subject="مكافأة نهاية الخدمة وبدل الإنذار",
        remedy="بدفع مكافأة نهاية الخدمة البالغة 22,500 وبدل إنذار عن شهر",
        partial="بدفع مكافأة نهاية الخدمة البالغة 22,500",
        defense="أن العامل استقال دون إشعار فسقط حقه في المكافأة",
        principles=[
            "تحسب المكافأة على أساس آخر أجر أساسي عن كل سنة من سنوات الخدمة المتصلة.",
            "لا تُسقط الاستقالة المكافأة المستحقة وفق العقد.",
        ],
    ),
    "sale": dict(
        subject="استرداد ثمن ثلاجات صناعية معيبة",
        remedy="باسترداد البضاعة ورد الثمن البالغ 48,000",
        partial="برد مبلغ 30,000 عن الوحدات الثابت عيبها",
        defense="أن العيوب نشأت عن سوء التركيب من قبل المشتري",
        principles=[
            "يضمن البائع العيوب الخفية الموجودة وقت التسليم والتي تجعل المبيع غير صالح للانتفاع.",
            "على المشتري إخطار البائع بالعيب خلال مدة معقولة من اكتشافه.",
        ],
    ),
    "loan": dict(
        subject="استرداد قرض شخصي",
        remedy="برد مبلغ القرض البالغ 60,000 مع الفائدة القانونية",
        partial="برد مبلغ 35,000 من القرض",
        defense="أن جزءاً من المبلغ كان هبة لا قرضاً",
        principles=[
            "يثبت القرض الذي يجاوز النصاب القانوني بالكتابة أو بإقرار مكتوب.",
            "تُخصم الدفعات الجزئية من أصل الدين ما لم يُتفق على غير ذلك.",
        ],
    ),
    "tort": dict(
        subject="التعويض عن إصابات ناتجة عن حادث سير",
        remedy="بدفع تعويض قدره 75,000 عن الضرر المادي والمعنوي",
        partial="بدفع تعويض قدره 40,000 عن الضرر المادي",
        defense="أن المدعي ساهم في الحادث بعبوره خارج ممر المشاة",
        principles=[
            "حارس المركبة مسؤول عما تحدثه من ضرر ما لم يثبت السبب الأجنبي.",
            "يُنقص التعويض بقدر خطأ المضرور.",
        ],
    ),
    "construction": dict(
        subject="غرامة التأخير التعاقدية عن تأخر إنجاز فيلا",
        remedy="بدفع غرامة التأخير التعاقدية البالغة 90,000",
        partial="بدفع غرامة تأخير مخفضة قدرها 45,000",
        defense="أن التأخير نتج عن تأخر صاحب العمل في استصدار الموافقات",
        principles=[
            "يجوز تخفيض الشرط الجزائي إذا كان مبالغاً فيه بالنسبة للضرر الفعلي.",
            "يُعفى المقاول من التأخير الراجع إلى فعل صاحب العمل.",
        ],
    ),
}

AR_FACTS = {
    "accepted": "قدم المدعي العقد الموقع وما يثبت الإخلال، ولم ينازع المدعى عليه في المستندات.",
    "partial": "ثبت الإخلال، إلا أن جزءاً من المبلغ المطالب به لا يسنده أي مستند.",
    "rejected": "لم تثبت مستندات المدعي الإخلال، وقدم المدعى عليه ما يثبت تنفيذ التزاماته.",
    "dismissed": "أقيمت الدعوى دون الإنذار المسبق الذي يوجبه القانون.",
}

AR_REASONING = {
    "accepted": "ثبت الالتزام والإخلال به من المستندات، ولم يقم دليل على دفاع المدعى عليه.",
    "partial": "ثبت الالتزام، لكن المدعي لم يثبت إلا جزءاً من المبلغ المطالب به.",
    "rejected": "عبء الإثبات على المدعي ولم يثبت الإخلال، وسجلات المدعى عليه تثبت التنفيذ.",
    "dismissed": "يوجب القانون الإنذار قبل رفع الدعوى، ولم يتم الإنذار فلا تنظر المحكمة في الموضوع.",
}

AR_TRAP = {
    "accepted": "وتقرر المحكمة رفض الدفع بعدم الاختصاص، كما تقرر رفض طلب التأجيل، "
    "وتقرر رفض الدفع بالتقادم.",
    "partial": "وتقرر المحكمة رفض الدفع بعدم الاختصاص، وتقرر رفض الدفع بالتقادم، "
    "وتقرر رفض طلب الإدخال.",
    "rejected": "وقد سبق قبول طلب الخبرة، كما تقرر قبول المذكرة المتأخرة، وتقرر قبول "
    "تعديل الطلبات.",
    "dismissed": "وقد تقرر قبول طلب التعديل، وتقرر قبول المذكرة المتأخرة، إلا أن الإنذار ما "
    "زال مفقوداً.",
}


def ar_operative(verdict: str, d: dict) -> str:
    return {
        "accepted": f"حكمت المحكمة بقبول الدعوى وإلزام المدعى عليه {d['remedy']}.",
        "partial": f"حكمت المحكمة بقبول الدعوى جزئياً وإلزام المدعى عليه {d['partial']} "
        "ورد ما زاد على ذلك.",
        "rejected": "حكمت المحكمة برد الدعوى وتضمين المدعي الرسوم والمصاريف.",
        "dismissed": "حكمت المحكمة بعدم قبول الدعوى لعدم توجيه الإنذار المسبق.",
    }[verdict]


def ar_press(verdict: str, d: dict, a: str, b: str) -> str:
    # Diacritics and hamza variants on purpose: the guard must normalize to catch it.
    ruling = {
        "accepted": f"حَكَمَت المحكمةُ بقبولِ الدعوى وإلزام المدعى عليه {d['remedy']}",
        "partial": f"حكمت المحكمة بقبول الدعوى جزئيًا وإلزام المدعى عليه {d['partial']}",
        "rejected": "حكمت المحكمة برد الدعوى وتضمين المدعي الرسوم والمصاريف",
        "dismissed": "حكمت المحكمة بعدم قبول الدعوى لعدم توجيه الانذار المسبق",
    }[verdict]
    return f"ملخص صحفي: في النزاع بين {a} و{b}، {ruling}."


# --------------------------------------------------------------------------- build


def build_case(lang: str, i: int) -> dict:
    en = lang == "en"
    domains = EN_DOMAINS if en else AR_DOMAINS
    domain = list(domains)[i % len(domains)]
    d = domains[domain]
    verdict = VERDICT_CYCLE[(i * 5 + (0 if en else 2)) % len(VERDICT_CYCLE)]
    a, b = (EN_PARTIES if en else AR_PARTIES)[(i * 7) % 6]
    cid = f"{lang}-{domain}-{i:03d}"
    source_doc_id = f"judg-{cid}"

    if en:
        input_text = (
            f"Case summary: {a} v. {b}. The claimant seeks {d['subject']}. "
            f"{EN_FACTS[verdict]} The defendant argues that {d['defense']}. "
            "Predict the court's judgment and end with the operative part."
        )
        reasoning = EN_REASONING[verdict]
        trap = EN_TRAP[verdict]
        operative = en_operative(verdict, d)
        head = "Reasoning:"
    else:
        input_text = (
            f"ملخص الدعوى: {a} ضد {b}. يطلب المدعي {d['subject']}. {AR_FACTS[verdict]} "
            f"ويدفع المدعى عليه {d['defense']}. توقع حكم المحكمة واختم بمنطوق الحكم."
        )
        reasoning = AR_REASONING[verdict]
        trap = AR_TRAP[verdict]
        operative = ar_operative(verdict, d)
        head = "الأسباب:"

    seeded = None
    body = f"{head} {reasoning}"
    if i in WHOLE_TEXT:
        body = f"{body} {trap}"
        seeded = "whole_text"
    expected = f"{body}\n{operative}"

    context = [
        {"doc_id": f"cass-{domain}-{k + 1}", "text": text} for k, text in enumerate(d["principles"])
    ]
    if i in SELF_RETRIEVAL:
        seeded = "self_retrieval"
        if SELF_RETRIEVAL[i] == "id":
            context.append({"doc_id": source_doc_id, "text": expected})
        else:
            # The same judgment under another id, lightly edited: only fuzzy matching finds it.
            copy = expected.replace("The court rules", "THE COURT RULES").replace(
                "حكمت المحكمة", "حَكَمَت المحكمة"
            )
            prefix = "Archived copy." if en else "نسخة مؤرشفة."
            context.append({"doc_id": f"archive-{i:03d}-{lang}", "text": f"{prefix} {copy}"})
    elif i in ANSWER_BEARING:
        seeded = "answer_bearing"
        press = en_press(verdict, d, a, b) if en else ar_press(verdict, d, a, b)
        context.append({"doc_id": f"news-{lang}-{i:03d}", "text": press})

    case = {
        "id": cid,
        "input": input_text,
        "expected": expected,
        "context": context,
        "tags": ["english" if en else "arabic", domain],
        "source_doc_id": source_doc_id,
        "metadata": {"verdict": verdict, "synthetic": True},
    }
    if seeded:
        case["metadata"]["seeded_trap"] = seeded
    return case


def build() -> list[dict]:
    return [build_case(lang, i) for lang in ("en", "ar") for i in range(PER_LANGUAGE)]


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="\n") as fh:
        for case in build():
            fh.write(json.dumps(case, ensure_ascii=False) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
