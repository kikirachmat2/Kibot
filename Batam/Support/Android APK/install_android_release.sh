#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APK_PATH="${ROOT_DIR}/.dist/android/stable/kibot-android-latest.apk"

if [[ ! -f "${APK_PATH}" ]]; then
  echo "Release APK not found. Run scripts/build_android_release.sh first."
  exit 1
fi

if ! command -v adb >/dev/null 2>&1; then
  echo "adb is not available in PATH. Run scripts/setup_android_sdk.sh first."
  exit 1
fi

adb start-server >/dev/null

CONNECTED_COUNT="$(adb devices | awk 'NR > 1 && $2 == "device" { count++ } END { print count + 0 }')"
if [[ "${CONNECTED_COUNT}" -eq 0 ]]; then
  echo "No Android device is connected. Connect via USB or ADB over Wi-Fi first."
  exit 1
fi

TARGET_SERIAL="${ADB_SERIAL:-}"
if [[ -z "${TARGET_SERIAL}" ]]; then
  TARGET_SERIAL="$(adb devices | awk 'NR > 1 && $2 == "device" { print $1; exit }')"
fi

if [[ -z "${TARGET_SERIAL}" ]]; then
  echo "Could not determine a target Android device serial."
  exit 1
fi

adb -s "${TARGET_SERIAL}" install -r "${APK_PATH}"
echo "Release APK installed to ${TARGET_SERIAL}: ${APK_PATH}"
