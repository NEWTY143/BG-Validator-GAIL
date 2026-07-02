"""Layer 1 — deterministic field extraction + rule checks against GAIL F-4."""
import re
from collections import Counter

from datetime import date

from dateutil import parser as dateparser
from dateutil.relativedelta import relativedelta
from rapidfuzz import fuzz

from .numwords import words_to_number

DATE_TOKEN = r"(\d{1,2}\s*[\-/\. ]\s*(?:\d{1,2}|[A-Za-z]{3,9})\s*[\-/\. ]\s*\d{2,4})"

BG_NO_RE = re.compile(
    r"(?:BANK\s+)?(?:GUARANTEE|B\.?\s?G\.?)\s*(?:NO|NUMBER)\b\.?\s*[:\-]?\s*"
    r"([A-Z0-9][A-Z0-9/\-]{5,})", re.I)

AMT_LABELLED_RE = re.compile(
    r"(?:GUARANTEE\s+AMOUNT|BG\s+AMOUNT|sum\s+of|amount\s+of)\s*[:\-]?\s*"
    r"(?:Rs\.?|INR|₹)\s*\.?\s*([\d][\d,]*)", re.I)
AMT_ANY_RE = re.compile(r"(?:Rs\.?|INR|₹)\s*\.?\s*([\d][\d,]{3,})", re.I)

AMT_WORDS_RE = re.compile(
    r"\(\s*(?:Indian\s+)?Rupees\s+([A-Za-z][A-Za-z\s,\-]*?)\s*only\s*\)?", re.I)

ESTAMP_RE = re.compile(r"\bIN-[A-Z]{2}[A-Z0-9]{10,}\b")
PO_RE = re.compile(
    r"(?:PO|LOA|FOA|P\.O\.)\s*(?:/\s*(?:PO|LOA|FOA))*\s*No\.?\s*[:\-]?\s*"
    r"([A-Z0-9][A-Z0-9/\.\-&]{6,})", re.I)

KNOWN_BANKS = [
    "State Bank of India", "Axis Bank", "Canara Bank", "HDFC Bank",
    "ICICI Bank", "Punjab National Bank", "Bank of Baroda", "Union Bank",
    "Bank of India", "IndusInd Bank", "Kotak Mahindra Bank", "IDBI Bank",
    "Indian Bank", "Central Bank of India", "UCO Bank", "Yes Bank",
    "Federal Bank", "Indian Overseas Bank", "Bank of Maharashtra",
]

DATE_PATTERNS = {
    "claim_expiry": [
        r"CLAIM\s+EXPIRY\s+DATE\s*\.?\s*[:\-]?\s*" + DATE_TOKEN,
        r"Claim\s+period\s+up\s*to\s*[:\-]?\s*" + DATE_TOKEN,
        r"on\s+or\s+before\s*(?:the\s+midnight\s+of)?\s*" + DATE_TOKEN,
    ],
    "expiry": [
        r"(?<!CLAIM\s)EXPIRY\s+DATE\s*\.?\s*[:\-]?\s*" + DATE_TOKEN,
        r"valid\s+up\s*to\s*[:\-]?\s*" + DATE_TOKEN,
        r"remain\s+in\s+force\s+up\s*to\s*[:\-]?\s*" + DATE_TOKEN,
    ],
    "issue": [
        r"ISSUANCE\s+DATE\s*[:\-]?\s*" + DATE_TOKEN,
        r"Date\s+of\s+BG\s*[:\-]?\s*" + DATE_TOKEN,
        r"DATED\s*[:\-]\s*" + DATE_TOKEN,
    ],
    "stamp_issue": [
        r"Certificate\s+Issue\s+Date\s*[:\-]?\s*" + DATE_TOKEN,
    ],
}

# Mandatory phrases from the F-4 proforma; fuzzy-matched (OCR tolerant).
PHRASES = [
    ("irrevocable_unconditional",
     "irrevocable and unconditional guarantee",
     "Clause 1 — guarantee declared irrevocable & unconditional", "fail"),
    ("without_demur",
     "on first demand pay without demur contest protest",
     "Clause 1 — payment on first demand without demur/contest/protest", "fail"),
    ("recovery_absolute",
     "absolute and unequivocal and will not be affected or suspended",
     "Clause 3 — GAIL's right to recover is absolute & unequivocal", "fail"),
    ("liquidation_survives",
     "liquidation or winding up dissolution or changes of constitution or insolvency",
     "Clause 4 — guarantee survives liquidation/insolvency of contractor", "fail"),
    ("no_revoke",
     "undertakes not to revoke this guarantee during its currency without your previous consent",
     "Clause 5 — bank cannot revoke without GAIL's consent", "fail"),
    ("principal_debtor",
     "enforce this guarantee against the bank as principal debtor in the first instant",
     "Clause 6 — enforceable against bank as principal debtor", "fail"),
    ("jurisdiction_delhi",
     "exclusive jurisdiction of courts at new delhi",
     "Clause 7 — exclusive jurisdiction of courts at New Delhi", "fail"),
    ("first_written_demand",
     "upon your first written demand declaring",
     "Clause 8 — payable on first written demand without caveat or argument", "fail"),
    ("liability_cap",
     "liability under this guarantee shall not exceed",
     "Clause 9 — liability cap stated (Notwithstanding clause A)", "warn"),
    ("power_of_attorney",
     "power of attorney",
     "Clause 10 — signatory's Power of Attorney referenced", "warn"),
    ("beneficiary_gail",
     "gail india limited",
     "Beneficiary is GAIL (India) Limited", "fail"),
    ("gail_regd_office",
     "16 bhikaiji cama place",
     "GAIL registered office (16, Bhikaiji Cama Place) cited", "warn"),
    ("bank_class",
     "nationalized bank scheduled commercial bank",
     "Issuer described as Nationalized/Scheduled Commercial Bank", "warn"),
]

NESL_PHRASES = [
    ("sfms_clause",
     "transmitted by the issuing bank through sfms",
     "SFMS transmission clause — verify SFMS/IFN-760 confirmation from beneficiary bank", "info"),
    ("ifn760",
     "ifn 760",
     "SFMS message type IFN 760 COV — confirm via banking channel, not PDF", "info"),
]

FUZZY_THRESHOLD = 85

# Core identity fields used as a sanity gate on extraction quality. If too
# few of these are found, the individual checks below are not trustworthy —
# this almost always means a bad scan / unusual layout, not real
# non-compliance, so it must be routed to a human rather than silently
# producing a wall of "fail" results that look like substantive findings.
CORE_FIELDS = ("bg_number", "amount_figures", "expiry", "claim_expiry",
               "issuing_bank")
MIN_CORE_FIELDS = 2


def _to_int(s):
    try:
        return int(s.replace(",", "").split(".")[0])
    except (ValueError, AttributeError):
        return None


def _parse_date(s):
    try:
        return dateparser.parse(s, dayfirst=True, fuzzy=True).date()
    except (ValueError, OverflowError):
        return None


def _find_dates(norm_text):
    out = {}
    consumed_spans = {"claim_expiry": []}
    for key in ("claim_expiry", "expiry", "issue", "stamp_issue"):
        for pat in DATE_PATTERNS[key]:
            for m in re.finditer(pat, norm_text, re.I):
                # don't let the generic EXPIRY pattern re-capture a span
                # already attributed to CLAIM EXPIRY
                if key == "expiry" and any(
                        a <= m.start(1) < b
                        for a, b in consumed_spans["claim_expiry"]):
                    continue
                d = _parse_date(m.group(1))
                if d:
                    out.setdefault(key, []).append(d)
                    if key == "claim_expiry":
                        consumed_spans["claim_expiry"].append(
                            (m.start(1), m.end(1)))
    # fallback: digital-signature date (NeSL), format yyyy.mm.dd
    if "issue" not in out:
        for m in re.finditer(r"Digitally\s+signed.{0,60}?Date\s*:\s*"
                             r"(\d{4})\.(\d{2})\.(\d{2})", norm_text, re.I):
            out.setdefault("issue", []).append(
                _parse_date(f"{m.group(3)}/{m.group(2)}/{m.group(1)}"))
        if "issue" in out:
            out["issue"] = [d for d in out["issue"] if d]
            if not out["issue"]:
                del out["issue"]
    # special: "Dated THIS 28th DAY OF APRIL 2026"
    m = re.search(r"Dated\s+THIS\s+(\d{1,2})\s*(?:st|nd|rd|th)?\s+DAY\s+OF\s+"
                  r"([A-Za-z]+)\s+(\d{4})", norm_text, re.I)
    if m:
        d = _parse_date(f"{m.group(1)} {m.group(2)} {m.group(3)}")
        if d:
            out.setdefault("issue", []).append(d)
    return {k: Counter(v).most_common(1)[0][0] for k, v in out.items()}


def _majority(values):
    return Counter(values).most_common(1)[0][0] if values else None


def extract_fields(norm_text):
    f = {}
    bg_nos = [m.group(1).rstrip("/-") for m in BG_NO_RE.finditer(norm_text)]
    f["bg_number"] = _majority(bg_nos)
    f["bg_number_variants"] = sorted(set(bg_nos))

    labelled = [_to_int(m.group(1)) for m in AMT_LABELLED_RE.finditer(norm_text)]
    labelled = [a for a in labelled if a]
    anyamt = [a for a in (_to_int(m.group(1))
                          for m in AMT_ANY_RE.finditer(norm_text)) if a]
    f["amount_figures"] = _majority(labelled) or _majority(anyamt)

    word_vals = [words_to_number(m.group(1))
                 for m in AMT_WORDS_RE.finditer(norm_text)]
    word_vals = [v for v in word_vals if v]
    f["amount_words_value"] = _majority(word_vals)
    m = AMT_WORDS_RE.search(norm_text)
    f["amount_words_raw"] = m.group(1).strip() if m else None

    f.update({k: v.isoformat() for k, v in _find_dates(norm_text).items()})

    m = ESTAMP_RE.search(norm_text)
    f["estamp_certificate"] = m.group(0) if m else None
    m = re.search(r"Stamp\s+Duty\s+Amount\s*\(?Rs\.?\)?\s*[:\-]?\s*([\d,\.]+)",
                  norm_text, re.I)
    f["stamp_duty"] = m.group(1) if m else None

    m = PO_RE.search(norm_text)
    f["po_reference"] = m.group(1) if m else None

    low = norm_text.lower()
    f["issuing_bank"] = next(
        (b for b in KNOWN_BANKS if b.lower() in low), None)
    return f


def run_checks(fields, norm_text, kind, expected_amount=None, expected_po=None):
    checks = []
    low = re.sub(r"\s+", " ", norm_text.lower().replace("&", " and "))

    def add(cid, label, status, detail, confidence=None):
        checks.append({"id": cid, "label": label, "status": status,
                       "detail": detail, "confidence": confidence})

    # --- extraction-quality gate (must run first: everything below this
    # point is only meaningful if the document was actually readable) ---
    found_core = sum(1 for k in CORE_FIELDS if fields.get(k))
    if found_core < MIN_CORE_FIELDS:
        add("extract_quality", "Automated extraction sufficiency", "fail",
            f"Only {found_core}/{len(CORE_FIELDS)} core fields detected "
            f"(BG number, amount, expiry, claim expiry, issuing bank). "
            f"Automated extraction is unreliable for this document — treat "
            f"every check below as informational only and perform a full "
            f"manual read of the PDF.", confidence=None)

    # --- identity ---
    if fields["bg_number"]:
        variants = fields["bg_number_variants"]
        if len(variants) > 1:
            add("bg_no", "BG number present & consistent across pages", "warn",
                f"Multiple values found: {', '.join(variants)} — verify "
                f"(may be OCR noise). Majority: {fields['bg_number']}")
        else:
            add("bg_no", "BG number present & consistent across pages",
                "pass", fields["bg_number"])
    else:
        add("bg_no", "BG number present", "fail",
            "No Bank Guarantee number could be located.")

    # --- amount ---
    if fields["amount_figures"]:
        add("amt_fig", "Guarantee amount (figures) found", "pass",
            f"Rs. {fields['amount_figures']:,}")
    else:
        add("amt_fig", "Guarantee amount (figures) found", "fail",
            "Could not locate the BG amount in figures.")

    if fields["amount_figures"] and fields["amount_words_value"]:
        if fields["amount_figures"] == fields["amount_words_value"]:
            add("amt_match", "Amount in words matches amount in figures",
                "pass",
                f"Words \u2192 Rs. {fields['amount_words_value']:,} "
                f"(\u201c{fields['amount_words_raw']}\u201d)")
        else:
            add("amt_match", "Amount in words matches amount in figures",
                "fail",
                f"Figures Rs. {fields['amount_figures']:,} vs words "
                f"Rs. {fields['amount_words_value']:,} "
                f"(\u201c{fields['amount_words_raw']}\u201d)")
    else:
        add("amt_match", "Amount in words matches amount in figures", "warn",
            "Amount in words not found / not parseable — verify manually.")

    if expected_amount:
        exp = _to_int(str(expected_amount))
        if exp and fields["amount_figures"] == exp:
            add("amt_expected", "Amount matches contract record", "pass",
                f"Rs. {exp:,}")
        else:
            add("amt_expected", "Amount matches contract record", "fail",
                f"Expected Rs. {exp:,} but BG states "
                f"Rs. {fields['amount_figures']:,}"
                if fields["amount_figures"] else
                f"Expected Rs. {exp:,}; no amount found in BG.")

    # --- dates ---
    issue = fields.get("issue")
    expiry = fields.get("expiry")
    claim = fields.get("claim_expiry")

    add("d_expiry", "BG expiry / validity date found",
        "pass" if expiry else "fail", expiry or "Not found.")
    add("d_claim", "Claim expiry date found",
        "pass" if claim else "fail", claim or "Not found.")
    add("d_issue", "BG issue date found",
        "pass" if issue else "warn", issue or "Not found — verify manually.")

    if expiry and claim:
        e = date.fromisoformat(expiry)
        c = date.fromisoformat(claim)
        need = e + relativedelta(months=3)
        if c >= need:
            add("d_gap", "Claim period ≥ 3 months beyond BG expiry (F-4 rule)",
                "pass", f"Expiry {e} \u2192 claim {c} "
                f"(required ≥ {need}).")
        else:
            add("d_gap", "Claim period ≥ 3 months beyond BG expiry (F-4 rule)",
                "fail", f"Claim expiry {c} is earlier than required {need}.")
    if issue and expiry:
        if date.fromisoformat(expiry) > date.fromisoformat(issue):
            add("d_order", "Expiry date falls after issue date", "pass",
                f"{issue} \u2192 {expiry}")
        else:
            add("d_order", "Expiry date falls after issue date", "fail",
                f"Issue {issue} is not before expiry {expiry}.")

    # --- contract reference ---
    if fields["po_reference"]:
        add("po", "PO / LOA / FOA reference present", "pass",
            fields["po_reference"])
    else:
        add("po", "PO / LOA / FOA reference present", "warn",
            "No contract reference detected — verify manually.")
    if expected_po:
        ratio = fuzz.partial_ratio(expected_po.lower(),
                                   (fields["po_reference"] or "").lower())
        add("po_expected", "Contract reference matches record",
            "pass" if ratio >= 90 else "fail",
            f"Record: {expected_po} | BG: {fields['po_reference'] or '—'}",
            confidence=round(ratio, 1))

    # --- stamping ---
    if fields["estamp_certificate"]:
        duty = f"; stamp duty Rs. {fields['stamp_duty']}" \
            if fields["stamp_duty"] else ""
        add("stamp", "Stamp paper / e-Stamp evidence", "pass",
            f"e-Stamp certificate {fields['estamp_certificate']}{duty}")
        stamp_d, bg_d = fields.get("stamp_issue"), issue
        if stamp_d and bg_d and date.fromisoformat(stamp_d) > date.fromisoformat(bg_d):
            add("stamp_date", "e-Stamp purchased on/before BG execution",
                "fail", f"e-Stamp dated {stamp_d} is after BG date {bg_d}.")
        elif stamp_d and bg_d:
            add("stamp_date", "e-Stamp purchased on/before BG execution",
                "pass", f"e-Stamp {stamp_d} \u2264 BG date {bg_d}")
    elif re.search(r"(?:Sr|Serial)\.?\s*No\.?\s*\d{5,}", norm_text, re.I) \
            or "stamp" in low:
        add("stamp", "Stamp paper / e-Stamp evidence", "warn",
            "Physical stamp paper indicators found — verify serial number, "
            "denomination and state of purchase manually.")
    else:
        add("stamp", "Stamp paper / e-Stamp evidence", "warn",
            "No stamp paper evidence detected.")

    if fields["issuing_bank"]:
        add("bank", "Issuing bank identified", "pass", fields["issuing_bank"])
    else:
        add("bank", "Issuing bank identified", "warn",
            "Bank name not recognised — confirm it is a Nationalized / "
            "Scheduled Commercial Bank.")

    # --- mandatory clause phrases (fuzzy, OCR tolerant) ---
    phrase_sets = PHRASES + (NESL_PHRASES if kind == "nesl" else [])
    for cid, phrase, label, sev in phrase_sets:
        score = fuzz.partial_ratio(phrase, low)
        if score >= FUZZY_THRESHOLD:
            add(cid, label, "pass", f"Found (match {score:.0f}%).",
                confidence=round(score, 1))
        else:
            add(cid, label, sev,
                f"Phrase not found (best match {score:.0f}%) — "
                f"expected wording: \u201c{phrase}\u201d.",
                confidence=round(score, 1))
    return checks
