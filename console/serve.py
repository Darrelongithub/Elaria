#!/usr/bin/env python3
"""Static server for the Elaria console shell.

Sends no-store so the browser can never show a stale copy of index.html —
that already bit us once mid-design-review.
"""
import http.server
import socketserver


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, fmt, *args):  # keep the log quiet
        pass


if __name__ == "__main__":
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", 8123), NoCacheHandler) as httpd:
        print("serving console on 0.0.0.0:8123 (no-store)")
        httpd.serve_forever()
