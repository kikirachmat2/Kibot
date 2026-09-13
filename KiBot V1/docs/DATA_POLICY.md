# KiBot Data Policy & Retention Mandate

## Overview
This document defines the check-in isolation and retention rules for all raw trade logs, engine state caches, SQLite databases, DuckDB matrices, and Parquet simulation frames.

To ensure performance, data integrity, and privacy, **no large-scale historical data or strategy records must ever be checked into GitHub.**

---

## 🛡️ Git Check-in Isolation Rules

1. **Strictly Untracked Directory (`data/`)**
   - The `/data` folder at the repository root is globally ignored by `.gitignore`.
   - Under no circumstances should simulation chunks, duckdb analytical schemas, or strategy walk-forwards be force-committed.

2. **Common Binary File Exclusions**
   - The following file extensions are explicitly banned from repository check-ins:
     - `*.parquet` (Simulation/Telemetry dataframes)
     - `*.duckdb` (Strategy analytics database files)
     - `*.sqlite` / `*.db` (Relational persistence structures)

3. **Placeholder / Directory Keepers (`.keep_git`)**
   - To maintain directory structures on server checkouts without checking in data files, use a `.keep_git` (or `.gitkeep`) file inside empty local tracking folders.
   - Example path: `/data/.keep_git` or `/state/.keep_git`.
   - When configuring automated scripts that write to `/data`, ensure they create the directory at startup if it does not exist.

---

## 🕒 Retention Policy & Data Backups

- **Local Live Caches**: State files in `/state` (e.g. `punishment_state.json`, `expected_value.json`) are updated in-place.
- **Backups & Corruption Recovery**: In case of runtime corruption, the `PunishmentEngine` and `ExpectedValueEngine` auto-backup original data to `/state/punishment_state.corrupt.<timestamp>.json` and re-write a clean baseline schema.
- **Telemetry Archive**: Large-scale trade logs are periodically rotated and aggregated into `/data/history/` as compressed Parquet files for off-heap strategy analysis.
