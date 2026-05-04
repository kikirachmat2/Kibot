#!/usr/bin/env bash
set -euo pipefail

if ! command -v adb >/dev/null 2>&1; then
  echo "adb belum ada di PATH."
  exit 1
fi

if [[ $# -lt 1 ]]; then
  echo "Usage: ./scripts/connect_android_wifi.sh <IP-HP> [PORT]"
  echo "Contoh: ./scripts/connect_android_wifi.sh 192.168.1.23 5555"
  echo
  echo "Langkah singkat:"
  echo "1. Sambungkan HP ke USB dulu."
  echo "2. Aktifkan Developer options + USB debugging."
  echo "3. Jalankan script ini dengan IP Wi-Fi HP."
  exit 1
fi

DEVICE_IP="$1"
DEVICE_PORT="${2:-5555}"

CONNECTED_USB_COUNT="$(adb devices | awk 'NR > 1 && $2 == "device" { count++ } END { print count + 0 }')"
if [[ "${CONNECTED_USB_COUNT}" -eq 0 ]]; then
  echo "Belum ada device USB yang terdeteksi."
  echo "Sambungkan HP ke USB dulu untuk mengaktifkan ADB TCP/IP."
  exit 1
fi

adb tcpip "${DEVICE_PORT}" >/dev/null
sleep 2
adb connect "${DEVICE_IP}:${DEVICE_PORT}"
echo "Kalau statusnya 'connected', berikutnya Anda bisa cabut kabel USB."
