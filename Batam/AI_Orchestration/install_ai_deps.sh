#!/bin/bash
# KiBot AI Dependency Installer
# Installs necessary libraries for the @AI_Orchestration ecosystem.

echo "--- Installing KiBot AI Dependencies ---"

# AI Search Tools
pip install --upgrade tavily-python duckduckgo-search finnhub-python

# HTTP & Security
pip install --upgrade requests urllib3 python-dotenv

# Market specific (if needed)
# pip install --upgrade polymarket-python

echo "--- Done ---"
echo "Note: Ensure your .env file in the root directory contains the necessary API keys."
