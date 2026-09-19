#!/usr/bin/env python3
"""
KiBot V2 — OCI ARM Capacity Catcher for Batam Tenancy (ap-batam-1).
Continuously polls Oracle Cloud API for VM.Standard.A1.Flex (2 OCPU / 12 GB RAM)
until capacity becomes available. Injects auto-bootstrap cloud-init script on launch.
Supports --dry-run for non-intrusive connectivity verification.
"""
import argparse
import base64
import json
import logging
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("BatamCatcher")

DEFAULT_SUBNET_ID = "ocid1.subnet.oc1.ap-batam-1.aaaaaaaaftmgyr6xkep6yl2snso6yjasoi3m2a77s2kbdrsndebqujfays7q"
DEFAULT_SHAPE = "VM.Standard.A1.Flex"
DEFAULT_OCPUS = 2
DEFAULT_MEMORY_GBS = 12
DEFAULT_BOOT_VOLUME_GBS = 50

def send_telegram(token: str, chat_id: str, message: str) -> None:
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=8)
    except Exception as exc:
        logger.warning(f"[Telegram] Failed to send alert: {exc}")

def load_user_data_script(script_path: Path, ts_authkey: str = "", tg_token: str = "", tg_chat: str = "") -> str:
    content = ""
    if script_path.exists():
        content = script_path.read_text(encoding="utf-8")
    else:
        content = "#!/bin/bash\necho 'KiBot Batam instance booted'\n"

    # Inject env vars into cloud-init header
    header = f"#!/bin/bash\nexport TS_AUTHKEY='{ts_authkey}'\nexport KIBOT_TELEGRAM_BOT_TOKEN='{tg_token}'\nexport KIBOT_TELEGRAM_CHAT_ID='{tg_chat}'\n"
    full_script = header + "\n" + content
    return base64.b64encode(full_script.encode("utf-8")).decode("utf-8")

def get_ubuntu_arm_image_id(compute_client, compartment_id: str) -> str:
    """Finds latest Canonical Ubuntu 24.04 / 22.04 aarch64 image in the compartment."""
    try:
        images = compute_client.list_images(
            compartment_id=compartment_id,
            operating_system="Canonical Ubuntu",
            shape=DEFAULT_SHAPE,
            sort_by="TIMECREATED",
            sort_order="DESC"
        ).data
        for img in images:
            if "24.04" in img.display_name or "22.04" in img.display_name:
                logger.info(f"Using OS Image: {img.display_name} ({img.id})")
                return img.id
        if images:
            return images[0].id
    except Exception as exc:
        logger.warning(f"Could not list images by shape: {exc}")
    return ""

def main():
    parser = argparse.ArgumentParser(description="OCI ARM Catcher for Batam Tenancy")
    parser.add_argument("--config-file", default=os.path.expanduser("~/.oci/config"), help="OCI config file path")
    parser.add_argument("--profile", default="BATAM", help="Profile name in OCI config")
    parser.add_argument("--dry-run", action="store_true", help="Simulate check without launching instance")
    parser.add_argument("--interval", type=int, default=35, help="Polling interval in seconds")
    args = parser.parse_args()

    import oci

    logger.info("=" * 60)
    logger.info(f"🤖 OCI ARM CATCHER — BATAM REGION (ap-batam-1)")
    logger.info(f"Target: {DEFAULT_SHAPE} ({DEFAULT_OCPUS} OCPU / {DEFAULT_MEMORY_GBS} GB RAM)")
    logger.info(f"Dry-run: {args.dry_run} | Profile: {args.profile}")
    logger.info("=" * 60)

    try:
        config = oci.config.from_file(args.config_file, args.profile)
    except Exception as exc:
        logger.error(f"Failed to load OCI config ({args.config_file}, profile {args.profile}): {exc}")
        sys.exit(1)

    compute_client = oci.core.ComputeClient(config)
    identity_client = oci.identity.IdentityClient(config)
    compartment_id = config["tenancy"]

    tg_token = os.getenv("KIBOT_TELEGRAM_TOKEN", "")
    tg_chat = os.getenv("KIBOT_TELEGRAM_CHAT_ID", "")
    ts_authkey = os.getenv("TS_AUTHKEY", "")

    # 1. Fetch Availability Domains
    try:
        ads = [ad.name for ad in identity_client.list_availability_domains(compartment_id).data]
        logger.info(f"Available ADs in Batam: {ads}")
    except Exception as exc:
        logger.error(f"Failed to list Availability Domains: {exc}")
        sys.exit(1)

    if not ads:
        logger.error("No Availability Domains found in region.")
        sys.exit(1)

    # 2. Find Image
    image_id = get_ubuntu_arm_image_id(compute_client, compartment_id)
    if not image_id:
        logger.warning("Could not automatically locate Ubuntu ARM image. Using fallback query.")

    # 3. Prepare User Data and SSH Key
    script_file = Path(__file__).parent / "bootstrap-batam.sh"
    encoded_user_data = load_user_data_script(script_file, ts_authkey=ts_authkey, tg_token=tg_token, tg_chat=tg_chat)
    
    ssh_key_path = os.path.expanduser("~/.ssh/kibot/ssh-key-batam-active.pem.pub")
    ssh_key = ""
    if os.path.exists(ssh_key_path):
        ssh_key = Path(ssh_key_path).read_text().strip()
    elif os.path.exists(os.path.expanduser("~/.ssh/id_rsa.pub")):
        ssh_key = Path(os.path.expanduser("~/.ssh/id_rsa.pub")).read_text().strip()

    if args.dry_run:
        logger.info("🧪 DRY RUN MODE: Verifying parameters...")
        logger.info(f"Compartment: {compartment_id}")
        logger.info(f"Subnet ID: {DEFAULT_SUBNET_ID}")
        logger.info(f"ADs to cycle: {ads}")
        logger.info(f"Image ID: {image_id}")
        logger.info(f"User Data size (base64): {len(encoded_user_data)} chars")
        send_telegram(tg_token, tg_chat, "🧪 <b>OCI Batam Catcher</b>: Dry-run test successful. Ready to arm.")
        logger.info("✅ Dry run finished successfully.")
        return

    if not ts_authkey and not args.dry_run:
        logger.error("❌ CRITICAL: TS_AUTHKEY environment variable is missing! Aborting launch to prevent orphan instance.")
        send_telegram(tg_token, tg_chat, "⚠️ <b>OCI Batam Catcher</b>: Refusing to start without TS_AUTHKEY.")
        sys.exit(1)

    # Polling Loop
    attempt = 0
    ad_idx = 0
    send_telegram(tg_token, tg_chat, "🔍 <b>OCI Batam Catcher ARMED</b>: Hunting 2 OCPU / 12 GB in ap-batam-1...")

    while True:
        attempt += 1
        current_ad = ads[ad_idx % len(ads)]
        ad_idx += 1
        display_name = f"kibot-batam-node-{int(time.time())}"

        launch_details = oci.core.models.LaunchInstanceDetails(
            compartment_id=compartment_id,
            availability_domain=current_ad,
            shape=DEFAULT_SHAPE,
            shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
                ocpus=float(DEFAULT_OCPUS),
                memory_in_gbs=float(DEFAULT_MEMORY_GBS)
            ),
            create_vnic_details=oci.core.models.CreateVnicDetails(
                subnet_id=DEFAULT_SUBNET_ID,
                assign_public_ip=True
            ),
            image_id=image_id,
            display_name=display_name,
            metadata={
                "ssh_authorized_keys": ssh_key,
                "user_data": encoded_user_data
            }
        )

        try:
            logger.info(f"[Attempt #{attempt}] Requesting launch in {current_ad}...")
            resp = compute_client.launch_instance(launch_details)
            if resp.status == 200:
                instance = resp.data
                logger.info(f"🎉 SUCCESS! Claimed instance {instance.id} in {current_ad}")
                msg = (
                    f"🎉 <b>KIBOT BATAM INSTANCE CLAIMED!</b>\n"
                    f"• OCID: <code>{instance.id}</code>\n"
                    f"• Shape: 2 OCPU / 12 GB ARM\n"
                    f"• AD: {current_ad}\n"
                    f"• Status: Provisioning & Auto-Bootstrapping..."
                )
                send_telegram(tg_token, tg_chat, msg)

                # Persist success record
                out_record = {
                    "instance_id": instance.id,
                    "availability_domain": current_ad,
                    "claimed_at": datetime.utcnow().isoformat(),
                    "attempts": attempt,
                }
                out_path = Path("/home/ubuntu/KiBotV2/KiBot V2/state/batam_instance.json")
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(json.dumps(out_record, indent=2))
                return
        except oci.exceptions.ServiceError as exc:
            if exc.status == 429:
                logger.warning(f"[Attempt #{attempt}] Rate limited (429). Sleeping 90s...")
                time.sleep(90)
                continue
            elif "Out of host capacity" in str(exc.message):
                logger.info(f"[Attempt #{attempt}] Capacity unavailable in {current_ad}. Will retry.")
            else:
                logger.warning(f"[Attempt #{attempt}] OCI Error ({exc.status} {exc.code}): {exc.message}")
        except Exception as e:
            logger.error(f"[Attempt #{attempt}] Unexpected error: {e}")

        # Send heartbeat summary every 100 attempts
        if attempt % 100 == 0:
            send_telegram(tg_token, tg_chat, f"📡 <b>OCI Batam Catcher</b>: Still hunting ({attempt} attempts)...")

        jitter = random.uniform(-4, 6)
        sleep_dur = max(20.0, args.interval + jitter)
        time.sleep(sleep_dur)

if __name__ == "__main__":
    main()
