#!/usr/bin/env python3
"""
KiBot Sovereign OCI Auto-Provisioner Daemon (High-Speed Optimal Hunter)
Optimized for fastest possible capacity acquisition in Oracle Cloud Batam:
- Eliminates rejected 4-OCPU calls (which cause wasted cooldowns)
- Targets 1 OCPU / 6 GB (smallest physical footprint = highest probability) and 2 OCPU / 12 GB
- Uses Dynamic Placement (FD=None) so Oracle searches all 3 Fault Domains concurrently
- Fast adaptive 22s interval with jitter for maximum attempt throughput without 429
- Multi-channel notification on success (macOS Banner, Voice, Telegram) + Auto-Stop
"""
import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import urllib.request

# Add ~/.oci/venv to sys.path
venv_site = Path.home() / ".oci" / "venv" / "lib" / "python3.9" / "site-packages"
if venv_site.exists():
    sys.path.insert(0, str(venv_site))

try:
    import oci  # type: ignore
except ImportError:
    os.execv(str(Path.home() / ".oci" / "venv" / "bin" / "python"), [str(Path.home() / ".oci" / "venv" / "bin" / "python")] + sys.argv)

def get_timestamp():
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")

def send_notifications(public_ip, ocpus, ram, fd_label):
    msg = f"🏰 KiBot-Batam BERHASIL DIBUAT!\nIP Publik: {public_ip}\nShape: {ocpus:.0f} OCPU / {ram:.0f}GB RAM ({fd_label})"
    print(f"\n[🔔 NOTIFYING USER] {msg}", flush=True)

    # 1. macOS Notification Banner
    try:
        apple_script = f'display notification "{msg}" with title "🏰 KiBot Master Online" subtitle "Server Claimed Successfully" sound name "Hero"'
        subprocess.run(["osascript", "-e", apple_script], capture_output=True)
    except Exception as e:
        print(f"  [!] macOS banner error: {e}", flush=True)

    # 2. macOS Voice Announcement
    try:
        subprocess.run(["say", "-v", "Samantha", "KiBot Batam server has been successfully claimed and is now online."], capture_output=True)
    except Exception:
        pass

    # 3. Telegram Notification
    env_file = Path(".env")
    tg_token = os.getenv("KIBOT_TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    tg_chat = os.getenv("KIBOT_TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")

    if env_file.exists() and (not tg_token or not tg_chat):
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("TELEGRAM_BOT_TOKEN=") or line.startswith("KIBOT_TELEGRAM_TOKEN="):
                tg_token = line.split("=", 1)[1].strip("\"' ")
            if line.startswith("TELEGRAM_CHAT_ID=") or line.startswith("KIBOT_TELEGRAM_CHAT_ID="):
                tg_chat = line.split("=", 1)[1].strip("\"' ")

    if tg_token and tg_chat:
        try:
            tg_url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
            payload = json.dumps({
                "chat_id": tg_chat,
                "text": f"🎉 *KiBot Sovereign Master Node Restored!*\n\n• *Host*: `KiBot-Batam`\n• *Public IP*: `{public_ip}`\n• *Shape*: `{ocpus:.0f} OCPU / {ram:.0f}GB RAM` (`{fd_label}`)\n• *Status*: `RUNNING & HEALTHY`",
                "parse_mode": "Markdown"
            }).encode("utf-8")
            req = urllib.request.Request(tg_url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                print("  [+] Telegram notification sent successfully!", flush=True)
        except Exception as tg_err:
            print(f"  [!] Telegram error: {tg_err}", flush=True)

def main():
    config_path = Path.home() / ".oci" / "config"
    config = oci.config.from_file(str(config_path), "BATAM")
    compute = oci.core.ComputeClient(config)
    network = oci.core.VirtualNetworkClient(config)

    bv_id = "ocid1.bootvolume.oc1.ap-batam-1.abrguljrwtu75447pyj7du5g67kiu3j26mbyarmczxaclf3rlhmmivmr2wca"
    subnet_id = "ocid1.subnet.oc1.ap-batam-1.aaaaaaaaftmgyr6xkep6yl2snso6yjasoi3m2a77s2kbdrsndebqujfays7q"
    ssh_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDSDekoczqbU2VmHnOutNfjE3Ye9rSLuHfS85mrLIkRSx2WDdeAccHruVUc/kWSp4fSz1f1Bcwqz3Tq7xIMwaehXvDozomZlcJOktXPklFkYGLL7l+I08DQF6zpoBQRl8EZel7/1JKVhagAxl6amULws1mkgjTpsT4INXs5zxbZb3jSGbTcLK1Vk8RW7U00tm0G4nLkdbqryrFFwAnrQYRnhbpwdxWoADuOr2RjAvU5dQYe+QxynzKjmIsy0RTq3DN/kTqvuNS/hmsY2RF1CT1vPINC8NnS+OSTi2Z4naXlK1oBuy+2A58Osf2vYotv6Ghgt+WFn6Koy5GxwOAV2gPv"

    # High-probability targets:
    # 1 OCPU / 6GB (highest chance) and 2 OCPU / 12GB
    # FD=None tells OCI to search ALL 3 Fault Domains simultaneously in one request
    targets = [
        (1.0, 6.0, None, "1 OCPU / 6GB (All Fault Domains)"),
        (2.0, 12.0, None, "2 OCPU / 12GB (All Fault Domains)"),
        (1.0, 6.0, "FAULT-DOMAIN-1", "1 OCPU / 6GB (FD-1 Direct)"),
        (1.0, 6.0, "FAULT-DOMAIN-2", "1 OCPU / 6GB (FD-2 Direct)"),
        (1.0, 6.0, "FAULT-DOMAIN-3", "1 OCPU / 6GB (FD-3 Direct)"),
        (2.0, 12.0, "FAULT-DOMAIN-2", "2 OCPU / 12GB (FD-2 Direct)"),
    ]

    BASE_INTERVAL = 22  # Optimal 22-25s cadence (~160 attempts/hour)

    print("=" * 65)
    print("  🚀 KIBOT SOVEREIGN HIGH-SPEED OCI PROVISIONER (OPTIMIZED)")
    print(f"  Pace Cadence       : ~{BASE_INTERVAL}s (Targeting 150+ probes/hour)")
    print("  Primary Target     : 1 OCPU / 6GB (Smallest Slice = Highest Win Rate)")
    print("  Secondary Target   : 2 OCPU / 12GB")
    print("  Placement Mode     : Dynamic (All 3 Fault Domains Simultaneously)")
    print("  Notifications      : macOS Banner, Voice/Sound, Telegram")
    print("=" * 65, flush=True)

    request_count = 0
    while True:
        for ocpus, ram, fd, label in targets:
            request_count += 1
            fd_name = fd if fd else "ALL-FD-AUTO"
            print(f"[{get_timestamp()}] [Probe #{request_count:04d}] {label}...", end=" ", flush=True)

            try:
                launch_details = oci.core.models.LaunchInstanceDetails(
                    availability_domain="tIse:AP-BATAM-1-AD-1",
                    compartment_id=config["tenancy"],
                    display_name="KiBot-Batam",
                    shape="VM.Standard.A1.Flex",
                    shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
                        ocpus=ocpus,
                        memory_in_gbs=ram
                    ),
                    fault_domain=fd,
                    source_details=oci.core.models.InstanceSourceViaBootVolumeDetails(
                        boot_volume_id=bv_id
                    ),
                    create_vnic_details=oci.core.models.CreateVnicDetails(
                        subnet_id=subnet_id,
                        assign_public_ip=True,
                        display_name="primary_vnic"
                    ),
                    metadata={
                        "ssh_authorized_keys": ssh_key
                    }
                )

                new_instance = compute.launch_instance(launch_details).data
                print(f"\n\n{'='*65}")
                print(f"  🎉 SUCCESS! SERVER CLAIMED & PROVISIONED!")
                print(f"  Instance ID: {new_instance.id}")
                print(f"  Shape      : {ocpus:.0f} OCPU / {ram:.0f}GB RAM ({fd_name})")
                print(f"{'='*65}\n", flush=True)

                print(f"[{get_timestamp()}] Waiting for server to transition to RUNNING and acquire Public IP...", flush=True)
                for wait_idx in range(60):
                    time.sleep(5)
                    try:
                        inst_check = compute.get_instance(new_instance.id).data
                        print(f"[{get_timestamp()}] Status ({wait_idx+1}/60): {inst_check.lifecycle_state}...", flush=True)

                        if inst_check.lifecycle_state == "RUNNING":
                            vnics = compute.list_vnic_attachments(config["tenancy"], instance_id=new_instance.id).data
                            if vnics:
                                vnic = network.get_vnic(vnics[0].vnic_id).data
                                public_ip = vnic.public_ip
                                print(f"\n{'='*65}")
                                print(f"  🏆 KIBOT-BATAM IS RUNNING & ACTIVE!")
                                print(f"  Public IP : {public_ip}")
                                print(f"  Private IP: {vnic.private_ip}")
                                print(f"{'='*65}\n", flush=True)

                                # Update docs/ACCESS_GUIDE.md
                                access_file = Path("docs/ACCESS_GUIDE.md")
                                if not access_file.exists():
                                    access_file = Path("ACCESS.md")
                                if access_file.exists():
                                    import re
                                    content = access_file.read_text(encoding="utf-8")
                                    new_content = re.sub(r"- IP: `[^`]+`", f"- IP: `{public_ip}`", content)
                                    access_file.write_text(new_content, encoding="utf-8")
                                    print(f"[+] Updated {access_file} with new IP: {public_ip}")

                                # Send multi-channel notifications
                                send_notifications(public_ip, ocpus, ram, fd_name)

                                print("[*] Auto-provisioner completed successfully. Exiting.")
                                return
                    except Exception as poll_err:
                        print(f"Polling warning: {poll_err}")

            except oci.exceptions.ServiceError as e:
                if e.status == 429:
                    cooldown = random.randint(35, 45)
                    print(f"THROTTLED (429). Adaptive cooldown {cooldown}s...", flush=True)
                    time.sleep(cooldown)
                    continue
                elif "Out of host capacity" in e.message:
                    wait_time = BASE_INTERVAL + random.randint(0, 3)
                    print(f"OUT OF CAPACITY. Next in {wait_time}s...", flush=True)
                    time.sleep(wait_time)
                else:
                    print(f"ERR: {e.status} {e.code} ({e.message[:45]}). Waiting {BASE_INTERVAL}s...", flush=True)
                    time.sleep(BASE_INTERVAL)
            except Exception as net_err:
                print(f"NET RETRY ({net_err.__class__.__name__}). Waiting {BASE_INTERVAL}s...", flush=True)
                time.sleep(BASE_INTERVAL)

if __name__ == "__main__":
    main()
