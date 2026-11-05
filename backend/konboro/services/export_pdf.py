"""The customer PDF (13 §4.1, 07 §12, 12 "HTML שמודפס דרך Chromium"; S26): HTML built in code, then printed by
Chromium through Playwright.

The page is right to left, in the app's own fonts embedded from `fonts/` (OFL, no network), with numbers, SKUs and
amounts isolated left to right (CLAUDE.md non-negotiable 10). Every value from the quote or the factory's template is
escaped, and Chromium may load nothing from the network: a description or the terms can never become markup or a
request. A draft has "טיוטה" across every page (S26 decision 3).
"""

import base64
from functools import cache
from html import escape
from pathlib import Path

from konboro.services.export import Document, Row, percent, quantity, shekels

FONTS = Path(__file__).with_name("fonts")
RENDER_TIMEOUT_MS = 20_000

# The body font's two subsets, regular and semibold, and the mono for SKUs (@fontsource's files, as the app loads them)
FONT_FACES = (
    (
        "IBM Plex Sans Hebrew",
        400,
        "ibm-plex-sans-hebrew-hebrew-400-normal",
        "U+0307-0308,U+0590-05FF,U+200C-2010,U+20AA,U+25CC,U+FB1D-FB4F",
    ),
    (
        "IBM Plex Sans Hebrew",
        600,
        "ibm-plex-sans-hebrew-hebrew-600-normal",
        "U+0307-0308,U+0590-05FF,U+200C-2010,U+20AA,U+25CC,U+FB1D-FB4F",
    ),
    (
        "IBM Plex Sans Hebrew",
        400,
        "ibm-plex-sans-hebrew-latin-400-normal",
        "U+0000-00FF,U+2000-206F,U+20AC,U+2122,U+2212",
    ),
    (
        "IBM Plex Sans Hebrew",
        600,
        "ibm-plex-sans-hebrew-latin-600-normal",
        "U+0000-00FF,U+2000-206F,U+20AC,U+2122,U+2212",
    ),
    ("IBM Plex Mono", 400, "ibm-plex-mono-latin-400-normal", "U+0000-00FF,U+2000-206F"),
)

CSS = """
@page { size: A4; margin: 16mm 14mm 18mm 14mm; }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { margin: 0; font-family: "IBM Plex Sans Hebrew", sans-serif; font-size: 10.5pt; line-height: 1.45;
  color: #1a1a1a; }
.num, .sku { direction: ltr; unicode-bidi: isolate; }
.num { font-variant-numeric: tabular-nums; }
.sku { font-family: "IBM Plex Mono", monospace; font-size: 9pt; }
header { display: flex; align-items: flex-start; gap: 16px; padding-bottom: 12px; border-bottom: 2px solid #1a1a1a; }
header .logo { max-height: 56px; max-width: 180px; object-fit: contain; }
header .company { display: grid; gap: 1px; }
header .company b { font-size: 13pt; }
header .company span { color: #555; font-size: 9.5pt; }
.title { display: flex; align-items: baseline; gap: 12px; margin: 16px 0 4px; }
.title h1 { font-size: 18pt; margin: 0; font-weight: 600; }
.meta { display: flex; flex-wrap: wrap; gap: 4px 18px; color: #444; font-size: 9.5pt; margin-bottom: 14px; }
table { width: 100%; border-collapse: collapse; }
thead { display: table-header-group; }
th { text-align: start; font-weight: 600; font-size: 9pt; color: #555; border-bottom: 1.5px solid #1a1a1a;
  padding: 5px 4px; }
td { border-bottom: 1px solid #e3e3e3; padding: 5px 4px; vertical-align: top; }
tr { break-inside: avoid; }
td.n, th.n { text-align: end; white-space: nowrap; }
tr.panel td { font-weight: 600; padding-top: 12px; border-bottom: 1px solid #999; }
tr.subtotal td { font-weight: 600; border-bottom: none; color: #333; }
.totals { margin-top: 14px; margin-inline-start: auto; width: 46%; break-inside: avoid; }
.totals div { display: flex; justify-content: space-between; padding: 3px 0; }
.totals .gross { border-top: 2px solid #1a1a1a; margin-top: 4px; padding-top: 6px; font-weight: 600; font-size: 12pt; }
.terms { margin-top: 22px; white-space: pre-line; font-size: 9.5pt; color: #333; break-inside: avoid; }
.terms b { display: block; margin-bottom: 3px; }
.draft { position: fixed; inset: 0; display: flex; align-items: center; justify-content: center; pointer-events: none; }
.draft span { transform: rotate(-30deg); font-size: 110pt; font-weight: 600; color: rgba(0, 0, 0, 0.07); }
.chip { font-size: 9pt; border: 1px solid #999; border-radius: 4px; padding: 0 6px; color: #555; }
"""


@cache
def _font_css() -> str:
    faces = []
    for family, weight, file, ranges in FONT_FACES:
        data = base64.b64encode((FONTS / f"{file}.woff2").read_bytes()).decode()
        faces.append(
            f'@font-face{{font-family:"{family}";font-style:normal;font-weight:{weight};font-display:block;'
            f'src:url(data:font/woff2;base64,{data}) format("woff2");unicode-range:{ranges};}}'
        )
    return "\n".join(faces)


def _num(text: str) -> str:
    return f'<span class="num">{escape(text)}</span>' if text else ""


def _row(r: Row, show_sku: bool) -> str:
    sku = (
        f'<td><span class="sku">{escape(r.sku)}</span></td>' if show_sku and r.sku else "<td></td>" if show_sku else ""
    )
    return (
        f"<tr><td>{escape(r.description)}</td>{sku}"
        f'<td class="n">{_num(quantity(r.qty))}</td>'
        f'<td class="n">{_num(shekels(r.unit_price))}</td>'
        f'<td class="n">{_num(shekels(r.line_total))}</td></tr>'
    )


def customer_html(doc: Document, logo: tuple[bytes, str] | None) -> str:
    """The customer document as one self-contained page. `logo`: its bytes and content type."""
    t = doc.template
    sku = t.show_sku
    cols = 5 if sku else 4
    company = [escape(x) for x in (t.address, t.phone) if x]
    if t.company_id:
        company.insert(0, f'ח.פ. <span class="num">{escape(t.company_id)}</span>')
    logo_img = (
        f'<img class="logo" alt="" src="data:{logo[1]};base64,{base64.b64encode(logo[0]).decode()}">' if logo else ""
    )
    meta = [f"<span>{escape(doc.name)}</span>"]
    if doc.drawing_number:
        meta.append(f'<span>שרטוט <span class="num">{escape(doc.drawing_number)}</span></span>')
    if doc.customer:
        meta.append(f"<span>לכבוד {escape(doc.customer)}</span>")
    if doc.quote_date:
        meta.append(f'<span>תאריך <span class="num">{doc.quote_date:%d.%m.%Y}</span></span>')
    meta.append(f'<span>גרסה <span class="num">{doc.version}</span></span>')

    body: list[str] = []
    several = len(doc.sections) > 1
    for s in doc.sections:
        if several:
            body.append(f'<tr class="panel"><td colspan="{cols}">{escape(s.name)}</td></tr>')
        body += [_row(r, sku) for r in s.rows]
        if several:
            body.append(
                f'<tr class="subtotal"><td colspan="{cols - 1}">סה"כ {escape(s.name)}</td>'
                f'<td class="n">{_num(shekels(s.total))}</td></tr>'
            )

    q = doc.totals
    totals = []
    if q.discount:
        totals.append(f'<div><span>סה"כ</span>{_num(shekels(q.sums.price_total))}</div>')
        totals.append(f"<div><span>הנחה {_num(percent(q.discount_pct))}</span>{_num(shekels(-q.discount))}</div>")
    totals.append(f'<div><span>סה"כ לפני מע"מ</span>{_num(shekels(q.net_total))}</div>')
    totals.append(f'<div><span>מע"מ {_num(percent(q.vat_rate))}</span>{_num(shekels(q.vat))}</div>')
    totals.append(f'<div class="gross"><span>לתשלום</span>{_num(shekels(q.gross_total))}</div>')

    head = "<th>תיאור</th>" + ('<th>מק"ט</th>' if sku else "")
    head += '<th class="n">כמות</th><th class="n">מחיר ליחידה</th><th class="n">סה"כ</th>'
    terms = f'<section class="terms"><b>תנאים</b>{escape(t.terms)}</section>' if t.terms else ""
    draft = '<div class="draft" aria-hidden="true"><span>טיוטה</span></div>' if doc.draft else ""
    details = "".join(f"<span>{c}</span>" for c in company)
    chip = '<span class="chip">טיוטה</span>' if doc.draft else ""
    return f"""<!doctype html>
<html lang="he" dir="rtl"><head><meta charset="utf-8"><title>{escape(doc.name)}</title>
<style>{_font_css()}{CSS}</style></head>
<body>{draft}
<header>{logo_img}<div class="company"><b>{escape(t.name)}</b>{details}</div></header>
<div class="title"><h1>הצעת מחיר</h1>{chip}</div>
<div class="meta">{"".join(meta)}</div>
<table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>
<section class="totals">{"".join(totals)}</section>
{terms}
</body></html>"""


FOOTER = (
    '<div style="width:100%;font-size:8px;color:#888;text-align:center;font-family:sans-serif">'
    '<span class="pageNumber"></span> / <span class="totalPages"></span></div>'
)


def render_pdf(html: str) -> bytes:
    """Prints the page in Chromium (Playwright's sync API, in the request's worker thread). Nothing is fetched: the
    page is self-contained, and every request it would make is refused."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            context = browser.new_context(offline=True)
            page = context.new_page()
            page.route("**/*", lambda route: route.abort())
            page.set_content(html, wait_until="load", timeout=RENDER_TIMEOUT_MS)
            page.evaluate("document.fonts.ready.then(() => true)")
            return page.pdf(
                format="A4",
                print_background=True,
                prefer_css_page_size=True,
                display_header_footer=True,
                header_template="<span></span>",
                footer_template=FOOTER,
            )
        finally:
            browser.close()
