#!/bin/bash
# 📱 KiBot Android Commander Bridge
# Menghubungkan HP (via USB) ke API Lokal Batam

PORT=8080
DEVICE_ID="40d203460421"

echo "🚀 [ADB] Initializing Reverse Port Forwarding on $PORT..."
adb -s $DEVICE_ID reverse tcp:$PORT tcp:$PORT

if [ $? -eq 0 ]; then
    echo "✅ [ADB] HP sekarang bisa akses API di http://localhost:$PORT"
else
    echo "❌ [ADB] Gagal melakukan port forwarding. Pastikan Developer Options & USB Debugging AKTIF."
fi
