"""
Minimal HTTP log viewer so the headless trading bot's output is visible
in the Base44 preview (port 3000). Uses only the standard library — no
extra dependencies. Does NOT touch any trading logic.
"""
import http.server
import html
import os

LOG_FILE = os.environ.get("BOT_LOG_FILE", "/logs/bot.log")
MAX_BYTES = 100_000


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        try:
            with open(LOG_FILE, "r", errors="replace") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - MAX_BYTES))
                content = f.read()
        except FileNotFoundError:
            content = "(No logs yet — the bot is starting up...)"
        escaped = html.escape(content)
        body = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="3">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IQ Option Bot — Live Logs</title>
<style>
  body {{ background:#1a1a2e; color:#c5c6c7; font-family:'Courier New',monospace; margin:0; padding:24px; }}
  h1 {{ color:#4CAF50; font-size:18px; margin:0 0 16px; }}
  .bar {{ color:#888; font-size:13px; margin-bottom:16px; }}
  pre {{ white-space:pre-wrap; word-wrap:break-word; font-size:13px; line-height:1.5; }}
  .err {{ color:#ff6b6b; }}
  .ok {{ color:#4CAF50; }}
  .warn {{ color:#ffd93d; }}
</style>
</head>
<body>
<h1>🤖 IQ Option Trading Bot — Live Logs</h1>
<div class="bar">Auto-refresh every 3s &middot; showing last {MAX_BYTES // 1000}KB</div>
<pre>{escaped}</pre>
</body>
</html>"""
        self.wfile.write(body.encode())

    def log_message(self, *args):
        pass  # silence default request logging


if __name__ == "__main__":
    server = http.server.HTTPServer(("0.0.0.0", 3000), Handler)
    print(f"Log viewer serving on http://0.0.0.0:3000 (tailing {LOG_FILE})")
    server.serve_forever()
