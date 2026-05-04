#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-$HOME/Library/Android/sdk}"
BOOTSTRAP_DIR="${ROOT_DIR}/.wrapper-bootstrap"
CMDLINE_TOOLS_BIN="${ANDROID_SDK_ROOT}/cmdline-tools/latest/bin"
SDKMANAGER="${CMDLINE_TOOLS_BIN}/sdkmanager"
COMMANDLINE_ZIP_URL="https://dl.google.com/android/repository/commandlinetools-mac-14742923_latest.zip"
COMMANDLINE_ZIP_PATH="${BOOTSTRAP_DIR}/commandlinetools-mac-latest.zip"

mkdir -p "${ANDROID_SDK_ROOT}"
mkdir -p "${BOOTSTRAP_DIR}"

if [[ ! -x "${SDKMANAGER}" ]]; then
  rm -rf "${ANDROID_SDK_ROOT}/cmdline-tools"
  mkdir -p "${ANDROID_SDK_ROOT}/cmdline-tools"
  curl -L "${COMMANDLINE_ZIP_URL}" -o "${COMMANDLINE_ZIP_PATH}"
  unzip -q -o "${COMMANDLINE_ZIP_PATH}" -d "${ANDROID_SDK_ROOT}/cmdline-tools"
  if [[ -d "${ANDROID_SDK_ROOT}/cmdline-tools/cmdline-tools" ]]; then
    rm -rf "${ANDROID_SDK_ROOT}/cmdline-tools/latest"
    mv "${ANDROID_SDK_ROOT}/cmdline-tools/cmdline-tools" "${ANDROID_SDK_ROOT}/cmdline-tools/latest"
  fi
fi

set +o pipefail
yes | "${SDKMANAGER}" --sdk_root="${ANDROID_SDK_ROOT}" --licenses >/dev/null
set -o pipefail
"${SDKMANAGER}" --sdk_root="${ANDROID_SDK_ROOT}" \
  "platform-tools" \
  "platforms;android-35" \
  "build-tools;35.0.0"

if [[ -x "${ANDROID_SDK_ROOT}/platform-tools/adb" && ! -e "/usr/local/bin/adb" ]]; then
  ln -s "${ANDROID_SDK_ROOT}/platform-tools/adb" /usr/local/bin/adb
fi

cat > "${ROOT_DIR}/local.properties" <<EOF
sdk.dir=${ANDROID_SDK_ROOT}
EOF

printf 'Android SDK ready. local.properties -> %s/local.properties\n' "${ROOT_DIR}"
