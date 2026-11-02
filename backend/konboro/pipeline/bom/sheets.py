"""Spreadsheets, read in code (01 §4.2, §5.8): an Excel workbook (one page per worksheet) or a CSV file (one page).

Cells come out as text, as a person reads them: whole numbers without ".0", dates as ISO dates, formulas as the value
Excel saved with them (openpyxl's `data_only`; a file never opened in Excel after a formula changed has none). Empty
cells are None, and trailing empty cells and rows are dropped.
"""

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal

from openpyxl import load_workbook

CSV_ENCODINGS = ("utf-8-sig", "cp1255")  # cp1255: Hebrew Excel's "CSV" export
CSV_DELIMITERS = ",;\t"

Cells = list[str | None]


@dataclass
class Sheet:
    name: str | None
    rows: list[Cells]  # rows[i] is the sheet's row i + 1


class UnreadableSheetError(Exception):
    pass


def text(value: object) -> str | None:
    """One cell as text, or None when it is empty."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        d = Decimal(repr(value))
        return format(d.quantize(Decimal(1)) if d == d.to_integral_value() else d.normalize(), "f")
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == time(0) else value.isoformat(sep=" ")
    if isinstance(value, date | time):
        return value.isoformat()
    s = " ".join(str(value).split())
    return s or None


def _trim(rows: list[Cells]) -> list[Cells]:
    out = []
    for r in rows:
        while r and r[-1] is None:
            r = r[:-1]
        out.append(r)
    while out and not out[-1]:
        out.pop()
    return out


def read_xlsx(data: bytes) -> list[Sheet]:
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:  # openpyxl raises many kinds for a broken file
        raise UnreadableSheetError(str(e)) from e
    try:
        return [
            Sheet(ws.title, _trim([[text(v) for v in row] for row in ws.iter_rows(values_only=True)]))
            for ws in wb.worksheets
        ]
    finally:
        wb.close()


def decode(data: bytes) -> str:
    for encoding in CSV_ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise UnreadableSheetError("not UTF-8 or cp1255")


def read_csv(data: bytes) -> list[Sheet]:
    body = decode(data)
    first = next((line for line in body.splitlines() if line.strip()), "")
    delimiter = max(CSV_DELIMITERS, key=first.count) if first else ","
    rows = [[text(c) for c in r] for r in csv.reader(io.StringIO(body), delimiter=delimiter)]
    return [Sheet(None, _trim(rows))]


def read(fmt: str, data: bytes) -> list[Sheet]:
    if fmt == "xlsx":
        return read_xlsx(data)
    if fmt == "csv":
        return read_csv(data)
    raise ValueError(f"{fmt} is not a spreadsheet")
