# [Module] Deployment (Server Operations)

This directory contains the configurations required to run KiBot's scanner network as persistent background services on a Linux server.

## Key Files

### 1. `.service` files (Systemd Templates)
- Templates like `kibot-scanner-binance.service` or `kibot-scanner-all.service`.
- These allow you to use `systemctl` to start, stop, and enable the scrapers to run automatically on boot.

### 2. `deploy_scanners.sh`
- An automated bash script that:
    - Sets up the Python virtual environment.
    - Installs necessary dependencies.
    - Copies the service files to `/etc/systemd/system/`.
    - Starts the scanner fleet.

## How to use
On your Linux server:
1. `chmod +x deploy_scanners.sh`
2. `./deploy_scanners.sh`
3. Check status: `systemctl status kibot-scanner-all`

## Why this is used?
Scanners must never sleep. By using systemd, we ensure that if a scraper crashes or the server reboots, it will automatically restart itself within seconds.
