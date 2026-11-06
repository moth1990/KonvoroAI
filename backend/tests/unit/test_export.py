"""The customer document's HTML and its formatting (13 §4.1, 07 §12; S26). The PDF from Chromium, the Excel and the
routes are in `tests/integration/test_api_export.py`, on the NURSERY fixture."""

import re
from datetime import date
from decimal import Decimal
from html import unescape
from typing import Any, cast

from konboro.domain.totals import Sums, quote_sums
from konboro.services import document_template as dt
from konboro.services import export, export_pdf

D = Decimal


def doc(*sections: export.Section, draft: bool = True, discount: str | None = None, **template: Any) -> export.Document:
    price = sum((s.total for s in sections), D(0))
    sums = quote_sums(Sums(price_total=price), D(discount) if discount else None, D("0.18"))
    return export.Document(
        quote_id="quo_1",
        name="NURSERY",
        drawing_number="26/952",
        customer='לקוח <b>בע"מ</b>',
        version=2,
        draft=draft,
        quote_date=date(2026, 10, 13),
        currency="ILS",
        sections=list(sections),
        totals=sums,
        template=dt.Template(**{"name": "לוחות דמו", **template}),
        view=cast(Any, None),
    )


ROWS = [
    export.Row('מא"ז ABB S201M 1P 16A', "S201M-C16", D("17.000"), "unit", D("42.0000"), D("714.0000")),
    export.Row("ממסר עזר <script>alert(1)</script>", None, D("1.000"), "unit", None, None),
]
ONE = export.Section("NURSERY", ROWS, D("714"))


def text(html: str) -> str:
    """What a reader sees: the body's text, entities read back."""
    return unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.split("</style>", 1)[1])))


def test_the_customer_document_has_rows_and_totals_and_nothing_internal() -> None:
    html = export_pdf.customer_html(doc(ONE), None)
    body = text(html)
    assert 'מא"ז ABB S201M 1P 16A' in body
    assert "₪42" in body and "₪714" in body
    assert "₪714 " in body.split('סה"כ לפני מע"מ', 1)[1]  # the stored net total
    assert "₪128.52" in body and "₪842.52" in body  # 18% VAT and the gross
    # 07 §12: no cost, margin, supplier, price source or colour, by word
    for word in ("עלות", "רווח", "ספק", "מחירון", "ירוק", "צהוב", "אדום", "מקור"):
        assert word not in body, word
    assert '<html lang="he" dir="rtl">' in html
    assert '<span class="num">₪42</span>' in html  # amounts isolated left to right


def test_an_unpriced_row_prints_with_no_amount() -> None:
    html = export_pdf.customer_html(doc(ONE), None)
    row = re.search(r"<tr><td>ממסר עזר.*?</tr>", html)
    assert row is not None
    assert "₪" not in row.group(0)
    assert row.group(0).count('<td class="n"></td>') == 2


def test_every_value_is_escaped() -> None:
    html = export_pdf.customer_html(doc(ONE, terms='<img src="http://x/">'), None)
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert '<img src="http://x/">' not in html and "&lt;img" in html
    assert "<b>בע" not in html  # the customer's name, too


def test_skus_show_only_by_the_factorys_setting() -> None:
    assert "S201M-C16" not in export_pdf.customer_html(doc(ONE), None)
    shown = export_pdf.customer_html(doc(ONE, show_sku=True), None)
    assert '<th>מק"ט</th>' in shown and '<span class="sku">S201M-C16</span>' in shown


def test_a_draft_is_marked_and_a_sent_version_is_not() -> None:
    assert 'class="draft"' in export_pdf.customer_html(doc(ONE), None)
    sent = export_pdf.customer_html(doc(ONE, draft=False), None)
    assert "טיוטה" not in text(sent) and 'class="draft"' not in sent


def test_the_discount_row_only_with_a_discount() -> None:
    assert "הנחה" not in text(export_pdf.customer_html(doc(ONE), None))
    body = text(export_pdf.customer_html(doc(ONE, discount="0.05"), None))
    assert "הנחה 5%" in body and "-₪35.70" in body
    assert "₪678.30" in body  # 714 − 35.70 before VAT


def test_several_panels_get_their_headings_and_subtotals() -> None:
    two = export.Section("לוח 2", [ROWS[0]], D("714"))
    body = text(export_pdf.customer_html(doc(ONE, two), None))
    assert 'סה"כ NURSERY ₪714' in body and 'סה"כ לוח 2 ₪714' in body
    assert 'סה"כ NURSERY' not in text(export_pdf.customer_html(doc(ONE), None))


def test_the_factorys_details_terms_and_logo() -> None:
    html = export_pdf.customer_html(
        doc(ONE, company_id="510000000", address="רח' המלאכה 7", phone="03-5550123", terms="שורה 1\nשורה 2"),
        (b"\x89PNG fake", "image/png"),
    )
    assert "לוחות דמו" in html and "510000000" in html and "03-5550123" in html
    assert "שורה 1\nשורה 2" in html  # pre-line keeps the factory's lines
    assert 'src="data:image/png;base64,' in html
    assert "http" not in html.split("</style>", 1)[1]  # nothing to fetch


def test_the_fonts_are_embedded() -> None:
    html = export_pdf.customer_html(doc(ONE), None)
    assert html.count("@font-face") == len(export_pdf.FONT_FACES)
    assert "url(data:font/woff2;base64," in html


def test_money_quantity_and_rate_are_written_as_the_screen_does() -> None:
    assert export.shekels(D("4674.0000")) == "₪4,674"
    assert export.shekels(D("24.575")) == "₪24.58"
    assert export.shekels(D("-35.7")) == "-₪35.70"
    assert export.shekels(None) == ""
    assert (export.quantity(D("17.000")), export.quantity(D("2.500")), export.quantity(D("100"))) == (
        "17",
        "2.5",
        "100",
    )
    assert (export.percent(D("0.18")), export.percent(D("0.075")), export.percent(None)) == ("18%", "7.5%", "")


def test_the_file_names() -> None:
    d = doc(ONE)
    assert export.file_name(d, "pdf") == "הצעת מחיר NURSERY גרסה 2.pdf"
    assert export.file_name(d, "xlsx") == "הצעה פנימית NURSERY גרסה 2.xlsx"
    odd = export.Document(**{**d.__dict__, "name": 'a/b:c*"'})
    assert export.file_name(odd, "pdf") == "הצעת מחיר abc גרסה 2.pdf"
