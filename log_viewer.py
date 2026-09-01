"""
Dashboard + log viewer for the IQ Option trading bot.
Serves the premium dashboard (dashboard.html) and API endpoints on port 3000.
"""
import http.server
import json
import os

LOG_FILE = os.environ.get("BOT_LOG_FILE", "/logs/bot.log")
METRICS_FILE = os.environ.get("BOT_METRICS_FILE", "/logs/metrics.json")
CONTROL_FILE = os.environ.get("BOT_CONTROL_FILE", "/logs/control.json")
FORCE_SCAN_FILE = os.environ.get("BOT_FORCE_SCAN_FILE", "/logs/force_scan.flag")
DASHBOARD_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")
MAX_LOG_BYTES = 100_000


class Handler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path == "/api/metrics":
            self._serve_metrics()
        elif self.path == "/api/logs":
            self._serve_logs()
        else:
            self._serve_dashboard()

    def do_POST(self):
        if self.path == "/api/control":
            self._handle_control()
        elif self.path == "/api/force-scan":
            self._handle_force_scan()
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_dashboard(self):
        try:
            with open(DASHBOARD_FILE, "r") as f:
                html = f.read()
        except FileNotFoundError:
            html = "<h1>dashboard.html not found</h1>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def _serve_metrics(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            with open(METRICS_FILE, "r") as f:
                self.wfile.write(f.read().encode())
        except FileNotFoundError:
            self.wfile.write(b"{}")

    def _serve_logs(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        try:
            with open(LOG_FILE, "r", errors="replace") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - MAX_LOG_BYTES))
                self.wfile.write(f.read().encode())
        except FileNotFoundError:
            self.wfile.write(b"(No logs yet)")

    def _handle_control(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        try:
            data = json.loads(body)
            data["_ts"] = data.get("_ts", 0)
            with open(CONTROL_FILE, "w") as f:
                json.dump(data, f, indent=2)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
        except Exception:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"bad request"}')

    def _handle_force_scan(self):
        try:
            with open(FORCE_SCAN_FILE, "w") as f:
                f.write("1")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
        except Exception:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'{"error":"cannot write flag"}')

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    server = http.server.HTTPServer(("0.0.0.0", 3000), Handler)
    print("Dashboard serving on http://0.0.0.0:3000")
    server.serve_forever()
