"""
Dashboard + log viewer for the IQ Option trading bot.
Serves a metrics dashboard with charts and bot controls on port 3000.
Uses only the standard library + Chart.js (from CDN in the browser).
"""
import http.server
import json
import os

LOG_FILE = os.environ.get("BOT_LOG_FILE", "/logs/bot.log")
METRICS_FILE = os.environ.get("BOT_METRICS_FILE", "/logs/metrics.json")
CONTROL_FILE = os.environ.get("BOT_CONTROL_FILE", "/logs/control.json")
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
  .header { display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; flex-wrap:wrap; gap:10px; }
  .header h1 { font-size:22px; color:#4CAF50; }
  .header-right { display:flex; align-items:center; gap:12px; }
  .status-badge { display:flex; align-items:center; gap:8px; font-size:14px; }
  .dot { width:10px; height:10px; border-radius:50%; }
  .dot.connected { background:#4CAF50; box-shadow:0 0 8px #4CAF50; }
  .dot.connecting { background:#ffd93d; }
  .dot.error { background:#ff6b6b; }
  .dot.starting { background:#888; }
  .dot.paused { background:#ffd93d; }
  .badge { font-size:11px; padding:3px 8px; border-radius:6px; font-weight:600; }
  .badge-cooldown { background:#ff6b6b22; color:#ff6b6b; border:1px solid #ff6b6b44; }
  .badge-pending { background:#61dafb22; color:#61dafb; border:1px solid #61dafb44; }
  .controls { background:#1a1a2e; border:1px solid #2a2a4a; border-radius:12px; padding:16px; margin-bottom:16px; }
  .control-row { display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
  .btn { padding:8px 16px; border:none; border-radius:8px; font-size:14px; font-weight:600; cursor:pointer; transition:all .15s; }
  .btn-pause { background:#ff6b6b; color:#fff; }
  .btn-resume { background:#4CAF50; color:#fff; }
  .btn-small { padding:5px 10px; font-size:12px; background:#2a2a4a; color:#e0e0e0; }
  .btn-small:hover { background:#3a3a5a; }
  .pair-list { display:flex; gap:8px; flex-wrap:wrap; margin-top:8px; }
  .pair-tag { background:#2a2a4a; padding:4px 10px; border-radius:6px; font-size:13px; display:flex; align-items:center; gap:6px; }
  .pair-tag .x { cursor:pointer; color:#ff6b6b; font-weight:bold; }
  .pair-input { background:#0f0f23; border:1px solid #2a2a4a; color:#e0e0e0; padding:5px 10px; border-radius:6px; font-size:13px; width:140px; }
  .config-bar { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:16px; font-size:13px; }
  .config-bar span { background:#1a1a2e; padding:6px 12px; border-radius:6px; border:1px solid #2a2a4a; }
  .config-bar b { color:#4CAF50; }
  .cards { display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:16px; }
  .card { background:#1a1a2e; border:1px solid #2a2a4a; border-radius:12px; padding:20px; }
  .card .label { font-size:11px; color:#888; text-transform:uppercase; letter-spacing:1px; margin-bottom:8px; }
  .card .value { font-size:28px; font-weight:700; }
  .green { color:#4CAF50; } .red { color:#ff6b6b; } .blue { color:#61dafb; } .yellow { color:#ffd93d; }
  .charts { display:grid; grid-template-columns:2fr 1fr; gap:16px; margin-bottom:16px; }
  .chart-box { background:#1a1a2e; border:1px solid #2a2a4a; border-radius:12px; padding:20px; }
  .chart-box h3 { font-size:13px; color:#888; margin-bottom:12px; }
  .pair-stats { background:#1a1a2e; border:1px solid #2a2a4a; border-radius:12px; padding:16px; margin-bottom:16px; }
  .pair-stats h3 { font-size:13px; color:#888; margin-bottom:10px; }
  .pair-stats table { width:100%; border-collapse:collapse; font-size:13px; }
  .pair-stats th { text-align:left; color:#888; padding:6px 8px; border-bottom:1px solid #2a2a4a; }
  .pair-stats td { padding:6px 8px; border-bottom:1px solid #1e1e38; }
  .info-row { display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:16px; }
  .info-box { background:#1a1a2e; border:1px solid #2a2a4a; border-radius:12px; padding:16px; }
  .info-box h3 { font-size:13px; color:#888; margin-bottom:8px; }
  .info-box .detail { font-size:12px; line-height:1.7; font-family:monospace; white-space:pre-wrap; }
  .logs-section { background:#1a1a2e; border:1px solid #2a2a4a; border-radius:12px; padding:16px; }
  .logs-section h3 { font-size:13px; color:#888; margin-bottom:10px; }
  #logs { background:#0f0f23; border:1px solid #2a2a4a; border-radius:8px; padding:12px; font-family:monospace; font-size:12px; max-height:250px; overflow-y:auto; white-space:pre-wrap; word-wrap:break-word; line-height:1.5; }
  @media(max-width:768px) { .cards,.charts,.info-row { grid-template-columns:1fr; } }
</style>
</head>
<body>
  <div class="header">
    <h1>🤖 IQ Option Trading Bot</h1>
    <div class="header-right">
      <div class="status-badge">
        <div class="dot starting" id="status-dot"></div>
        <span id="status-text">Starting...</span>
      </div>
      <span id="cooldown-badge" class="badge badge-cooldown" style="display:none">⚠ Cooldown</span>
      <span id="pending-badge" class="badge badge-pending" style="display:none">Pending: 0</span>
    </div>
  </div>

  <!-- Control panel -->
  <div class="controls">
    <div class="control-row">
      <button id="btn-toggle" class="btn btn-pause">⏸ Pause Bot</button>
      <span style="color:#888;font-size:13px">24/7 mode · 1h trend → 1m entry · no daily limit</span>
    </div>
    <div class="control-row" style="margin-top:10px">
      <span style="color:#888;font-size:13px">Pairs:</span>
      <div id="pair-list" class="pair-list"></div>
      <input type="text" id="new-pair" placeholder="e.g. GBPUSD-OTC" class="pair-input">
      <button id="btn-add-pair" class="btn btn-small">+ Add</button>
    </div>
  </div>

  <div class="config-bar">
    <span>Strategy: <b id="cfg-strategy">—</b></span>
    <span>Auto Trade: <b id="cfg-autotrade">—</b></span>
    <span>Account: <b id="cfg-account">—</b></span>
    <span>Cons. Losses: <b id="cfg-cons-losses">0</b>/<span id="cfg-max-losses">—</span></span>
  </div>

  <div class="cards">
    <div class="card"><div class="label">Total Tasks</div><div class="value blue" id="m-cycles">0</div></div>
    <div class="card"><div class="label">Trades Placed</div><div class="value yellow" id="m-trades">0</div></div>
    <div class="card"><div class="label">Win Rate</div><div class="value green" id="m-winrate">—</div></div>
    <div class="card"><div class="label">Total P&L</div><div class="value" id="m-pnl">0.00</div></div>
  </div>

  <div class="charts">
    <div class="chart-box"><h3>Signal History (Cumulative)</h3><canvas id="signalChart" height="100"></canvas></div>
    <div class="chart-box"><h3>Trade Results</h3><canvas id="resultChart" height="100"></canvas></div>
  </div>

  <div class="pair-stats">
    <h3>Per-Pair Stats</h3>
    <table><thead><tr><th>Pair</th><th>Signals</th><th>Trades</th><th>Wins</th><th>Losses</th></tr></thead>
      <tbody id="pair-stats-body"><tr><td colspan="5" style="color:#555">No data yet</td></tr></tbody>
    </table>
  </div>

  <div class="info-row">
    <div class="info-box"><h3>Last Signal</h3><div class="detail" id="last-signal">No signals yet</div></div>
    <div class="info-box"><h3>Last Trade</h3><div class="detail" id="last-trade">No trades yet</div></div>
  </div>

  <div class="logs-section"><h3>Live Logs</h3><pre id="logs">Loading...</pre></div>

<script>
let signalChart, resultChart;
let currentPairs = [];
let currentRunning = true;

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
  // Status
  const dotEl = document.getElementById('status-dot');
  const stTxt = document.getElementById('status-text');
  const stVal = d.status || 'starting';
  dotEl.className = 'dot ' + stVal;
  stTxt.textContent = stVal.charAt(0).toUpperCase() + stVal.slice(1);

  // Cooldown & pending badges
  const cdBadge = document.getElementById('cooldown-badge');
  cdBadge.style.display = d.cooldown ? '' : 'none';
  const pBadge = document.getElementById('pending-badge');
  if (d.pending_trades > 0) { pBadge.style.display = ''; pBadge.textContent = 'Pending: ' + d.pending_trades; }
  else pBadge.style.display = 'none';

  // Config
  document.getElementById('cfg-strategy').textContent = d.strategy || '—';
  document.getElementById('cfg-autotrade').textContent = d.auto_trade ? 'ON' : 'OFF';
  document.getElementById('cfg-account').textContent = d.account_type || '—';
  document.getElementById('cfg-cons-losses').textContent = d.consecutive_losses || 0;
  document.getElementById('cfg-max-losses').textContent = d.max_consecutive_losses || '—';

  // Cards
  document.getElementById('m-cycles').textContent = d.total_cycles || 0;
  document.getElementById('m-trades').textContent = d.trades_placed || 0;
  const w = d.wins||0, l = d.losses||0, dec = w+l;
  document.getElementById('m-winrate').textContent = dec > 0 ? ((w/dec)*100).toFixed(1)+'%' : '—';
  const pnl = d.pnl_total || 0;
  const pnlEl = document.getElementById('m-pnl');
  pnlEl.textContent = (pnl >= 0 ? '+' : '') + pnl.toFixed(2);
  pnlEl.className = 'value ' + (pnl > 0 ? 'green' : pnl < 0 ? 'red' : '');

  // Toggle button
  currentRunning = d.running !== false;
  const btn = document.getElementById('btn-toggle');
  if (currentRunning) { btn.textContent = '⏸ Pause Bot'; btn.className = 'btn btn-pause'; }
  else { btn.textContent = '▶ Resume Bot'; btn.className = 'btn btn-resume'; }

  // Pairs
  currentPairs = d.pairs || [];
  renderPairs();

  // Last signal
  if (d.last_signal) {
    const ls = d.last_signal;
    let detail = 'Direction: ' + ls.direction + '\nPair: ' + (ls.pair||'—') + '\nTime: ' + (ls.timestamp || '—');
    if (ls.info) for (const [k,v] of Object.entries(ls.info)) {
      if (typeof v === 'object') { detail += '\n' + k + ':'; for (const [k2,v2] of Object.entries(v)) detail += '\n  ' + k2 + ': ' + fmt(v2); }
      else detail += '\n' + k + ': ' + fmt(v);
    }
    document.getElementById('last-signal').textContent = detail;
  }

  // Last trade
  if (d.last_trade) {
    const lt = d.last_trade;
    document.getElementById('last-trade').textContent =
      'Direction: ' + lt.direction + '\nPair: ' + (lt.pair||'—') + '\nAmount: ' + lt.amount + '\nOrder ID: ' + lt.order_id + '\nSuccess: ' + lt.success + '\nTime: ' + (lt.timestamp || '—');
  }

  // Per-pair stats
  if (d.pair_stats && Object.keys(d.pair_stats).length > 0) {
    let rows = '';
    for (const [pair, s] of Object.entries(d.pair_stats)) {
      rows += '<tr><td>' + pair + '</td><td>' + (s.signals||0) + '</td><td>' + (s.trades||0) + '</td><td>' + (s.wins||0) + '</td><td>' + (s.losses||0) + '</td></tr>';
    }
    document.getElementById('pair-stats-body').innerHTML = rows;
  }

  // Signal chart
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

  // Result chart
  resultChart.data.datasets[0].data = [d.wins||0, d.losses||0, d.unknown_results||0];
  resultChart.update('none');
}

function renderPairs() {
  const el = document.getElementById('pair-list');
  el.innerHTML = currentPairs.map(function(p) {
    return '<span class="pair-tag">' + p + ' <span class="x" data-pair="' + p + '">×</span></span>';
  }).join('');
  el.querySelectorAll('.x').forEach(function(x) {
    x.onclick = function() {
      var pair = this.getAttribute('data-pair');
      currentPairs = currentPairs.filter(function(p) { return p !== pair; });
      sendControl();
    };
  });
}

async function sendControl() {
  try {
    await fetch('/api/control', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ running: currentRunning, pairs: currentPairs })
    });
    fetchMetrics();
  } catch(e) { console.error('control send failed', e); }
}

document.getElementById('btn-toggle').onclick = function() {
  currentRunning = !currentRunning;
  sendControl();
};

document.getElementById('btn-add-pair').onclick = function() {
  var input = document.getElementById('new-pair');
  var pair = input.value.trim().toUpperCase();
  if (pair && currentPairs.indexOf(pair) === -1) {
    currentPairs.push(pair);
    input.value = '';
    sendControl();
  }
};

document.getElementById('new-pair').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') document.getElementById('btn-add-pair').click();
});

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

    def do_POST(self):
        if self.path == "/api/control":
            self._handle_control()
        else:
            self.send_response(404)
            self.end_headers()

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

    def _handle_control(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        try:
            data = json.loads(body)
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

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    server = http.server.HTTPServer(("0.0.0.0", 3000), Handler)
    print("Dashboard serving on http://0.0.0.0:3000")
    server.serve_forever()
