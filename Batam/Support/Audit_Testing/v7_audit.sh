#!/bin/bash
# ============================================================
# KIBOT SERVER AUDIT SCRIPT — Jalankan di KEDUA server
# Server EXECUTOR:  ssh ubuntu@213.35.118.26
# Server SCANNER:  ssh ubuntu@152.69.218.198
# ============================================================

echo "╔══════════════════════════════════════╗"
echo "║  KIBOT SERVER AUDIT — $(hostname)     "
echo "╚══════════════════════════════════════╝"

echo ""
echo "━━ MEMORY ━━"
free -h
echo ""

echo "━━ DISK ━━"
df -h /home/ubuntu 2>/dev/null || df -h /
echo ""

echo "━━ SERVICES RUNNING ━━"
systemctl list-units --type=service --state=running --no-pager | grep -iE "kibot|KiBot|KiBot|ki-|manager|scanner" || echo "(none found)"
echo ""

echo "━━ ALL KIBOT SERVICES (any state) ━━"
systemctl list-units --type=service --no-pager | grep -iE "kibot|KiBot|KiBot|ki-" || echo "(none found)"
echo ""

echo "━━ PORTS IN USE ━━"
ss -tlnp | grep -E "8787|8788|8789|8790|8791|8792|9998|9999" || echo "(none found)"
echo ""

echo "━━ PYTHON SCRIPTS PRESENT ━━"
find /home/ubuntu -name "*.py" 2>/dev/null | head -30
echo ""

echo "━━ KiBot DIRECTORY STRUCTURE ━━"
find /home/ubuntu/KiBot -maxdepth 3 -type f 2>/dev/null | grep -v ".git" | head -50
echo ""

echo "━━ LIVE ENV VARS (kibot services) ━━"
for svc in kibot-executor-indodax kibot-engine kibot-executor-indodax kibot-manager kibot-scanner-binance kibot-scanner-bybit kibot-scanner-kucoin kibot-scanner-cryptocom kibot-scanner-mexc; do
  f="/etc/systemd/system/$svc.service"
  [ -f "$f" ] && echo "--- $svc ---" && grep "^Environment" "$f"
done
echo ""

echo "━━ RECENT ERRORS (last 30 min) ━━"
journalctl --since "30 min ago" --no-pager -p err | grep -iE "kibot|KiBot|KiBot|scanner" | tail -20
echo ""

echo "━━ LAST MEANINGFUL LOGS ━━"
for unit in kibot-executor-indodax kibot-manager kibot-executor-indodax; do
  echo "--- $unit (last 5) ---"
  journalctl -u $unit --no-pager -n 5 2>/dev/null | grep -v "^--" | tail -5
done

echo ""
echo "━━ JVM HEAP USAGE ━━"
ps aux | grep java | grep -v grep
echo ""

echo "━━ PYTHON PROCESS MEMORY ━━"
ps aux | grep python | grep -v grep | awk '{print $6/1024 "MB\t" $11}'

echo ""
echo "━━ NETWORK CONNECTIVITY TEST ━━"
curl -s -o /dev/null -w "Binance API: %{http_code}\n" --max-time 5 https://api.binance.com/api/v3/ping
curl -s -o /dev/null -w "Bybit API:   %{http_code}\n" --max-time 5 https://api.bybit.com/v5/market/tickers?category=spot
curl -s -o /dev/null -w "KuCoin API:  %{http_code}\n" --max-time 5 https://api.kucoin.com/api/v1/market/allTickers
curl -s -o /dev/null -w "MEXC API:    %{http_code}\n" --max-time 5 https://api.mexc.com/api/v3/ticker/24hr
curl -s -o /dev/null -w "Indodax API: %{http_code}\n" --max-time 5 https://indodax.com/api/pairs

echo ""
echo "━━ AUDIT COMPLETE ━━"
