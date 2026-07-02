"""Human-in-the-loop feedback logging for the BG Validator.

The rule engine in rules.py / clauses.py is deterministic — there is no LLM
in this pipeline, so "confidence" here means fuzzy-match score, not a model's
self-reported certainty. Anything that isn't a clean PASS (i.e. status is
"warn" or "fail") is routed to a human reviewer rather than auto-resolved.

Every human decision is appended to a local, append-only JSON-lines log.
This log is never read back into the validator automatically — a bad or
malicious entry cannot silently change a future verdict. It exists purely
as an audit trail and as raw material for later recalibrating thresholds
(PASS_AT/WARN_AT in clauses.py, FUZZY_THRESHOLD in rules.py) once enough
real review decisions have accumulated.
"""
import json
import os
from datetime import datetime, timezone

LOG_PATH = "bg_validator_feedback_log.jsonl"


def log_review(filename, bg_number, item_id, item_kind, ai_status,
               ai_detail, human_decision, human_status, comment,
               reviewer=""):
    """Append one human adjudication record.

    human_decision is "agree" or "override". human_status is the final
    status ("pass"/"warn"/"fail") after the human's input. Overrides without
    a comment are rejected by the calling UI before this is ever invoked —
    this function does not itself enforce that, callers must.
    """
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "filename": filename,
        "bg_number": bg_number,
        "item_id": item_id,
        "item_kind": item_kind,            # "check" or "clause"
        "ai_status": ai_status,
        "ai_detail": ai_detail,
        "human_decision": human_decision,  # "agree" | "override"
        "human_status": human_status,
        "comment": comment,
        "reviewer": reviewer,
    }
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def load_log():
    if not os.path.exists(LOG_PATH):
        return []
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def summary_stats():
    """Agreement rate between the rule engine and human reviewers so far.

    A falling agreement rate on a particular item_id over time is the
    signal to go tighten/loosen that specific rule or clause threshold —
    this is the manual analogue of the paper's "prior-year statistics"
    debiasing step, since this pipeline has no model to retrain.
    """
    rows = load_log()
    if not rows:
        return {"total": 0, "agree": 0, "override": 0,
                "agreement_rate": None, "by_item": {}}
    agree = sum(1 for r in rows if r["human_decision"] == "agree")
    override = len(rows) - agree
    by_item = {}
    for r in rows:
        bucket = by_item.setdefault(
            r["item_id"], {"total": 0, "agree": 0, "override": 0})
        bucket["total"] += 1
        bucket[r["human_decision"] if r["human_decision"] == "agree"
               else "override"] += 1
    return {
        "total": len(rows),
        "agree": agree,
        "override": override,
        "agreement_rate": round(100 * agree / len(rows), 1),
        "by_item": by_item,
    }
