#!/bin/bash
DEVICE_ID="40d203460421"

echo "🚀 [ADB] Forwarding all KiBot ports..."
adb -s $DEVICE_ID reverse tcp:8787 tcp:8787   # Dashboard WebSocket
adb -s $DEVICE_ID reverse tcp:8080 tcp:8080   # FastAPI Commander
adb -s $DEVICE_ID reverse tcp:18787 tcp:8787  # USB fallback alias
adb -s $DEVICE_ID reverse tcp:18798 tcp:9998  # Signal receiver fallback

echo "✅ Ports forwarded. App sekarang bisa connect via 127.0.0.1:8787" AKTIF."
fi
