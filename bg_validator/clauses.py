"""Layer 2 — clause-by-clause comparison against GAIL F-4 proforma.

Templates below are the canonical clause texts taken from Format.docx
(F-4: Proforma of Bank Guarantee for Contract Performance Security /
Security Deposit), with the fill-in blanks removed. To update the
standard wording, edit CLAUSES only.
"""
import html
import re
from difflib import SequenceMatcher

from rapidfuzz import fuzz

CLAUSES = [
    ("P1", "Preamble — award of work",
     "having registered office at herein after called the contractor which "
     "expression shall wherever the context so require include its successors "
     "and assignees have been placed awarded the job work of vide LOA FOA No "
     "dated for GAIL India Limited having registered office at 16 Bhikaiji "
     "Cama Place R K Puram New Delhi herein after called the GAIL which "
     "expression shall wherever the context so require include its successors "
     "and assignees"),
    ("P2", "Preamble — CPG obligation",
     "The Contract conditions provide that the CONTRACTOR shall pay a sum of "
     "Rs as full Contract Performance Guarantee in the form therein mentioned "
     "The form of payment of Contract Performance Guarantee includes guarantee "
     "executed by Nationalized Bank Scheduled Commercial Bank undertaking full "
     "responsibility to indemnify GAIL INDIA LIMITED in case of default"),
    ("C1", "Clause 1 — irrevocable & unconditional, pay on first demand",
     "We hereby undertake to give the irrevocable and unconditional guarantee "
     "to you that if default shall be made by in performing any of the terms "
     "and conditions of the tender order contract or in payment of any money "
     "payable to GAIL INDIA LIMITED we shall on first demand pay without demur "
     "contest protest and or without any recourse to the contractor to GAIL in "
     "such manner as GAIL may direct the said amount of Rupees only or such "
     "portion thereof not exceeding the said sum as you may require from time "
     "to time"),
    ("C2", "Clause 2 — liberty to postpone rights",
     "You will have the full liberty without reference to us and without "
     "affecting this guarantee postpone for any time or from time to time the "
     "exercise of any of the powers and rights conferred on you under the "
     "order contract with the said and to enforce or to forbear from endorsing "
     "any powers or rights or by reason of time being given to the said and "
     "such postponement forbearance would not have the effect of releasing the "
     "bank from its obligation under this debt"),
    ("C3", "Clause 3 — absolute right to recover despite disputes",
     "Your right to recover the said sum of Rs from us in manner aforesaid is "
     "absolute and unequivocal and will not be affected or suspended by reason "
     "of the fact that any dispute or disputes have been raised by the said "
     "and or that any dispute or disputes are pending before any officer "
     "tribunal or court or arbitrator or any other authority forum and any "
     "demand made by you in the bank shall be conclusive and binding The bank "
     "shall not be released of its obligations under these presents by any "
     "exercise by you of its liberty with reference to matter aforesaid or any "
     "of their or by reason or any other act of omission or commission on your "
     "part or any other indulgence shown by you or by any other matter or "
     "changed what so ever which under law would but for this provision have "
     "the effect of releasing the bank"),
    ("C4", "Clause 4 — survives liquidation / insolvency",
     "The guarantee herein contained shall not be determined or affected by "
     "the liquidation or winding up dissolution or changes of constitution or "
     "insolvency of the said contractor but shall in all respects and for all "
     "purposes be binding and operative until payment of all money due to you "
     "in respect of such liabilities is paid"),
    ("C5", "Clause 5 — no revocation; extension at GAIL's instance",
     "The bank undertakes not to revoke this guarantee during its currency "
     "without your previous consent and further agrees that the guarantee "
     "shall continue to be enforceable until it is discharged by GAIL in "
     "writing However if for any reason the contractor is unable to complete "
     "the work within the period stipulated in the order contract and in case "
     "of extension of the date of delivery completion resulting extension of "
     "defect liability period guarantee period of the contractor fails to "
     "perform the work fully the bank hereby agrees to further extend this "
     "guarantee at the instance of the contractor till such time as may be "
     "determined by GAIL If any further extension of this guarantee is "
     "required the same shall be extended to such required period on receiving "
     "instruction from contractor on whose behalf this guarantee is issued"),
    ("C6", "Clause 6 — bank as principal debtor",
     "Bank also agrees that GAIL at its option shall be entitled to enforce "
     "this Guarantee against the bank as principal debtor in the first instant "
     "without proceeding against the contractor and notwithstanding any "
     "security or other guarantee that GAIL may have in relation to the "
     "contractors liabilities"),
    ("C7", "Clause 7 — payable forthwith; New Delhi jurisdiction",
     "The amount under the Bank Guarantee is payable forthwith without any "
     "delay by Bank upon the written demand raised by GAIL Any dispute arising "
     "out of or in relation to the said Bank Guarantee shall be subject to the "
     "exclusive jurisdiction of courts at New Delhi"),
    ("C8", "Clause 8 — guarantor affirmation, no caveat or argument",
     "Therefore we hereby affirm that we are guarantors and responsible to you "
     "on behalf of the Contractor up to a total amount of and we undertake to "
     "pay you upon your first written demand declaring the Contractor to be in "
     "default under the order contract and without caveat or argument any sum "
     "or sums within the limits of amounts of guarantee as aforesaid without "
     "your needing to prove or show grounds or reasons for your demand or the "
     "sum specified therein"),
    ("C9", "Notwithstanding (a/b/c) — cap, validity, claim discharge",
     "Notwithstanding anything contained herein The Banks liability under this "
     "Guarantee shall not exceed currency in figures currency in words only "
     "This Guarantee shall remain in force upto and any extension s thereof "
     "and The Bank shall be released and discharged from all liability under "
     "this Guarantee unless a written claim or demand is issued to the Bank on "
     "or before the midnight of and if extended the date of expiry of the last "
     "extension of this Guarantee If a claim has been received by us within "
     "the said date all the rights of GAIL under this Guarantee shall be valid "
     "and shall not cease until we have satisfied that claim"),
]

PASS_AT = 90
WARN_AT = 76


def _norm(text):
    t = text.replace("&", " and ")
    t = re.sub(r"[^A-Za-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip().lower()  # lowercase: rapidfuzz token_set_ratio is case-sensitive
    # F-4 says "contractor"; supply/service BGs lawfully substitute these:
    t = re.sub(r"\bservice\s+provider\b", "contractor", t, flags=re.I)
    t = re.sub(r"\bsuppliers\b", "contractors", t, flags=re.I)
    t = re.sub(r"\bsupplier\b", "contractor", t, flags=re.I)
    t = re.sub(r"\bsupply\s*/\s*work\b", "work", t, flags=re.I)
    # strip digital-signature / e-Stamp / bank-contact boilerplate that
    # PyMuPDF splices INTO clause text on signed BGs (NeSL, Bank of Baroda).
    # The signature->address->certificate block is one contiguous run; remove
    # it whole between its start anchor and the e-Stamp id / SWIFT line:
    t = re.sub(
        r"\b(?:signature\s+(?:in)?valid|digitally\s+signed)\b[\s\S]{0,400}?"
        r"(?:\bin[-\s]?[a-z]{2}\d[a-z0-9]{9,}v?\b"
        r"|swift\s+[a-z]{4}\s+[a-z]{2}\s+\d{2}(?:\s+\d{2,4})?)",
        " ", t, flags=re.I)
    # mop up standalone remnants when the block isn't fully bracketed:
    for _p in (
        r"digitally\s+signed\s+by[\s\S]{0,160}?ist",
        r"reason\s+agreement\s+executed\s+location\s+\w+",
        r"signature\s+(?:not\s+)?(?:in)?valid",
        r"signature\s+not\s+verified",
        r"certificate\s+number\s+in[\s-]?[a-z]{2}[a-z0-9]{8,}",
        r"\bin[-\s]?[a-z]{2}\d[a-z0-9]{9,}v?\b",
        r"\bfax\s+number\b[\s\S]{0,12}?\d{4,}",
        r"\bemail\b[\s\S]{0,60}?\bco\s+in\b",
        r"\bswift\b\s+[a-z]{4}\s+[a-z]{2}\s+\d{2}(?:\s+\d{2,4})?",
        # proforma fill-in INSTRUCTION text (parenthetical F-4 guidance that
        # completed BGs replace with real values) — drop on BOTH template and
        # document so neither side is penalised for it:
        r"currency\s+in\s+figures",
        r"currency\s+in\s+words\s+only",
        r"this\s+date\s+should\s+be\s+expiry\s+date\s+of\s+defect\s+liability\s+period\s+of\s+the\s+contract",
        r"indicate\s+date\s+of\s+expiry\s+of\s+claim\s+period\s+which\s+includes\s+(?:minimum\s+)?three\s+months\s+from\s+the\s+expiry\s+of\s+this\s+bank\s+guarantee",
        r"\bthe\s+midnight\s+of\b",
    ):
        t = re.sub(_p, " ", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _diff_html(template_words, doc_words):
    """Word-level diff. Deletions (missing standard wording) are critical;
    insertions (extra wording in the BG) are shown subdued — most are just
    the filled-in names/amounts."""
    sm = SequenceMatcher(None,
                         [w.lower() for w in template_words],
                         [w.lower() for w in doc_words], autojunk=False)
    opcodes = sm.get_opcodes()
    # padding adds surrounding doc text at the edges; drop those inserts
    if opcodes and opcodes[0][0] == "insert":
        opcodes = opcodes[1:]
    if opcodes and opcodes[-1][0] == "insert":
        opcodes = opcodes[:-1]
    out = []
    for op, a1, a2, b1, b2 in opcodes:
        if op == "equal":
            out.append(html.escape(" ".join(doc_words[b1:b2])))
        elif op == "delete":
            out.append("<del>" + html.escape(
                " ".join(template_words[a1:a2])) + "</del>")
        elif op == "insert":
            out.append("<ins>" + html.escape(
                " ".join(doc_words[b1:b2])) + "</ins>")
        else:  # replace
            out.append("<del>" + html.escape(
                " ".join(template_words[a1:a2])) + "</del>")
            out.append("<ins>" + html.escape(
                " ".join(doc_words[b1:b2])) + "</ins>")
    return " ".join(out)


def compare_clauses(doc_text):
    doc_norm = _norm(doc_text)
    doc_words = doc_norm.split()
    results = []
    for cid, title, template in CLAUSES:
        tpl_norm = _norm(template)
        align = fuzz.partial_ratio_alignment(tpl_norm, doc_norm)
        if align is None:
            results.append({"id": cid, "title": title, "score": 0,
                            "status": "fail",
                            "diff": "<del>" + html.escape(template) + "</del>",
                            "note": "Clause not found in document."})
            continue
        # pad the aligned span (alignment can clip clause edges), then
        # snap to word boundaries; edge noise is trimmed in the diff
        pad = max(80, (len(tpl_norm) - (align.dest_end - align.dest_start)))
        raw_start = max(0, align.dest_start - pad)
        raw_end = min(len(doc_norm), align.dest_end + pad)
        start = doc_norm.rfind(" ", 0, raw_start) + 1
        end_sp = doc_norm.find(" ", raw_end)
        end = len(doc_norm) if end_sp == -1 else end_sp
        span_words = doc_norm[start:end].split()
        score = fuzz.token_set_ratio(tpl_norm, " ".join(span_words))
        status = ("pass" if score >= PASS_AT
                  else "warn" if score >= WARN_AT else "fail")
        note = ""
        if status == "warn":
            note = ("Wording deviates from F-4 — review the highlighted "
                    "differences (may be OCR noise or a real modification).")
        elif status == "fail":
            note = ("Substantial deviation or clause missing — escalate "
                    "before acceptance.")
        results.append({
            "id": cid, "title": title, "score": round(score, 1),
            "status": status,
            "diff": _diff_html(tpl_norm.split(), span_words),
            "note": note,
        })
    return results
