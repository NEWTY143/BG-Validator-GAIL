"""GAIL BG Validator — web app for Render.

Three-stage workflow:
  1) Upload    — multiple PDFs (only .pdf accepted)
  2) AI Review — engine validates each; reviewer sees clauses side-by-side
                 with the PDF, comments on fail/review clauses, marks
                 each BG VALID / INVALID, then submits
  3) Completed — submitted BGs, read-only

Reviews persist to SQLite (review.db) — the same row schema the feedback
notebook produces, so it can later seed a risk model.
"""
import io
import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime

from flask import (Flask, jsonify, render_template, request,
                   send_file, abort)

from bg_validator import validate_pdf
from highlights import build_highlights
from highlights import build_highlights

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("BG_DB", os.path.join(APP_DIR, "review.db"))
# uploaded PDFs are kept in-process for the session (Render's disk is ephemeral
# unless a persistent disk is attached); store bytes in memory keyed by id.
PDF_STORE = {}
JOBS = {}
REPORT_STORE = {}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB total


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id TEXT PRIMARY KEY,
                filename TEXT,
                engine_verdict TEXT,
                reviewer_decision TEXT,
                reason_code TEXT,
                comments_json TEXT,
                report_json TEXT,
                reviewer TEXT,
                reviewed_at TEXT
            )""")


init_db()


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/validate")
def api_validate():
    """Accept multiple PDFs; validate in the BACKGROUND (Render's proxy cuts
    requests at ~100 s, and OCR on the free tier can exceed that). Returns a
    job_id immediately; the frontend polls /api/job/<id> for progress."""
    files = request.files.getlist("files")
    if not files or all(f.filename == "" for f in files):
        return jsonify({"error": "No files received."}), 400

    staged = []
    for f in files:
        staged.append((f.filename,
                       f.read() if f.filename.lower().endswith(".pdf") else None))

    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"status": "running", "done": 0,
                    "total": len(staged), "reports": []}
    threading.Thread(target=_run_job, args=(job_id, staged),
                     daemon=True).start()
    return jsonify({"job_id": job_id, "total": len(staged)})


def _run_job(job_id, staged):
    job = JOBS[job_id]
    for filename, data in staged:
        if data is None:
            job["reports"].append({"filename": filename,
                                   "error": "Only .pdf files are accepted."})
        else:
            try:
                report = validate_pdf(data, filename=filename)
                doc_id = uuid.uuid4().hex
                PDF_STORE[doc_id] = data
                REPORT_STORE[doc_id] = report
                report["doc_id"] = doc_id
                job["reports"].append(report)
            except Exception as exc:  # noqa: BLE001
                job["reports"].append({"filename": filename,
                                       "error": f"Validation failed: {exc}"})
        job["done"] += 1
    job["status"] = "finished"


@app.get("/api/job/<job_id>")
def api_job(job_id):
    job = JOBS.get(job_id)
    if job is None:
        abort(404)
    # only ship reports once finished (keeps polling responses tiny)
    out = {"status": job["status"], "done": job["done"], "total": job["total"]}
    if job["status"] == "finished":
        out["reports"] = job["reports"]
    return jsonify(out)


@app.get("/api/highlights/<doc_id>")
def api_highlights(doc_id):
    data = PDF_STORE.get(doc_id)
    report = REPORT_STORE.get(doc_id)
    if data is None or report is None:
        abort(404)
    try:
        return jsonify(build_highlights(data, report))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"page_sizes": [], "highlights": [], "error": str(exc)})


@app.get("/api/pdf/<doc_id>")
def api_pdf(doc_id):
    data = PDF_STORE.get(doc_id)
    if data is None:
        abort(404)
    return send_file(io.BytesIO(data), mimetype="application/pdf",
                     download_name=f"{doc_id}.pdf")


@app.post("/api/submit")
def api_submit():
    """Persist a completed review."""
    body = request.get_json(force=True)
    required = ("doc_id", "filename", "reviewer_decision", "report")
    if not all(k in body for k in required):
        return jsonify({"error": "Missing fields."}), 400

    row_id = body["doc_id"]
    with db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO reviews
               (id, filename, engine_verdict, reviewer_decision, reason_code,
                comments_json, report_json, reviewer, reviewed_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (row_id, body["filename"],
             body["report"].get("verdict", ""),
             body["reviewer_decision"],
             body.get("reason_code", ""),
             json.dumps(body.get("comments", {})),
             json.dumps(body["report"]),
             body.get("reviewer", ""),
             datetime.now().isoformat(timespec="seconds")))
    return jsonify({"ok": True, "id": row_id})


@app.get("/api/completed")
def api_completed():
    with db() as conn:
        rows = conn.execute(
            """SELECT id, filename, engine_verdict, reviewer_decision,
                      reason_code, comments_json, reviewer, reviewed_at
               FROM reviews ORDER BY reviewed_at DESC""").fetchall()
    out = []
    for r in rows:
        out.append({
            "doc_id": r["id"], "filename": r["filename"],
            "engine_verdict": r["engine_verdict"],
            "reviewer_decision": r["reviewer_decision"],
            "reason_code": r["reason_code"],
            "comments": json.loads(r["comments_json"] or "{}"),
            "reviewer": r["reviewer"], "reviewed_at": r["reviewed_at"],
            "pdf_available": r["id"] in PDF_STORE,
        })
    return jsonify({"completed": out})


@app.get("/api/export")
def api_export():
    """Download all reviews as CSV (training-data seed)."""
    import csv
    with db() as conn:
        rows = conn.execute("SELECT * FROM reviews ORDER BY reviewed_at").fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "filename", "engine_verdict", "reviewer_decision",
                "reason_code", "comments_json", "reviewer", "reviewed_at"])
    for r in rows:
        w.writerow([r["id"], r["filename"], r["engine_verdict"],
                    r["reviewer_decision"], r["reason_code"],
                    r["comments_json"], r["reviewer"], r["reviewed_at"]])
    return send_file(io.BytesIO(buf.getvalue().encode()),
                     mimetype="text/csv", as_attachment=True,
                     download_name="bg_reviews.csv")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
