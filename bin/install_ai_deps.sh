#!/bin/bash
# KiBot AI Dependency Installer
# Installs necessary libraries for the @Intelligence ecosystem.

echo "--- Installing KiBot AI Dependencies ---"

# AI Search Tools
pip3 install --upgrade tavily-python duckduckgo-search finnhub-python --break-system-packages

# HTTP & Security
pip3 install --upgrade requests urllib3 python-dotenv --break-system-packages

# Market specific (if needed)
# pip install --upgrade polymarket-python

echo "--- Done ---"
echo "Note: Ensure your .env file in the root directory contains the necessary API keys."
