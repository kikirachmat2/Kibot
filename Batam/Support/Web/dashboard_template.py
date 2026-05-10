DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>KiBot</title>
    <link rel="icon" href="/static/kibot.png" type="image/png">
    <link
        href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;700&display=swap"
        rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/lucide-static@0.321.0/lib/index.min.js"></script>
    <style>
        :root {
            --bg: #0b0e14;
            --surface: #151921;
            --surface-light: #1e232d;
            --primary: #00d2ff;
            --secondary: #9d50bb;
            --success: #00c853;
            --danger: #ff1744;
            --warning: #ff9100;
            --text: #e1e1e1;
            --text-dim: #94a3b8;
            --border: rgba(255, 255, 255, 0.05);
            --glass: rgba(255, 255, 255, 0.02);
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            background-color: var(--bg);
            color: var(--text);
            font-family: 'Inter', sans-serif;
            height: 100vh;
            display: grid;
            grid-template-columns: 260px 1fr;
            grid-template-rows: 64px 1fr;
            overflow: hidden;
        }

        /* --- TOPBAR --- */
        nav {
            grid-column: 1 / -1;
            background: var(--surface);
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 1.5rem;
            z-index: 50;
        }

        .brand {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .brand-logo {
            width: 32px;
            height: 32px;
            background: url('/static/kibot.png') no-repeat center;
            background-size: contain;
            border-radius: 8px;
        }

        .brand-name {
            font-weight: 700;
            font-size: 1.1rem;
            letter-spacing: 1px;
            color: #fff;
        }

        .view-switcher {
            display: flex;
            background: var(--bg);
            padding: 4px;
            border-radius: 10px;
            border: 1px solid var(--border);
        }

        .view-btn {
            padding: 6px 16px;
            border-radius: 8px;
            border: none;
            background: transparent;
            color: var(--text-dim);
            font-size: 0.8rem;
            font-weight: 600;
            cursor: pointer;
            transition: 0.2s;
        }

        .view-btn.active {
            background: var(--surface-light);
            color: #fff;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        }

        .global-stats {
            display: flex;
            gap: 2rem;
        }

        .stat-item {
            text-align: right;
        }

        .stat-label {
            font-size: 0.65rem;
            color: var(--text-dim);
            text-transform: uppercase;
            display: block;
            margin-bottom: 2px;
        }

        .stat-value {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.9rem;
            font-weight: 600;
        }

        /* --- SIDEBAR --- */
        aside {
            background: var(--surface);
            border-right: 1px solid var(--border);
            padding: 1.5rem;
            display: flex;
            flex-direction: column;
            gap: 2rem;
            overflow-y: auto;
        }

        .sidebar-section h3 {
            font-size: 0.7rem;
            text-transform: uppercase;
            color: var(--text-dim);
            letter-spacing: 1.5px;
            margin-bottom: 1rem;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .node-card {
            background: var(--glass);
            border: 1px solid var(--border);
            padding: 12px;
            border-radius: 12px;
            margin-bottom: 8px;
        }

        .node-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }

        .node-name {
            font-size: 0.8rem;
            font-weight: 600;
        }

        .status-dot {
            width: 6px;
            height: 6px;
            border-radius: 50%;
        }

        .status-dot.online {
            background: var(--success);
            box-shadow: 0 0 8px var(--success);
        }

        .node-bar-container {
            width: 100%;
            height: 4px;
            background: var(--bg);
            border-radius: 2px;
            overflow: hidden;
            margin-top: 4px;
        }

        .node-bar {
            height: 100%;
            background: var(--primary);
            transition: 0.5s;
            width: 0%;
        }

        /* --- MAIN CONTENT --- */
        main {
            padding: 1.5rem;
            overflow-y: auto;
            display: grid;
            grid-template-columns: 1fr 340px;
            grid-template-rows: auto 1fr;
            gap: 1.5rem;
        }

        .hero-section {
            grid-column: 1 / 2;
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 1rem;
        }

        .hero-card {
            background: linear-gradient(135deg, var(--surface), #1a1e26);
            border: 1px solid var(--border);
            padding: 1.5rem;
            border-radius: 20px;
            position: relative;
            overflow: hidden;
        }

        .hero-card::after {
            content: '';
            position: absolute;
            top: -50%;
            right: -50%;
            width: 100%;
            height: 100%;
            background: radial-gradient(circle, var(--primary) 0%, transparent 70%);
            opacity: 0.05;
        }

        .hero-val {
            font-family: 'JetBrains Mono', monospace;
            font-size: 1.5rem;
            font-weight: 700;
            margin-top: 8px;
            display: block;
        }

        .hero-delta {
            font-size: 0.75rem;
            font-weight: 600;
            margin-top: 4px;
        }

        .hero-delta.up {
            color: var(--success);
        }

        .hero-delta.down {
            color: var(--danger);
        }

        .signals-panel {
            grid-column: 1 / 2;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 20px;
            display: flex;
            flex-direction: column;
        }

        .panel-header {
            padding: 1.2rem 1.5rem;
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .panel-title {
            font-weight: 600;
            font-size: 0.9rem;
        }

        .panel-content {
            flex: 1;
            padding: 1rem;
            overflow-y: auto;
        }

        .sig-row {
            display: grid;
            grid-template-columns: 100px 140px 80px 100px 1fr 100px;
            padding: 1rem;
            border-radius: 12px;
            margin-bottom: 8px;
            background: var(--glass);
            align-items: center;
            font-size: 0.85rem;
            border: 1px solid transparent;
            transition: 0.2s;
        }

        .sig-row:hover {
            border-color: var(--primary);
            background: rgba(0, 210, 255, 0.02);
        }

        .sig-pair {
            font-weight: 700;
            color: #fff;
        }

        .sig-score {
            font-weight: 700;
            color: var(--success);
            font-family: 'JetBrains Mono', monospace;
        }

        .sidebar-right {
            grid-column: 2 / 3;
            grid-row: 1 / 3;
            display: flex;
            flex-direction: column;
            gap: 1.5rem;
        }

        .decision-panel {
            flex: 1;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 20px;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        .terminal {
            flex: 1;
            background: #0d1117;
            padding: 1rem;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.7rem;
            color: #7ee787;
            overflow-y: auto;
            line-height: 1.6;
        }

        .term-ts {
            color: #8b949e;
            margin-right: 8px;
        }

        .term-tag {
            color: var(--primary);
            font-weight: 700;
        }

        .holdings-list {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .holding-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 14px;
            background: var(--glass);
            border-radius: 10px;
            border: 1px solid var(--border);
        }

        .holding-name {
            font-weight: 600;
            font-size: 0.85rem;
        }

        .holding-val {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.8rem;
        }

        /* --- UTILS --- */
        .badge {
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.65rem;
            font-weight: 700;
            text-transform: uppercase;
        }

        .badge-primary {
            background: var(--primary);
            color: #000;
        }

        .badge-secondary {
            background: var(--secondary);
            color: #fff;
        }

        @keyframes pulse {
            0% {
                opacity: 1;
            }

            50% {
                opacity: 0.5;
            }

            100% {
                opacity: 1;
            }
        }

        .live-indicator {
            width: 8px;
            height: 8px;
            background: var(--danger);
            border-radius: 50%;
            animation: pulse 1s infinite;
        }
    </style>
</head>

<body>
    <nav>
        <div class="brand">
            <div class="brand-logo"></div>
            <div class="brand-name">KiBot</div>
            <div class="live-indicator"></div>
        </div>

        <div class="view-switcher">
            <button class="view-btn active" id="btn-indodax" onclick="switchView('indodax')">INDODAX</button>
            <button class="view-btn" id="btn-polymarket" onclick="switchView('polymarket')">POLYMARKET</button>
        </div>

        <div class="global-stats">
            <div class="stat-item">
                <span class="stat-label">Market Bias</span>
                <span class="stat-value" id="market-bias" style="color: var(--success)">BULLISH (0.82)</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">BTC Price</span>
                <span class="stat-value" id="btc-price">$0.00</span>
            </div>
        </div>
    </nav>

    <aside>
        <div class="sidebar-section">
            <h3>Infrastructure</h3>
            <div class="node-card">
                <div class="node-header">
                    <span class="node-name">Batam_Hub</span>
                    <span class="status-dot online" id="dot-batam"></span>
                </div>
                <div style="font-size: 0.65rem; color: var(--text-dim); display: flex; justify-content: space-between;">
                    <span>CPU</span><span id="txt-cpu-batam">0%</span>
                </div>
                <div class="node-bar-container">
                    <div class="node-bar" id="bar-cpu-batam"></div>
                </div>
                <div
                    style="font-size: 0.65rem; color: var(--text-dim); display: flex; justify-content: space-between; margin-top: 5px;">
                    <span>RAM</span><span id="txt-ram-batam">0%</span>
                </div>
                <div class="node-bar-container">
                    <div class="node-bar" id="bar-ram-batam" style="background: var(--secondary)"></div>
                </div>
                <div
                    style="font-size: 0.65rem; color: var(--text-dim); display: flex; justify-content: space-between; margin-top: 5px;">
                    <span>DISK</span><span id="txt-disk-batam">0%</span>
                </div>
                <div class="node-bar-container">
                    <div class="node-bar" id="bar-disk-batam" style="background: var(--warning)"></div>
                </div>
            </div>
            <div class="node-card">
                <div class="node-header">
                    <span class="node-name">EXECUTOR_Executor</span>
                    <span class="status-dot" id="dot-EXECUTOR"></span>
                </div>
                <div style="font-size: 0.65rem; color: var(--text-dim); display: flex; justify-content: space-between;">
                    <span>CPU</span><span id="txt-cpu-EXECUTOR">0%</span></div>
                <div class="node-bar-container">
                    <div class="node-bar" id="bar-cpu-EXECUTOR"></div>
                </div>
                <div
                    style="font-size: 0.65rem; color: var(--text-dim); display: flex; justify-content: space-between; margin-top: 5px;">
                    <span>RAM</span><span id="txt-ram-EXECUTOR">0%</span></div>
                <div class="node-bar-container">
                    <div class="node-bar" id="bar-ram-EXECUTOR" style="background: var(--secondary)"></div>
                </div>
                <div
                    style="font-size: 0.65rem; color: var(--text-dim); display: flex; justify-content: space-between; margin-top: 5px;">
                    <span>DISK</span><span id="txt-disk-EXECUTOR">0%</span></div>
                <div class="node-bar-container">
                    <div class="node-bar" id="bar-disk-EXECUTOR" style="background: var(--warning)"></div>
                </div>
            </div>
            <div class="node-card">
                <div class="node-header">
                    <span class="node-name">SCANNER_Scanners</span>
                    <span class="status-dot" id="dot-SCANNER"></span>
                </div>
                <div style="font-size: 0.65rem; color: var(--text-dim); display: flex; justify-content: space-between;">
                    <span>MESH</span><span id="txt-mesh-SCANNER">0/15</span></div>
                <div class="node-bar-container">
                    <div class="node-bar" id="bar-mesh-SCANNER" style="background: var(--success)"></div>
                </div>
                <div
                    style="font-size: 0.65rem; color: var(--text-dim); display: flex; justify-content: space-between; margin-top: 5px;">
                    <span>RAM</span><span id="txt-ram-SCANNER">0%</span></div>
                <div class="node-bar-container">
                    <div class="node-bar" id="bar-ram-SCANNER" style="background: var(--secondary)"></div>
                </div>
                <div
                    style="font-size: 0.65rem; color: var(--text-dim); display: flex; justify-content: space-between; margin-top: 5px;">
                    <span>DISK</span><span id="txt-disk-SCANNER">0%</span></div>
                <div class="node-bar-container">
                    <div class="node-bar" id="bar-disk-SCANNER" style="background: var(--warning)"></div>
                </div>
            </div>
        </div>

        <div class="sidebar-section">
            <h3>Decision Engine</h3>
            <div class="node-card">
                <div class="node-header">
                    <span class="node-name">AI Status</span>
                    <span class="badge badge-primary" id="ai-status-badge">Healthy</span>
                </div>
                <div style="font-size: 0.65rem; color: var(--text-dim);" id="ai-last-check">Last audit: Just now</div>
            </div>
            <div class="node-card">
                <div class="node-header">
                    <span class="node-name">Risk Mode</span>
                    <span class="badge badge-secondary" id="risk-mode-badge">NORMAL</span>
                </div>
            </div>
        </div>
    </aside>

    <main>
        <div class="hero-section" id="hero-indodax">
            <div class="hero-card">
                <span class="stat-label">Total Equity (IDR)</span>
                <span class="hero-val" id="total-equity">Rp 0</span>
                <div class="hero-delta up" id="pnl-delta">+0.0% today</div>
            </div>
            <div class="hero-card">
                <span class="stat-label">Free Cash Balance</span>
                <span class="hero-val" id="free-cash">Rp 0</span>
            </div>
            <div class="hero-card">
                <span class="stat-label">Active Trades</span>
                <span class="hero-val" id="active-trades">0</span>
            </div>
        </div>

        <div class="hero-section" id="hero-polymarket" style="display:none">
            <div class="hero-card">
                <span class="stat-label">USDC Balance</span>
                <span class="hero-val" id="poly-balance">$0.00</span>
            </div>
            <div class="hero-card">
                <span class="stat-label">MATIC (Gas)</span>
                <span class="hero-val" id="poly-gas">0.00 MATIC</span>
            </div>
            <div class="hero-card">
                <span class="stat-label">Open Markets</span>
                <span class="hero-val" id="poly-trades">0</span>
            </div>
        </div>

        <div class="signals-panel">
            <div class="panel-header">
                <span class="panel-title">LIVE SCANNER FEED</span>
                <div class="badge badge-primary" id="signal-count">0 Signals</div>
            </div>
            <div class="panel-content" id="signal-feed">
                <!-- Signals will appear here -->
            </div>
        </div>

        <div class="sidebar-right">
            <div class="decision-panel">
                <div class="panel-header"><span class="panel-title">DECISION LOG</span></div>
                <div class="terminal" id="decision-log">
                    <div class="term-entry"><span class="term-ts">[SYSTEM]</span> Initializing Trinity Core...</div>
                </div>
            </div>

            <div class="decision-panel" style="flex: 0.6;">
                <div class="panel-header"><span class="panel-title">ASSET HOLDINGS</span></div>
                <div class="panel-content holdings-list" id="holdings-list">
                    <!-- Assets -->
                </div>
            </div>
        </div>
    </main>

    <script>
        let currentView = 'indodax';

        function switchView(view) {
            currentView = view;
            document.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
            document.getElementById('btn-' + view).classList.add('active');

            if (view === 'indodax') {
                document.getElementById('hero-indodax').style.display = 'grid';
                document.getElementById('hero-polymarket').style.display = 'none';
            } else {
                document.getElementById('hero-indodax').style.display = 'none';
                document.getElementById('hero-polymarket').style.display = 'grid';
            }
        }

        async function update() {
            try {
                // Fetch from the unified state endpoint
                const r = await fetch('/api/state');
                const state = await r.json();

                if (!state || state.error) return;

                // 1. BTC STATS
                const btc = state.btc || {};
                document.getElementById('btc-price').innerText = btc.price > 0 ? '$' + btc.price.toLocaleString() : 'Loading...';
                
                const biasEl = document.getElementById('market-bias');
                const regime = (state.market_regime || 'SIDEWAYS').toUpperCase();
                biasEl.innerText = `${regime}`;
                biasEl.style.color = regime === 'BULLISH' ? 'var(--success)' : (regime === 'BEARISH' ? 'var(--danger)' : 'var(--warning)');

                // 2. AI & RISK STATUS
                const ai = state.ai_status || {};
                const aiBadge = document.getElementById('ai-status-badge');
                aiBadge.innerText = ai.healthy ? 'Healthy' : 'Degraded';
                aiBadge.className = 'badge ' + (ai.healthy ? 'badge-primary' : 'badge-secondary');
                
                const riskMode = state.risk_mode || 'NORMAL';
                const riskBadge = document.getElementById('risk-mode-badge');
                riskBadge.innerText = riskMode;
                riskBadge.style.background = riskMode === 'RISK_OFF' ? 'var(--danger)' : 'var(--secondary)';

                // 3. FINANCIALS (INDODAX)
                const metrics = state.metrics || {};
                document.getElementById('total-equity').innerText = 'Rp ' + (metrics.total_equity_idr || 0).toLocaleString();
                document.getElementById('free-cash').innerText = 'Rp ' + (metrics.available_idr || 0).toLocaleString();
                document.getElementById('active-trades').innerText = (state.portfolio?.active_positions || []).length;
                
                const pnlDelta = document.getElementById('pnl-delta');
                const pnlVal = metrics.daily_pnl_pct || 0;
                pnlDelta.innerText = (pnlVal >= 0 ? '+' : '') + pnlVal.toFixed(2) + '% today';
                pnlDelta.className = 'hero-delta ' + (pnlVal >= 0 ? 'up' : 'down');

                // 4. INFRASTRUCTURE (MOCKED FOR NOW, NEEDS REAL DATA)
                const setBar = (id, val) => {
                    const bar = document.getElementById('bar-' + id);
                    const txt = document.getElementById('txt-' + id);
                    if (bar) bar.style.width = (val || 0) + '%';
                    if (txt) txt.innerText = (val || 0) + '%';
                };
                
                // Real data from metrics if available
                setBar('cpu-batam', metrics.system_cpu || 0);
                setBar('ram-batam', metrics.system_ram || 0);
                setBar('disk-batam', metrics.system_disk || 0);

                // 5. HOLDINGS
                const hList = document.getElementById('holdings-list');
                const holdings = state.portfolio?.active_positions || [];
                hList.innerHTML = holdings.length > 0 ? '' : '<div style="color:var(--text-dim);font-size:0.7rem;padding:10px;">No positions</div>';
                holdings.forEach(h => {
                    const item = document.createElement('div');
                    item.className = 'holding-item';
                    item.innerHTML = `<span class="holding-name">${h}</span><span class="holding-val">ACTIVE</span>`;
                    hList.appendChild(item);
                });

                // 6. DECISION LOG
                const log = document.getElementById('decision-log');
                const actions = state.recent_actions || [];
                if (actions.length > 0) {
                    log.innerHTML = '';
                    actions.forEach(a => {
                        const entry = document.createElement('div');
                        entry.className = 'term-entry';
                        entry.innerHTML = `<span class="term-ts">[${new Date().toLocaleTimeString()}]</span> <span class="term-tag">LOG</span> ${JSON.stringify(a)}`;
                        log.appendChild(entry);
                    });
                }

                // 7. LIVE SCANNER FEED
                const signals = state.scanners?.top_signals || [];
                const feed = document.getElementById('signal-feed');
                document.getElementById('signal-count').innerText = signals.length + ' Signals';
                
                if (signals.length > 0) {
                    feed.innerHTML = '';
                    signals.forEach(s => {
                        const row = document.createElement('div');
                        row.className = 'sig-row';
                        row.innerHTML = `
                            <span style="color: var(--text-dim)">${new Date().toLocaleTimeString()}</span>
                            <span class="sig-pair">${s.pair.toUpperCase()}</span>
                            <span class="sig-score" style="color: ${s.msc > 0.8 ? 'var(--success)' : 'var(--warning)'}">${s.msc.toFixed(2)}</span>
                            <span class="badge badge-secondary">${s.scanners.length} Radars</span>
                            <span style="font-size: 0.7rem; color: var(--text-dim); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${s.scanners.join(', ')}</span>
                            <span style="font-weight: 700; color: ${s.action === 'ENTRY' ? 'var(--success)' : 'var(--warning)'}">${s.action}</span>
                        `;
                        feed.appendChild(row);
                    });
                }

            } catch (e) { 
                console.error("Dashboard update failed:", e); 
            }
        }

        setInterval(update, 5000);
        update();
        lucide.createIcons();
    </script>
</body>

</html>
"""
