"""Locate flagged clauses AND found info-phrases as coloured highlight boxes.

Output (consumed by the PDF.js overlay):
  {"page_sizes":[{"w","h"}...],
   "highlights":[{"page","rect":[x0,y0,x1,y1],"status","color","id","label",
                  "match","approx"}...]}
red=fail, orange=warn/review, blue=info. Clean regions precise;
signature-scrambled regions approximate (approx=True, drawn translucent).
"""
import re
import fitz
from rapidfuzz import fuzz
from bg_validator import clauses as _C

MIN_MATCH = 55
APPROX_BELOW = 80
COLORS = {
    "fail": "rgba(229,96,77,0.32)",
    "warn": "rgba(224,169,59,0.32)",
    "info": "rgba(111,168,199,0.32)",
}
# info phrases worth boxing when they ARE present in the document
INFO_PHRASES = {
    "sfms_clause": "transmitted by the issuing bank through sfms",
    "ifn760": "ifn 760 cov",
}


def _norm_word(w):
    return re.sub(r"[^a-z0-9]", "", w.lower())


def _page_words(page):
    out = []
    for w in page.get_text("words"):
        nw = _norm_word(w[4])
        if nw:
            out.append((nw, [w[0], w[1], w[2], w[3]]))
    return out


def _merge_lines(boxes, y_tol=3.0):
    if not boxes:
        return []
    boxes = sorted(boxes, key=lambda b: (round(b[1] / y_tol), b[0]))
    lines, cur = [], None
    for x0, y0, x1, y1 in boxes:
        if cur and abs(y0 - cur[1]) <= y_tol:
            cur = [min(cur[0], x0), min(cur[1], y0),
                   max(cur[2], x1), max(cur[3], y1)]
        else:
            if cur:
                lines.append(cur)
            cur = [x0, y0, x1, y1]
    if cur:
        lines.append(cur)
    return lines


def _locate(doc, phrase_norm):
    """Best matching word-run for a normalised phrase; returns (page, boxes, score)."""
    tpl_words = phrase_norm.split()
    if not tpl_words:
        return None
    L = len(tpl_words)
    best = None
    for pi in range(doc.page_count):
        pw = _page_words(doc[pi])
        toks = [w[0] for w in pw]
        if len(toks) < 2:
            continue
        step = max(2, L // 8)
        for i in range(0, max(1, len(toks) - max(1, L // 2)), step):
            sc = fuzz.token_set_ratio(phrase_norm, " ".join(toks[i:i + L]))
            if best is None or sc > best[0]:
                best = (sc, pi, i, min(len(toks), i + L))
    if not best or best[0] < MIN_MATCH:
        return None
    sc, pi, s, e = best
    pw = _page_words(doc[pi])
    return pi, [pw[j][1] for j in range(s, e)], round(sc, 1)


def build_highlights(pdf_bytes, report):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_sizes = [{"w": doc[p].rect.width, "h": doc[p].rect.height}
                  for p in range(doc.page_count)]
    out = []

    # 1) flagged clauses (fail / warn) -> red / orange
    tpl_by_id = {cid: tpl for cid, _t, tpl in _C.CLAUSES}
    for cl in report.get("clauses", []):
        if cl["status"] not in ("fail", "warn"):
            continue
        tpl = tpl_by_id.get(cl["id"])
        if not tpl:
            continue
        found = _locate(doc, _C._norm(tpl))
        if not found:
            continue
        pi, boxes, score = found
        approx = score < APPROX_BELOW
        for rect in _merge_lines(boxes):
            out.append({"page": pi, "rect": rect, "status": cl["status"],
                        "color": COLORS[cl["status"]], "id": cl["id"],
                        "label": cl["title"], "match": score, "approx": approx})

    # 2) info phrases (e.g. SFMS) -> blue, ONLY when actually present in the PDF
    for ch in report.get("checks", []):
        if ch.get("status") != "info":
            continue
        phrase = INFO_PHRASES.get(ch["id"])
        if not phrase:
            continue
        found = _locate(doc, phrase)
        if not found:
            continue           # phrase absent -> nothing to box (correct)
        pi, boxes, score = found
        if score < 80:         # info: only box confident matches, avoid noise
            continue
        for rect in _merge_lines(boxes):
            out.append({"page": pi, "rect": rect, "status": "info",
                        "color": COLORS["info"], "id": ch["id"],
                        "label": ch["label"], "match": score,
                        "approx": score < APPROX_BELOW})
    return {"page_sizes": page_sizes, "highlights": out}
