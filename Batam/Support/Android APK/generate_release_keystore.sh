#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRETS_DIR="${ROOT_DIR}/.secrets"
KEYSTORE_PATH="${ROOT_DIR}/kibot-release.jks"
KEYSTORE_ENV="${SECRETS_DIR}/android-keystore.env"

mkdir -p "${SECRETS_DIR}"

random_secret() {
  python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(24))
PY
}

if [[ -f "${KEYSTORE_PATH}" && -f "${KEYSTORE_ENV}" ]]; then
  printf 'Release keystore already exists: %s\n' "${KEYSTORE_PATH}"
  exit 0
fi

STORE_PASSWORD="$(random_secret)"
KEY_PASSWORD="${STORE_PASSWORD}"
KEY_ALIAS="kibot-release"

keytool -genkeypair \
  -v \
  -keystore "${KEYSTORE_PATH}" \
  -storepass "${STORE_PASSWORD}" \
  -keypass "${KEY_PASSWORD}" \
  -alias "${KEY_ALIAS}" \
  -keyalg RSA \
  -keysize 4096 \
  -validity 3650 \
  -dname "CN=KiBot Private, OU=Private Trading, O=KiBot, L=Jakarta, ST=DKI Jakarta, C=ID"

cat > "${KEYSTORE_ENV}" <<EOF
ANDROID_RELEASE_KEYSTORE_PATH=${KEYSTORE_PATH}
ANDROID_RELEASE_STORE_PASSWORD=${STORE_PASSWORD}
ANDROID_RELEASE_KEY_ALIAS=${KEY_ALIAS}
ANDROID_RELEASE_KEY_PASSWORD=${KEY_PASSWORD}
EOF
chmod 600 "${KEYSTORE_ENV}" "${KEYSTORE_PATH}"

printf 'Release keystore created: %s\n' "${KEYSTORE_PATH}"
