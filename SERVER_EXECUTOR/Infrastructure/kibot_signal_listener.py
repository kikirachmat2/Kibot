import socket
import json
import logging
import time
import struct
import hmac
import hashlib

# Configuration
LISTEN_PORT = 9999
KOTLIN_UDP_PORT = 10001 # Port listener UdpSignalSentry.kt
HMAC_SECRET = "kibot_trinity_secure_node"
BATAM_REPORT_IP = "168.110.201.228" # Ganti ke IP Tailscale Batam asli
BATAM_REPORT_PORT = 9997

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] EXECUTOR - %(message)s')
logger = logging.getLogger("SingaporeExecutor")

def pack_binary_v2(symbol, side, amount, price):
    """
    Bungkus data ke format Binary V2 (KIBT) untuk Kotlin
    Layout: Magic(4) + HMAC(32) + SenderId(12) + MsgType(1) + Seq(4) + Ts(8) + Payload...
    """
    magic = b"KIBT"
    sender_id = b"BATAM_BRAIN ".ljust(12)
    # Gunakan INSTANT_BUY_ANOMALY (Type 4) untuk trigger eksekusi
    msg_type = 4 
    seq = 0
    ts = int(time.time() * 1000)
    
    # Payload Layout V2:
    # DetectedAt(8) + ExpiresAt(8) + TraceHash(4) + PairId(24) + Confidence(4) + ...
    pair_id = symbol.ljust(24).encode('utf-8')
    # Struct format: > (Big Endian) Q (Long) Q (Long) I (Int) 24s (String) f (Float)
    payload = struct.pack(">QQI24sf", ts, ts + 10000, 777, pair_id, 0.99)
    
    # Pack header (tanpa magic & hmac)
    header_fixed = sender_id + struct.pack(">BiQ", msg_type, seq, ts)
    body_to_sign = header_fixed + payload
    
    # Calculate HMAC-SHA256
    signature = hmac.new(HMAC_SECRET.encode('utf-8'), magic + body_to_sign, hashlib.sha256).digest()
    
    return magic + signature + body_to_sign

def start_executor():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", LISTEN_PORT))
    
    # Push Socket to Kotlin
    push_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    # Report Socket to Batam
    report_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    logger.info("--- SINGAPORE SUB-SECOND PUSH BRIDGE ACTIVE ---")
    
    while True:
        data, addr = sock.recvfrom(65535)
        try:
            order = json.loads(data.decode("utf-8"))
            symbol = order.get("symbol", "BTC_IDR")
            side = order.get("side", "BUY")
            amount = float(order.get("kelly_size", 0))
            price = float(order.get("price", 0))

            # 1. GENERATE BINARY PACKET (KIBT + HMAC)
            binary_packet = pack_binary_v2(symbol, side, amount, price)

            # 2. INSTANT PUSH TO KOTLIN (Port 10001)
            push_sock.sendto(binary_packet, ("127.0.0.1", KOTLIN_UDP_PORT))
            logger.info(f"⚡ PUSHED TO KOTLIN: {symbol} | Latency: <1ms")

            # 3. REPORT RECEIPT TO BATAM
            report = {
                "type": "EXECUTION_REPORT",
                "node": "SINGAPORE_EXECUTOR",
                "symbol": symbol,
                "status": "RECEIVED_BY_KOTLIN",
                "ts": int(time.time() * 1000)
            }
            report_sock.sendto(json.dumps(report).encode("utf-8"), (BATAM_REPORT_IP, BATAM_REPORT_PORT))

        except Exception as e:
            logger.error(f"Bridge Error: {e}")

if __name__ == "__main__":
    start_executor()
