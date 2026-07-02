"""GAIL Bank Guarantee Validator — extraction + F-4 compliance engine."""
from .clauses import compare_clauses
from .extract import extract, normalise
from .rules import extract_fields, run_checks
from . import feedback  # noqa: F401  (re-exported: `from bg_validator import feedback`)

ORDER = {"fail": 0, "warn": 1, "pass": 2, "info": 3}


def validate_pdf(pdf_bytes, filename="", expected_amount=None,
                 expected_po=None):
    ext = extract(pdf_bytes)
    norm = normalise(ext["text"])
    fields = extract_fields(norm)
    checks = run_checks(fields, norm, ext["kind"],
                        expected_amount=expected_amount,
                        expected_po=expected_po)
    clauses = compare_clauses(ext["text"])

    # Normalise checks and clauses onto one shared interface (id, label,
    # status, detail, confidence, kind, requires_review) so the review UI
    # and the feedback log never need kind-specific branching — that
    # branching is exactly where inconsistencies tend to creep in.
    for c in checks:
        c["kind"] = "check"
        c.setdefault("confidence", None)
        c["requires_review"] = c["status"] in ("warn", "fail")
    for c in clauses:
        c["kind"] = "clause"
        c["label"] = c["title"]
        c["confidence"] = c["score"]
        c["detail"] = c["note"] or f"Clause similarity {c['score']}%."
        c["requires_review"] = c["status"] in ("warn", "fail")

    statuses = [c["status"] for c in checks] + [c["status"] for c in clauses]
    if "fail" in statuses:
        verdict = "DISCREPANT"
    elif "warn" in statuses:
        verdict = "NEEDS REVIEW"
    else:
        verdict = "COMPLIANT"

    checks.sort(key=lambda c: ORDER.get(c["status"], 9))
    review_queue = [c for c in checks if c["requires_review"]] + \
                   [c for c in clauses if c["requires_review"]]

    return {
        "filename": filename,
        "kind": ext["kind"],
        "page_count": ext["page_count"],
        "used_ocr": ext["used_ocr"],
        "ocr_pages": ext["ocr_pages"],
        "fields": fields,
        "checks": checks,
        "clauses": clauses,
        "verdict": verdict,
        "review_queue": review_queue,
        "human_reviewed": False,
        "counts": {
            "fail": statuses.count("fail"),
            "warn": statuses.count("warn"),
            "pass": statuses.count("pass"),
        },
    }
