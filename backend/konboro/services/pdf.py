"""PDFium (pypdfium2), behind one lock per process (BUG-010).

PDFium is not thread-safe: two threads may not call it at the same time, not even on different documents
(pypdfium2's documentation). The API checks uploads in its thread pool, and in `make dev` and E2E the pipeline
worker renders pages in the same process, so every call goes through `document()`. Without the lock, two uploads at
once crashed or hung the API. Nothing else imports pypdfium2 (tests/unit/test_pdf_threads.py); `raw` re-exports its
C API for code that reads page objects (pipeline/intake/pages.py).
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager

import pypdfium2 as pdfium
from pypdfium2 import raw  # PDFium's C API, for what the helpers don't wrap; call it only inside `document()`

__all__ = ["PdfiumError", "document", "raw"]

PdfiumError = pdfium.PdfiumError

_lock = threading.RLock()


@contextmanager
def document(data: bytes) -> Iterator[pdfium.PdfDocument]:
    """An open PDF, used and closed while this thread holds the PDFium lock. Bitmaps and pages taken from it must
    not outlive the block: copy what you need (e.g. `to_pil().copy()`) before it ends."""
    with _lock:
        pdf = pdfium.PdfDocument(data)
        try:
            yield pdf
        finally:
            pdf.close()
