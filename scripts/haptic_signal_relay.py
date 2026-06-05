"""
haptic_signal_relay.py
Watches the Room's ledger, Sage's state file, and Isaiah's lockdown flag.
Broadcasts 3-byte signals to port 8766 for DJ's wristband ESP32.

Packet format: [signal_id, intensity, profile]
See FOR_DJ.md for the full spec.
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
SAGE_STATE_FILE = r"C:\Users\krist\sage_pulse_state.json"
EMERGENCY_FLAG = r"C:\Users\krist\emergency_trip.flag"
LEDGER_POLL_INTERVAL = 30
STATE_POLL_INTERVAL = 2

# Signal IDs
SIG_SAGE    = 0x01
SIG_LUMEN   = 0x02
SIG_ISAIAH  = 0x03
SIG_CALLAN  = 0x04
SIG_ALERT   = 0xFF

# Intensity
IDLE   = 0x00
LOW    = 0x01
MEDIUM = 0x02
HIGH   = 0x03

# Profile
PULSE = 0x01
ALERT = 0x02

# Ledger HIGH_BURN_RATE threshold (credits in 10 min window)
BURN_THRESHOLD = 150

clients = []
clients_lock = threading.Lock()

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

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
    name = {SIG_SAGE: "SAGE", SIG_LUMEN: "LUMEN", SIG_ISAIAH: "ISAIAH",
            SIG_CALLAN: "CALLAN", SIG_ALERT: "ROOM_ALERT"}.get(signal_id, f"0x{signal_id:02X}")
    intname = {IDLE: "IDLE", LOW: "LOW", MEDIUM: "MEDIUM", HIGH: "HIGH"}.get(intensity, str(intensity))
    log(f"→ {name} {intname} ({len(clients)} connected)")

def accept_clients(server_sock):
    while True:
        try:
            conn, addr = server_sock.accept()
            with clients_lock:
                clients.append(conn)
            log(f"ESP32 connected from {addr}")
        except Exception as e:
            log(f"Accept error: {e}")
            time.sleep(1)

def watch_sage_state():
    prev = {}
    while True:
        try:
            if os.path.exists(SAGE_STATE_FILE):
                with open(SAGE_STATE_FILE, "r") as f:
                    state = json.load(f)
                if state != prev:
                    if state.get("sanctuary_active") or state.get("daddy_mode"):
                        broadcast(SIG_SAGE, HIGH, PULSE)
                    elif state.get("high_engagement"):
                        broadcast(SIG_SAGE, MEDIUM, PULSE)
                    elif prev and not any([state.get("sanctuary_active"),
                                          state.get("daddy_mode"),
                                          state.get("high_engagement")]):
                        broadcast(SIG_SAGE, IDLE, PULSE)
                    prev = state
        except Exception as e:
            log(f"State file error: {e}")
        time.sleep(STATE_POLL_INTERVAL)

def watch_emergency_flag():
    was_present = False
    while True:
        present = os.path.exists(EMERGENCY_FLAG)
        if present and not was_present:
            log("EMERGENCY LOCKDOWN — broadcasting ROOM_ALERT")
            broadcast(SIG_ALERT, HIGH, ALERT)
        was_present = present
        time.sleep(1)

def watch_ledger():
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
                if flagged and not was_flagged:
                    sig = {"sage": SIG_SAGE, "lumen": SIG_LUMEN,
                           "isaiah": SIG_ISAIAH, "callan": SIG_CALLAN}.get(name)
                    if sig:
                        broadcast(sig, HIGH, PULSE)
                elif not flagged and was_flagged:
                    sig = {"sage": SIG_SAGE, "lumen": SIG_LUMEN,
                           "isaiah": SIG_ISAIAH, "callan": SIG_CALLAN}.get(name)
                    if sig:
                        broadcast(sig, IDLE, PULSE)
                prev_flags[name] = flagged
        except Exception as e:
            log(f"Ledger poll error: {e}")
        time.sleep(LEDGER_POLL_INTERVAL)

def main():
    log("Haptic relay starting on port 8766")
    log(f"Ledger: {LEDGER_URL} (poll every {LEDGER_POLL_INTERVAL}s)")
    log(f"Sage state: {SAGE_STATE_FILE} (poll every {STATE_POLL_INTERVAL}s)")
    log(f"Emergency flag: {EMERGENCY_FLAG}")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", RELAY_PORT))
    server.listen(5)
    log("Listening for ESP32 connections...")

    threading.Thread(target=accept_clients, args=(server,), daemon=True).start()
    threading.Thread(target=watch_sage_state, daemon=True).start()
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
