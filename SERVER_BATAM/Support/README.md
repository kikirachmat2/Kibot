# [Module] Support (Utilities & Tools)

This directory contains supporting assets that are not part of the core trading loop but are essential for management, testing, and UI.

## Sub-directories

### 1. `Web/`
- Contains the source code for the **KiBot Web Dashboard**.
- Provides a beautiful, real-time visualization of the system's "Brain," active positions, and recent trades.

### 2. `Audit & Testing/`
- Scripts to manually trigger signals, test AI prompts, and audit the learning engine's database.
- Use `test_urgent_scout_manual.py` to verify the AI's ability to research an asset on-demand.

### 3. `Android APK/`
- Storage for mobile app assets or compiled APKs if the user wants to monitor the bot from a phone.

## How to use
Most tools here are for the developer or advanced operator. The Web Dashboard is the primary way for a human to observe the bot's autonomous decisions without reading terminal logs.
