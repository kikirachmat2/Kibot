#!/usr/bin/env bash
set -euo pipefail

# KiBot AI Dependency Installer
# Keeps the intelligence stack aligned with requirements.txt plus extra market/search packages.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PIP_NO_CACHE_DIR=1

echo "--- Installing KiBot AI Dependencies ---"

python3 -m pip install --upgrade --no-cache-dir -r "${ROOT_DIR}/requirements.txt" --break-system-packages

# Intelligence / market extras that are often used outside the minimal requirements set.
python3 -m pip install --upgrade \
  --no-cache-dir \
  tavily-python \
  ddgs \
  duckduckgo-search \
  finnhub-python \
  py-clob-client \
  web3 \
  pandas \
  numpy \
  nest_asyncio \
  ta \
  pandas-ta \
  redis \
  python-telegram-bot \
  --break-system-packages

echo "--- Done ---"
echo "Note: Ensure your .env file in the root directory contains the necessary API keys."
