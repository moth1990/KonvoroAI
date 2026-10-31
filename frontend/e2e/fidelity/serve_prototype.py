"""Serve prototype/ for the fidelity capture, as UTF-8 (the file has no charset meta, and http.server sends none)."""

import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class Utf8Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".html": "text/html; charset=utf-8"}

    def log_message(self, format: str, *args: object) -> None:  # quiet: Playwright prints server output
        pass


if __name__ == "__main__":
    port, root = int(sys.argv[1]), sys.argv[2]
    ThreadingHTTPServer(("127.0.0.1", port), partial(Utf8Handler, directory=root)).serve_forever()
