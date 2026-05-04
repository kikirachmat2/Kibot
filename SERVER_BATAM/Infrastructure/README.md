# KiBot Infrastructure (Sovereign Shield v8.2)

Low-level infrastructure and orchestration for the KiBot trading cluster.

## Paranoid Reconstruction Architecture

In v8.2, we have hardened the infrastructure to prevent process-level attacks, resource exhaustion, and service leakage.

### 1. Role-Based Purity (ROLE_MANIFEST.md)
The cluster is divided into functional roles (Batam, Executor, Scanner). 
- **Enforcement**: `kibot_guardian.py` dynamically identifies its node's role via the `KIBOT_ROLE` environment variable.
- **Isolation**: Services not assigned to a node's role are automatically stopped and ignored, preventing "Service Leakage".

### 2. Systemd Hardening & Sandboxing
All microservices are now sandboxed using advanced systemd features:
- **ProtectSystem=full**: Makes `/usr`, `/boot`, and `/etc` read-only for the service.
- **PrivateTmp=yes**: Provides a private `/tmp` directory, isolated from the rest of the system.
- **NoNewPrivileges=yes**: Prevents the service and its children from gaining new privileges via `setuid` or `setgid` bits.
- **OOMPolicy=kill**: Ensures memory-leaking processes are terminated immediately by the OS rather than degrading system performance.

### 3. Resource Constraints
Strict hardware limits are enforced per service to prevent cascading cluster failure:
- **MemoryMax**: Hard cap on RAM usage (e.g., 800MB for Manager, 1.2GB for Learning Engine).
- **CPUQuota**: Restricts CPU usage to a percentage of a single core (e.g., 50% for Guardian).

### 4. Network Hardening
- **Local Loopback Binding**: Core inter-node services default to `127.0.0.1`.
- **Encrypted Env Sync**: Secrets are synchronized via `sync_env_to_server.sh` using encrypted `.env.kiv` containers.

## Maintenance Commands

### Deploying Hardened Services
```bash
# Apply new unit files
sudo cp systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload

# Restart with role enforcement
sudo systemctl restart kibot-manager
```

### Monitoring Resource Usage
```bash
systemctl status kibot-manager
# Look for 'Memory: ... (limit: 800.0M)'
```

## Security Policy
1. **Zero Trust**: No service should trust signals without HMAC verification.
2. **Resource Integrity**: Any service exceeding its allocated resources is considered compromised/unstable and must be killed.
3. **Role Accountability**: A node must only run services defined in its manifest.
