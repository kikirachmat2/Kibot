#!/usr/bin/env bash
set -euo pipefail

# KiBot AI Dependency Installer
# Keeps the intelligence stack aligned with requirements.txt plus extra market/search packages.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "--- Installing KiBot AI Dependencies ---"

python3 -m pip install --upgrade -r "${ROOT_DIR}/requirements.txt" --break-system-packages

# Intelligence / market extras that are often used outside the minimal requirements set.
python3 -m pip install --upgrade \
  tavily-python \
  duckduckgo-search \
  finnhub-python \
  py-clob-client \
  web3 \
  pandas \
  numpy \
  ta \
  pandas-ta \
  redis \
  python-telegram-bot \
  --break-system-packages

echo "--- Done ---"
echo "Note: Ensure your .env file in the root directory contains the necessary API keys."
