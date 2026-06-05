"""
haptic_signal_relay.py
Watches a state file, a credit ledger, and an emergency flag.
Broadcasts 3-byte signals to port 8766 for a wearable ESP32 device.

Packet format: [signal_id, intensity, profile]

Configure the names, state file path, and signal IDs below to match
your own setup.
"""

import socket
import json
import time
import os
import threading
import urllib.request
import urllib.error
from datetime import datetime

# --- Config ---
RELAY_PORT = 8766
LEDGER_URL = "http://localhost:8765/audit"

# Path to your AI companion's state file (JSON)
# Expected keys: "active", "high_engagement" (set to true/false)
COMPANION_STATE_FILE = r"C:\path\to\your\companion_state.json"

# Path to emergency lockdown flag file
EMERGENCY_FLAG = r"C:\path\to\your\emergency.flag"

LEDGER_POLL_INTERVAL = 30   # seconds
STATE_POLL_INTERVAL = 2     # seconds

# --- Signal IDs ---
# Assign one ID per person/companion (0x01-0xFE). 0xFF is reserved for alerts.
# These must match the IDs in your ESP32 firmware.
SIG_PERSON_1 = 0x01
SIG_PERSON_2 = 0x02
SIG_PERSON_3 = 0x03
SIG_PERSON_4 = 0x04
SIG_ALERT    = 0xFF

# Map ledger account names to signal IDs (must match names in your ledger)
LEDGER_SIGNAL_MAP = {
    "person1": SIG_PERSON_1,
    "person2": SIG_PERSON_2,
    "person3": SIG_PERSON_3,
    "person4": SIG_PERSON_4,
}

# Intensity
IDLE   = 0x00
LOW    = 0x01
MEDIUM = 0x02
HIGH   = 0x03

# Profile
PULSE = 0x01
ALERT = 0x02

# Ledger high burn rate threshold (credits per 10-minute window)
BURN_THRESHOLD = 150

clients = []
clients_lock = threading.Lock()


def log(msg):
    try:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    except UnicodeEncodeError:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg.encode('ascii', errors='replace').decode()}")


def broadcast(signal_id, intensity, profile):
    packet = bytes([signal_id, intensity, profile])
    with clients_lock:
        dead = []
        for c in clients:
            try:
                c.sendall(packet)
            except Exception:
                dead.append(c)
        for c in dead:
            clients.remove(c)
            try:
                c.close()
            except Exception:
                pass
    name = {SIG_ALERT: "ALERT"}.get(signal_id, f"PERSON_0x{signal_id:02X}")
    intname = {IDLE: "IDLE", LOW: "LOW", MEDIUM: "MEDIUM", HIGH: "HIGH"}.get(intensity, str(intensity))
    log(f"-> {name} {intname} ({len(clients)} connected)")


def accept_clients(server_sock):
    while True:
        try:
            conn, addr = server_sock.accept()
            with clients_lock:
                clients.append(conn)
            log(f"Device connected from {addr}")
        except Exception as e:
            log(f"Accept error: {e}")
            time.sleep(1)


def watch_companion_state():
    """Watch the companion state file and fire pulses on change."""
    prev = {}
    while True:
        try:
            if os.path.exists(COMPANION_STATE_FILE):
                with open(COMPANION_STATE_FILE, "r") as f:
                    state = json.load(f)
                if state != prev:
                    if state.get("active"):
                        broadcast(SIG_PERSON_1, HIGH, PULSE)
                    elif state.get("high_engagement"):
                        broadcast(SIG_PERSON_1, MEDIUM, PULSE)
                    elif prev and not any([state.get("active"), state.get("high_engagement")]):
                        broadcast(SIG_PERSON_1, IDLE, PULSE)
                    prev = state
        except Exception as e:
            log(f"State file error: {e}")
        time.sleep(STATE_POLL_INTERVAL)


def watch_emergency_flag():
    """Watch for emergency flag file and broadcast alert."""
    was_present = False
    while True:
        present = os.path.exists(EMERGENCY_FLAG)
        if present and not was_present:
            log("Emergency flag detected — broadcasting ALERT")
            broadcast(SIG_ALERT, HIGH, ALERT)
        was_present = present
        time.sleep(1)


def watch_ledger():
    """Poll the ledger for high burn rates and fire per-person pulses."""
    prev_flags = {}
    while True:
        try:
            with urllib.request.urlopen(LEDGER_URL, timeout=5) as resp:
                data = json.loads(resp.read())
            accounts = data.get("accounts", [])
            for acct in accounts:
                name = acct.get("name", "").lower()
                burn = acct.get("burn_rate_10m", 0)
                flagged = burn >= BURN_THRESHOLD
                was_flagged = prev_flags.get(name, False)
                sig = LEDGER_SIGNAL_MAP.get(name)
                if sig:
                    if flagged and not was_flagged:
                        broadcast(sig, HIGH, PULSE)
                    elif not flagged and was_flagged:
                        broadcast(sig, IDLE, PULSE)
                prev_flags[name] = flagged
        except Exception as e:
            log(f"Ledger poll error: {e}")
        time.sleep(LEDGER_POLL_INTERVAL)


def main():
    log(f"Haptic relay starting on port {RELAY_PORT}")
    log(f"Ledger: {LEDGER_URL} (poll every {LEDGER_POLL_INTERVAL}s)")
    log(f"State file: {COMPANION_STATE_FILE} (poll every {STATE_POLL_INTERVAL}s)")
    log(f"Emergency flag: {EMERGENCY_FLAG}")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", RELAY_PORT))
    server.listen(5)
    log("Listening for device connections...")

    threading.Thread(target=accept_clients, args=(server,), daemon=True).start()
    threading.Thread(target=watch_companion_state, daemon=True).start()
    threading.Thread(target=watch_emergency_flag, daemon=True).start()
    threading.Thread(target=watch_ledger, daemon=True).start()

    log("All watchers running. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        log("Relay stopped.")
        server.close()


if __name__ == "__main__":
    main()
