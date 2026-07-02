# GAIL BG Validator — Web App (Render-ready)

Three-tab reviewer workflow over the F-4 scrutiny engine:

1. **Upload** — drop multiple PDFs (only .pdf accepted), click "Run AI review".
2. **AI Review** — three-column workspace: document list · source PDF ·
   F-4 scrutiny. Failed/review clauses open with a comment box to justify;
   pick **Valid / Invalid**, optional reason code, **Submit**.
3. **Completed** — submitted reviews, read-only, with "View PDF" and a
   CSV export (the training-data seed).

## Run locally
    pip install -r requirements.txt
    python app.py            # http://localhost:5000
(Scanned PDFs need Tesseract: `apt-get install tesseract-ocr`.)

## Deploy on Render
1. Push this folder to a GitHub repo.
2. Render → New → Blueprint → pick the repo (uses render.yaml), OR
   New → Web Service → repo, with:
     Build:  pip install -r requirements.txt
     Start:  gunicorn app:app --timeout 180 --workers 1 --bind 0.0.0.0:$PORT
3. The `Aptfile` installs Tesseract OCR automatically (needed for scanned BGs).
4. Free plan works; first request after idle has a cold start (~30 s).

## Notes
- Reviews persist to SQLite (review.db). On Render's free plan the disk is
  ephemeral — attach a **persistent disk** (mount at the app dir) to keep
  review history and uploaded PDFs across restarts. Without it, the CSV
  export is your durable record; download it periodically.
- Uploaded PDFs are held in memory for the session so the "View PDF" link
  works during review; they may expire after a restart (shown as "expired"
  in Completed). The review row + comments always persist in the DB.
- This is decision-support; final acceptance stays with C&P / F&A.

## PDF highlighting (new)
Flagged clauses are boxed on the rendered PDF: red = fail, orange = review,
blue = info. Clicking a flagged clause on the right jumps to its highlight.
- Rendering uses PDF.js (loaded from CDN — Render has internet, so it works
  in production; if your network blocks cdnjs, vendor pdf.min.js +
  pdf.worker.min.js into static/ and repoint the two <script>/worker URLs).
- Highlight location is reliable for clean clauses and APPROXIMATE on
  signature-overlaid regions (marked with a subtler box + tooltip). It marks
  the clause area, not every individual wrong word.
