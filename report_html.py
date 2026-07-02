"""Render a validation report as notebook-friendly HTML (inline styles)."""
import html as H

PALETTE = {"pass": ("#1E6E48", "#E4F0E8"), "warn": ("#9A6B14", "#F5ECD8"),
           "fail": ("#A92E26", "#F6E2DF"), "info": ("#3A566B", "#E7EDF1")}
VERDICT_STYLE = {"COMPLIANT": "#1E6E48", "NEEDS REVIEW": "#9A6B14",
                 "DISCREPANT": "#A92E26"}


def _badge(status):
    fg, bg = PALETTE[status]
    label = "REVIEW" if status == "warn" else ("INFO" if status == "info" else status.upper())
    return (f'<span style="font-family:monospace;font-size:10px;font-weight:700;'
            f'padding:2px 7px;background:{bg};color:{fg};letter-spacing:1px">'
            f'{label}</span>')


def render_report(r):
    f = r["fields"]
    vcol = VERDICT_STYLE[r["verdict"]]
    rows = [("BG number", f.get("bg_number")),
            ("Issuing bank", f.get("issuing_bank")),
            ("Amount (figures)", f"Rs. {f['amount_figures']:,}" if f.get("amount_figures") else None),
            ("Amount (words)", f"Rs. {f['amount_words_value']:,}" if f.get("amount_words_value") else None),
            ("Issue date", f.get("issue")), ("Expiry", f.get("expiry")),
            ("Claim expiry", f.get("claim_expiry")),
            ("PO / LOA / FOA", f.get("po_reference")),
            ("e-Stamp", f.get("estamp_certificate"))]
    field_rows = "".join(
        f'<tr><td style="color:#4A6172;padding:4px 14px 4px 0;border-bottom:1px solid #E2E8E1">{k}</td>'
        f'<td style="font-family:monospace;padding:4px 0;border-bottom:1px solid #E2E8E1">{H.escape(str(v))}</td></tr>'
        for k, v in rows if v)
    checks = "".join(
        f'<div style="padding:7px 0;border-bottom:1px solid #EDF1EC">{_badge(c["status"])} '
        f'<b style="font-size:13.5px">{H.escape(c["label"])}</b>'
        + (f' <span style="font-family:monospace;font-size:11px;color:#4A6172">'
           f'— {c["confidence"]}%</span>' if c.get("confidence") is not None else "")
        + f'<br><span style="font-family:monospace;font-size:11.5px;color:#4A6172;margin-left:62px">'
        f'{H.escape(c["detail"])}</span></div>'
        for c in r["checks"])
    clauses = "".join(
        f'<details {"open" if c["status"] != "pass" else ""} style="border-bottom:1px solid #EDF1EC;padding:5px 0">'
        f'<summary style="cursor:pointer">{_badge(c["status"])} '
        f'<b style="font-size:13.5px">{H.escape(c["title"])}</b> '
        f'<span style="font-family:monospace;color:#4A6172">— {c["score"]}%</span></summary>'
        f'<div style="font-size:13px;line-height:1.8;color:#4A6172;background:#F6F8F4;'
        f'padding:10px 14px;margin-top:6px">'
        + (f'<div style="color:#162B3A;margin-bottom:6px">{H.escape(c["note"])}</div>' if c["note"] else "")
        + c["diff"].replace("<del>", '<del style="background:#F6E2DF;color:#A92E26;padding:0 2px">')
                   .replace("<ins>", '<ins style="background:#E4F0E8;color:#1E6E48;text-decoration:none;padding:0 2px">')
        + '</div></details>'
        for c in r["clauses"])
    ocr = (f'OCR on {r["ocr_pages"]} page(s)' if r["used_ocr"] else "text layer")
    n_review = len(r["review_queue"])
    review_banner = "" if n_review == 0 else (
        f'<div style="margin-top:10px;padding:8px 14px;background:#F5ECD8;'
        f'border:1px solid #9A6B14;color:#9A6B14;font-family:monospace;'
        f'font-size:11.5px;font-weight:700;letter-spacing:0.5px">'
        f'⚠ {n_review} ITEM(S) BELOW REQUIRE HUMAN REVIEW BEFORE SIGN-OFF — '
        f'see the review panel below.</div>')
    return f'''
<div style="font-family:system-ui,Segoe UI,Arial;max-width:880px;border:1.5px solid #162B3A;
            background:#FBFCFA;color:#162B3A;margin:18px 0">
  <div style="display:flex;justify-content:space-between;align-items:center;
              border-bottom:1.5px solid #162B3A;padding:14px 20px">
    <div>
      <div style="font-size:19px;font-weight:600">{H.escape(r["filename"])}</div>
      <div style="font-family:monospace;font-size:11px;color:#4A6172;margin-top:4px">
        {r["kind"].upper()} &middot; {r["page_count"]} PAGES &middot; {ocr.upper()}</div>
    </div>
    <div style="border:3px double {vcol};color:{vcol};padding:8px 16px;transform:rotate(-4deg);
                font-family:monospace;font-weight:700;letter-spacing:3px;font-size:16px">
      {r["verdict"]} (AI)</div>
  </div>
  <div style="padding:14px 20px">
    {review_banner}
    <div style="font-size:11px;letter-spacing:2px;color:#4A6172;font-weight:700;margin-top:14px">EXTRACTED PARTICULARS</div>
    <table style="border-collapse:collapse;font-size:13px;margin:8px 0 16px">{field_rows}</table>
    <div style="font-size:11px;letter-spacing:2px;color:#4A6172;font-weight:700">
      CHECKS — {r["counts"]["fail"]} FAIL &middot; {r["counts"]["warn"]} REVIEW &middot; {r["counts"]["pass"]} PASS</div>
    {checks}
    <div style="font-size:11px;letter-spacing:2px;color:#4A6172;font-weight:700;margin-top:16px">
      CLAUSE-BY-CLAUSE VS F-4 &nbsp;(<del style="background:#F6E2DF;color:#A92E26">missing standard wording</del>
      &middot; <ins style="background:#E4F0E8;color:#1E6E48;text-decoration:none">bank's insertions</ins>)</div>
    {clauses}
  </div>
</div>'''
