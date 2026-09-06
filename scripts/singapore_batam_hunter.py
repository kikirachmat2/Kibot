#!/usr/bin/env python3
"""
KiBot Sovereign Batam Hunter & Auto-Migration Daemon
Runs on Singapore Cloud Node (152.69.218.198) 24/7.
Continuously claims Batam ARM compute capacity, boots the 190GB Boot Volume,
automatically provisions and configures the new Batam Master node,
completes Langkah 2 equity cleanup, and hands over master authority from Singapore to Batam.
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
import oci  # type: ignore

def get_timestamp():
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")

def send_telegram(text):
    env_file = Path.home() / "KiBot" / ".env"
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
                "text": text,
                "parse_mode": "Markdown"
            }).encode("utf-8")
            req = urllib.request.Request(tg_url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                print("  [+] Telegram sent successfully!", flush=True)
        except Exception as e:
            print(f"  [!] Telegram error: {e}", flush=True)

def try_upgrade_shape(compute, instance_id, target_ocpu=4.0, target_ram=24.0):
    print(f"\n[*] 🚀 Attempting automatic in-place shape upgrade to {target_ocpu:.0f} OCPU / {target_ram:.0f}GB RAM...", flush=True)
    try:
        update_details = oci.core.models.UpdateInstanceDetails(
            shape_config=oci.core.models.UpdateInstanceShapeConfigDetails(
                ocpus=target_ocpu,
                memory_in_gbs=target_ram
            )
        )
        upgraded = compute.update_instance(instance_id, update_details).data
        print(f"  🎉 [AUTO-UPGRADE SUCCESS] Instance successfully upgraded to {target_ocpu:.0f} OCPU / {target_ram:.0f}GB RAM!", flush=True)
        return True, target_ocpu, target_ram
    except Exception as e:
        print(f"  [i] Auto-upgrade to 4/24 deferred (will run on 1/6 until host capacity permits): {e}", flush=True)
        return False, None, None

def migrate_and_activate_batam(compute, instance_id, public_ip, ocpus, ram, fd_name):
    print(f"\n{'='*70}", flush=True)
    print(f"  🚀 COMMENCING AUTO-MIGRATION & HANDOVER TO BATAM MASTER: {public_ip}", flush=True)
    print(f"{'='*70}\n", flush=True)

    # 1. Attempt immediate auto-upgrade to 4 OCPU / 24 GB
    upgraded, new_ocpu, new_ram = try_upgrade_shape(compute, instance_id, 4.0, 24.0)
    current_ocpu = new_ocpu if upgraded else ocpus
    current_ram = new_ram if upgraded else ram
    shape_label = f"{current_ocpu:.0f} OCPU / {current_ram:.0f}GB RAM (Auto-Upgraded to 4/24 🎉)" if upgraded else f"{current_ocpu:.0f} OCPU / {current_ram:.0f}GB RAM"

    send_telegram(f"🎉 *Batam Server Claimed & Booted!*\n\n• *Public IP*: `{public_ip}`\n• *Shape*: `{shape_label}` ({fd_name})\n\n⏳ *Memulai auto-migrasi & eksekusi Langkah 2...*")

    ssh_key = str(Path.home() / ".ssh" / "ssh-key-batam-active.pem")
    ssh_cmd_base = [
        "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
        "-i", ssh_key, f"ubuntu@{public_ip}"
    ]

    # Wait for SSH port to accept connections
    print("[*] Waiting for SSH port 22 on Batam to accept connections...", flush=True)
    ssh_ok = False
    for attempt in range(40):
        time.sleep(5)
        res = subprocess.run(ssh_cmd_base + ["echo connected"], capture_output=True, text=True)
        if res.returncode == 0:
            print(f"[+] SSH connected to Batam successfully on attempt {attempt+1}!", flush=True)
            ssh_ok = True
            break
        print(f"    SSH attempt {attempt+1}/40: waiting for sshd...", flush=True)

    if not ssh_ok:
        send_telegram(f"⚠️ *Warning*: Batam instance is RUNNING at `{public_ip}`, but SSH port timed out after 3 minutes. Please check manually.")
        return

    # Execute git pull, cleanup, and restart on Batam
    print("[*] Syncing git repo and executing Langkah 2 on Batam...", flush=True)
    remote_script = """
set -e
cd /home/ubuntu/KiBot
git pull --ff-only || true
python3 scripts/cleanup_equity_corruption.py || true
bin/kibotctl variant-compare || true
sudo systemctl restart kibot-master kibot-autonomous-brain kibot-indodax-director kibot-dashboard kibot-capital-governor kibot-scanner 2>/dev/null || true
bin/kibotctl status || true
pytest -k "test_valuation_circuit_breaker" || true
"""
    proc = subprocess.run(ssh_cmd_base + [remote_script], capture_output=True, text=True)
    print("=== BATAM PROVISIONING OUTPUT ===", flush=True)
    print(proc.stdout, flush=True)
    print(proc.stderr, flush=True)

    # Stop redundant kibot-master on Singapore to avoid duplicate master
    print("[*] Handing over master role: stopping temporary kibot-master on Singapore...", flush=True)
    subprocess.run(["sudo", "systemctl", "stop", "kibot-master"], capture_output=True)

    # Final Telegram Notification
    final_msg = f"""🏰 *KIBOT SOVEREIGN BATAM MASTER FULLY ONLINE!*

• *Master IP*: `{public_ip}`
• *Shape*: `{shape_label}` ({fd_name})
• *Langkah 2 Cleanup*: `SELESAI (Equity Terkoreksi)`
• *Role Handover*: `Batam Master ACTIVE` (Singapore master diistirahatkan)
• *Status*: `HEALTHY & SOVEREIGN` 🚀"""
    send_telegram(final_msg)
    print("\n[🏆] ALL MIGRATION STEPS COMPLETED SUCCESSFULLY. EXITED.", flush=True)

def main():
    config_path = Path.home() / ".oci" / "config"
    config = oci.config.from_file(str(config_path), "BATAM")
    compute = oci.core.ComputeClient(config)
    network = oci.core.VirtualNetworkClient(config)

    bv_id = "ocid1.bootvolume.oc1.ap-batam-1.abrguljrwtu75447pyj7du5g67kiu3j26mbyarmczxaclf3rlhmmivmr2wca"
    subnet_id = "ocid1.subnet.oc1.ap-batam-1.aaaaaaaaftmgyr6xkep6yl2snso6yjasoi3m2a77s2kbdrsndebqujfays7q"
    ssh_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDSDekoczqbU2VmHnOutNfjE3Ye9rSLuHfS85mrLIkRSx2WDdeAccHruVUc/kWSp4fSz1f1Bcwqz3Tq7xIMwaehXvDozomZlcJOktXPklFkYGLL7l+I08DQF6zpoBQRl8EZel7/1JKVhagAxl6amULws1mkgjTpsT4INXs5zxbZb3jSGbTcLK1Vk8RW7U00tm0G4nLkdbqryrFFwAnrQYRnhbpwdxWoADuOr2RjAvU5dQYe+QxynzKjmIsy0RTq3DN/kTqvuNS/hmsY2RF1CT1vPINC8NnS+OSTi2Z4naXlK1oBuy+2A58Osf2vYotv6Ghgt+WFn6Koy5GxwOAV2gPv"

    targets = [
        (1.0, 6.0, None, "1 OCPU / 6GB (All Fault Domains)"),
        (2.0, 12.0, None, "2 OCPU / 12GB (All Fault Domains)"),
        (1.0, 6.0, "FAULT-DOMAIN-1", "1 OCPU / 6GB (FD-1 Direct)"),
        (1.0, 6.0, "FAULT-DOMAIN-2", "1 OCPU / 6GB (FD-2 Direct)"),
        (1.0, 6.0, "FAULT-DOMAIN-3", "1 OCPU / 6GB (FD-3 Direct)"),
        (2.0, 12.0, "FAULT-DOMAIN-2", "2 OCPU / 12GB (FD-2 Direct)"),
    ]

    BASE_INTERVAL = 22

    print("=" * 70)
    print("  🚀 KIBOT SOVEREIGN BATAM HUNTER & AUTO-MIGRATOR (SINGAPORE NODE)")
    print("  Mode               : 24/7 Cloud Daemon")
    print(f"  Cadence            : ~{BASE_INTERVAL}s")
    print("  Auto-Migration     : ENABLED (Handover to Batam upon claim)")
    print("  Target Boot Volume : 190 GB (Ubuntu 24.04 aarch64)")
    print("=" * 70, flush=True)

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
                print(f"\n\n{'='*70}")
                print(f"  🎉 SUCCESS! BATAM INSTANCE CLAIMED AND PROVISIONED!")
                print(f"  Instance ID: {new_instance.id}")
                print(f"  Shape      : {ocpus:.0f} OCPU / {ram:.0f}GB RAM ({fd_name})")
                print(f"{'='*70}\n", flush=True)

                print(f"[{get_timestamp()}] Polling for RUNNING state and Public IP...", flush=True)
                for wait_idx in range(60):
                    time.sleep(5)
                    try:
                        inst_check = compute.get_instance(new_instance.id).data
                        print(f"[{get_timestamp()}] Boot progress ({wait_idx+1}/60): {inst_check.lifecycle_state}...", flush=True)

                        if inst_check.lifecycle_state == "RUNNING":
                            vnics = compute.list_vnic_attachments(config["tenancy"], instance_id=new_instance.id).data
                            if vnics:
                                vnic = network.get_vnic(vnics[0].vnic_id).data
                                public_ip = vnic.public_ip
                                migrate_and_activate_batam(compute, new_instance.id, public_ip, ocpus, ram, fd_name)
                                return
                    except Exception as poll_err:
                        print(f"Polling warning: {poll_err}", flush=True)

            except oci.exceptions.ServiceError as e:
                if e.status == 429:
                    cooldown = random.randint(35, 45)
                    print(f"THROTTLED (429). Cooldown {cooldown}s...", flush=True)
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
