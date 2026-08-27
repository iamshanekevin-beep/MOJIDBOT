"""
Dashboard + log viewer for the IQ Option trading bot.
Serves a metrics dashboard with charts on port 3000, plus JSON APIs.
Uses only the standard library + Chart.js (from CDN in the browser).
"""
import http.server
import json
import os

LOG_FILE = os.environ.get("BOT_LOG_FILE", "/logs/bot.log")
METRICS_FILE = os.environ.get("BOT_METRICS_FILE", "/logs/metrics.json")
MAX_LOG_BYTES = 100_000

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IQ Option Bot — Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:#0f0f23; color:#e0e0e0; font-family:'Segoe UI',system-ui,sans-serif; padding:20px; max-width:1200px; margin:0 auto; }
  .header { display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; }
  .header h1 { font-size:22px; color:#4CAF50; }
  .status-badge { display:flex; align-items:center; gap:8px; font-size:14px; }
  .dot { width:10px; height:10px; border-radius:50%; }
  .dot.connected { background:#4CAF50; box-shadow:0 0 8px #4CAF50; }
  .dot.connecting { background:#ffd93d; }
  .dot.error { background:#ff6b6b; }
  .dot.starting { background:#888; }
  .config-bar { display:flex; gap:10px; flex-wrap:wrap; margin-bottom:20px; font-size:13px; }
  .config-bar span { background:#1a1a2e; padding:6px 12px; border-radius:6px; border:1px solid #2a2a4a; }
  .config-bar b { color:#4CAF50; }
  .cards { display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:20px; }
  .card { background:#1a1a2e; border:1px solid #2a2a4a; border-radius:12px; padding:20px; }
  .card .label { font-size:11px; color:#888; text-transform:uppercase; letter-spacing:1px; margin-bottom:8px; }
  .card .value { font-size:28px; font-weight:700; }
  .green { color:#4CAF50; } .red { color:#ff6b6b; } .blue { color:#61dafb; } .yellow { color:#ffd93d; }
  .charts { display:grid; grid-template-columns:2fr 1fr; gap:16px; margin-bottom:20px; }
  .chart-box { background:#1a1a2e; border:1px solid #2a2a4a; border-radius:12px; padding:20px; }
  .chart-box h3 { font-size:13px; color:#888; margin-bottom:12px; }
  .info-row { display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:20px; }
  .info-box { background:#1a1a2e; border:1px solid #2a2a4a; border-radius:12px; padding:16px; }
  .info-box h3 { font-size:13px; color:#888; margin-bottom:8px; }
  .info-box .detail { font-size:12px; line-height:1.7; font-family:monospace; white-space:pre-wrap; }
  .logs-section { background:#1a1a2e; border:1px solid #2a2a4a; border-radius:12px; padding:20px; }
  .logs-section h3 { font-size:13px; color:#888; margin-bottom:12px; }
  #logs { background:#0f0f23; border:1px solid #2a2a4a; border-radius:8px; padding:12px; font-family:monospace; font-size:12px; max-height:300px; overflow-y:auto; white-space:pre-wrap; word-wrap:break-word; line-height:1.5; }
  @media(max-width:768px) { .cards,.charts,.info-row { grid-template-columns:1fr; } }
</style>
</head>
<body>
  <div class="header">
    <h1>🤖 IQ Option Trading Bot</h1>
    <div class="status-badge">
      <div class="dot starting" id="status-dot"></div>
      <span id="status-text">Starting...</span>
    </div>
  </div>

  <div class="config-bar">
    <span>Pair: <b id="cfg-pair">—</b></span>
    <span>Strategy: <b id="cfg-strategy">—</b></span>
    <span>Auto Trade: <b id="cfg-autotrade">—</b></span>
    <span>Account: <b id="cfg-account">—</b></span>
    <span>Trades Today: <b id="cfg-trades-today">0</b>/<span id="cfg-max-trades">—</span></span>
    <span>Cons. Losses: <b id="cfg-cons-losses">0</b>/<span id="cfg-max-losses">—</span></span>
  </div>

  <div class="cards">
    <div class="card"><div class="label">Total Tasks</div><div class="value blue" id="m-cycles">0</div></div>
    <div class="card"><div class="label">Trades Placed</div><div class="value yellow" id="m-trades">0</div></div>
    <div class="card"><div class="label">Win Rate</div><div class="value green" id="m-winrate">—</div></div>
    <div class="card"><div class="label">Daily P&L</div><div class="value" id="m-pnl">0.00</div></div>
  </div>

  <div class="charts">
    <div class="chart-box"><h3>Signal History (Cumulative)</h3><canvas id="signalChart" height="100"></canvas></div>
    <div class="chart-box"><h3>Trade Results</h3><canvas id="resultChart" height="100"></canvas></div>
  </div>

  <div class="info-row">
    <div class="info-box"><h3>Last Signal</h3><div class="detail" id="last-signal">No signals yet</div></div>
    <div class="info-box"><h3>Last Trade</h3><div class="detail" id="last-trade">No trades yet</div></div>
  </div>

  <div class="logs-section"><h3>Live Logs</h3><pre id="logs">Loading...</pre></div>

<script>
let signalChart, resultChart;

function initCharts() {
  signalChart = new Chart(document.getElementById('signalChart'), {
    type: 'line',
    data: { labels: [], datasets: [
      { label: 'CALL', data: [], borderColor: '#4CAF50', backgroundColor: 'rgba(76,175,80,0.1)', fill: true, tension: 0.3 },
      { label: 'PUT',  data: [], borderColor: '#ff6b6b', backgroundColor: 'rgba(255,107,107,0.1)', fill: true, tension: 0.3 }
    ]},
    options: { responsive: true,
      plugins: { legend: { labels: { color: '#888' } } },
      scales: {
        x: { ticks: { color: '#555', maxTicksLimit: 8 }, grid: { color: '#1a1a2e' } },
        y: { ticks: { color: '#555' }, grid: { color: '#1a1a2e' }, beginAtZero: true }
      }
    }
  });
  resultChart = new Chart(document.getElementById('resultChart'), {
    type: 'doughnut',
    data: { labels: ['Wins','Losses','Unknown'], datasets: [{ data: [0,0,0], backgroundColor: ['#4CAF50','#ff6b6b','#555'], borderWidth: 0 }] },
    options: { responsive: true, plugins: { legend: { labels: { color: '#888' } } } }
  });
}

function fmt(v) { return typeof v === 'number' ? v.toFixed(5) : v; }

function updateMetrics(d) {
  document.getElementById('status-dot').className = 'dot ' + (d.status || 'starting');
  document.getElementById('status-text').textContent = (d.status || 'unknown').charAt(0).toUpperCase() + (d.status || 'unknown').slice(1);
  document.getElementById('cfg-pair').textContent = d.pair || '—';
  document.getElementById('cfg-strategy').textContent = d.strategy || '—';
  document.getElementById('cfg-autotrade').textContent = d.auto_trade ? 'ON' : 'OFF';
  document.getElementById('cfg-account').textContent = d.account_type || '—';
  document.getElementById('cfg-trades-today').textContent = d.trades_today || 0;
  document.getElementById('cfg-max-trades').textContent = d.max_trades_per_day || '—';
  document.getElementById('cfg-cons-losses').textContent = d.consecutive_losses || 0;
  document.getElementById('cfg-max-losses').textContent = d.max_consecutive_losses || '—';

  document.getElementById('m-cycles').textContent = d.total_cycles || 0;
  document.getElementById('m-trades').textContent = d.trades_placed || 0;
  const w = d.wins||0, l = d.losses||0, dec = w+l;
  document.getElementById('m-winrate').textContent = dec > 0 ? ((w/dec)*100).toFixed(1)+'%' : '—';
  const pnl = d.pnl_today || 0;
  const pnlEl = document.getElementById('m-pnl');
  pnlEl.textContent = (pnl >= 0 ? '+' : '') + pnl.toFixed(2);
  pnlEl.className = 'value ' + (pnl > 0 ? 'green' : pnl < 0 ? 'red' : '');

  if (d.last_signal) {
    const ls = d.last_signal;
    let detail = 'Direction: ' + ls.direction + '\nTime: ' + (ls.timestamp || '—');
    if (ls.info) for (const [k,v] of Object.entries(ls.info)) {
      if (typeof v === 'object') { detail += '\n' + k + ':'; for (const [k2,v2] of Object.entries(v)) detail += '\n  ' + k2 + ': ' + fmt(v2); }
      else detail += '\n' + k + ': ' + fmt(v);
    }
    document.getElementById('last-signal').textContent = detail;
  }
  if (d.last_trade) {
    const lt = d.last_trade;
    document.getElementById('last-trade').textContent =
      'Direction: ' + lt.direction + '\nAmount: ' + lt.amount + '\nOrder ID: ' + lt.order_id + '\nSuccess: ' + lt.success + '\nTime: ' + (lt.timestamp || '—');
  }

  if (d.signal_history && d.signal_history.length > 0) {
    let cc=0, pc=0; const labels=[], cd=[], pd=[];
    for (const s of d.signal_history) {
      if (s.direction==='CALL') cc++; else if (s.direction==='PUT') pc++;
      labels.push(new Date(s.ts).toLocaleTimeString());
      cd.push(cc); pd.push(pc);
    }
    signalChart.data.labels = labels;
    signalChart.data.datasets[0].data = cd;
    signalChart.data.datasets[1].data = pd;
    signalChart.update('none');
  }
  resultChart.data.datasets[0].data = [d.wins||0, d.losses||0, d.unknown_results||0];
  resultChart.update('none');
}

async function fetchMetrics() {
  try { const r = await fetch('/api/metrics'); updateMetrics(await r.json()); } catch(e) {}
}
async function fetchLogs() {
  try {
    const r = await fetch('/api/logs');
    const t = await r.text();
    const el = document.getElementById('logs');
    el.textContent = t;
    el.scrollTop = el.scrollHeight;
  } catch(e) {}
}

initCharts();
fetchMetrics(); fetchLogs();
setInterval(fetchMetrics, 3000);
setInterval(fetchLogs, 3000);
</script>
</body>
</html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/metrics":
            self._serve_metrics()
        elif self.path == "/api/logs":
            self._serve_logs()
        else:
            self._serve_dashboard()

    def _serve_dashboard(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(DASHBOARD_HTML.encode())

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

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    server = http.server.HTTPServer(("0.0.0.0", 3000), Handler)
    print(f"Dashboard serving on http://0.0.0.0:3000")
    server.serve_forever()
