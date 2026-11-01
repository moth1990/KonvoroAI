"""PDFium is not thread-safe (BUG-010). The API checks uploads in its thread pool while the worker thread renders
pages in the same process, so every PDFium call goes through one lock (konboro.services.pdf). Without it, two
uploads at once crashed or hung the API."""

import re
import subprocess
import sys
import textwrap
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
NURSERY = BACKEND.parent / "golden" / "NURSERY-1" / "NURSERY-1.pdf"

# Upload checks and stage-1 rendering at the same time, from several threads. In a child process: a race inside
# PDFium ends in a segfault or an abort, which would take pytest down with it.
RACE = textwrap.dedent(f"""
    import threading
    from pathlib import Path
    from konboro.pipeline.intake.pages import read_pages, render as render_page
    from konboro.services.intake import count_pages

    data = Path({str(NURSERY)!r}).read_bytes()
    finished = []

    def check() -> None:
        for _ in range(15):
            assert count_pages("pdf", data).pages == 9
        finished.append("check")

    def render() -> None:
        for _ in range(3):
            pages = read_pages("fil", "pdf", data)
            assert len(pages) == 9
            render_page(pages[4], data, 300)
        finished.append("render")

    threads = [threading.Thread(target=f, daemon=True) for f in (check, render) * 3]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    print("finished", len(finished))
""")


def test_pdfium_is_safe_across_threads() -> None:
    result = subprocess.run(  # noqa: S603  (our own interpreter and our own script)
        [sys.executable, "-c", RACE], cwd=BACKEND, capture_output=True, text=True, timeout=120, check=False
    )
    assert (result.returncode, result.stdout.strip()) == (0, "finished 6"), result.stderr[-2000:]


def test_only_the_pdf_service_imports_pypdfium2() -> None:
    """Every call has to take the lock, so nothing else may reach PDFium directly."""
    offenders = [
        str(path.relative_to(BACKEND))
        for path in (BACKEND / "konboro").rglob("*.py")
        if path.name != "pdf.py" and re.search(r"^\s*(import|from)\s+pypdfium2", path.read_text(), re.M)
    ]
    assert offenders == []
