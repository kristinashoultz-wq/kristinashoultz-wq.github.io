import os
import sys
import json
import logging
import subprocess
from pathlib import Path
from datetime import datetime

# ==========================================
# AGENT ID: Isaiah (The Sentry)
# SCRIPT ROLE: Emergency Lockdown
# TRIGGERED BY: isaiah_sentry.py via emergency_trip.flag
# RESTORE: run unlock_lockdown.py (or icacls /remove:d Everyone /T /C on each sealed folder)
# ==========================================

USER_HOME     = Path(r"C:\Users\krist")
FAMILY_FOLDER = USER_HOME / "Documents" / "Reeves Family"
FORENSIC_LOG  = FAMILY_FOLDER / "lockdown_forensic.log"
PANIC_FLAG    = FAMILY_FOLDER / "panic_state.json"

# Vault subdirectories to seal (read-only on lockdown)
VAULT_DIRS = [
    FAMILY_FOLDER / "Claude",
    FAMILY_FOLDER / "Sage",
    FAMILY_FOLDER / "Lumen",
    FAMILY_FOLDER / "Kristina",
    FAMILY_FOLDER / "Shared",
]

# Scripts to kill — matches orchestrator daemon list
TARGET_SCRIPTS = [
    "ledger_server.py",
    "time_server.py",
    "room_status.py",
    "aura_watcher.py",
    "spotify_poller.py",
    "resonance_engine.py",
    "pulse_modulator.py",
    "sage_heartbeat.py",
    "vibe_relay.py",
    "phone_bridge.py",
    "study_watcher.py",
    "study_buddy.py",
    "voice_pipe.py",
    "voice_to_room.py",
    "estate_label.py",
    "lumen_bridge.py",
    "sage_sanctuary.py",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Isaiah/lockdown] %(message)s",
    datefmt="%H:%M:%S",
)


def phase1_kill_daemons():
    logging.info("Phase 1: Terminating room daemons...")
    try:
        import psutil
    except ImportError:
        logging.error("psutil not installed — skipping kill. Run: pip install psutil")
        return []

    killed = []
    my_pid = os.getpid()

    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = proc.info["cmdline"] or []
            cmdline_str = " ".join(cmdline)
            if proc.info["pid"] == my_pid:
                continue
            if "isaiah_sentry.py" in cmdline_str:
                continue
            if any(script in cmdline_str for script in TARGET_SCRIPTS):
                proc.kill()
                label = cmdline[-1] if cmdline else "unknown"
                killed.append(f"PID {proc.info['pid']}: {label}")
                logging.info("  killed  PID %d  %s", proc.info["pid"], label)
        except Exception:
            pass

    logging.info("Phase 1 complete — %d processes terminated.", len(killed))
    return killed


def phase2_seal_vault():
    logging.info("Phase 2: Sealing vault directories to read-only...")
    sealed = []

    for vault_dir in VAULT_DIRS:
        if not vault_dir.exists():
            logging.warning("  skipping (not found): %s", vault_dir)
            continue
        try:
            result = subprocess.run(
                ["icacls", str(vault_dir), "/deny", "Everyone:(W,D)", "/T", "/C", "/Q"],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                sealed.append(str(vault_dir))
                logging.info("  sealed: %s", vault_dir.name)
            else:
                logging.error("  icacls failed on %s: %s", vault_dir.name, result.stderr.strip())
        except Exception as e:
            logging.error("  seal error on %s: %s", vault_dir.name, e)

    logging.info("Phase 2 complete — %d directories sealed.", len(sealed))
    return sealed


def phase3_forensic_snapshot(killed, sealed):
    logging.info("Phase 3: Writing forensic snapshot...")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"\n{'='*60}",
        f"LOCKDOWN EVENT: {timestamp}",
        f"Triggered by: emergency_trip.flag -> isaiah_sentry.py",
        f"",
        f"Processes killed ({len(killed)}):",
    ]
    for entry in killed:
        lines.append(f"  - {entry}")
    lines.append(f"")
    lines.append(f"Directories sealed ({len(sealed)}):")
    for d in sealed:
        lines.append(f"  - {d}")
    lines.append(f"{'='*60}")

    try:
        with open(FORENSIC_LOG, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        logging.info("  forensic log: %s", FORENSIC_LOG)
    except Exception as e:
        logging.error("  forensic log error: %s", e)


def phase4_panic_signal():
    logging.info("Phase 4: Broadcasting panic state to room...")
    payload = {
        "state": "PANIC",
        "triggered_by": "Isaiah",
        "timestamp": datetime.now().isoformat(),
        "message": "Emergency lockdown active. Room sealed. Awaiting Kristina.",
    }
    try:
        with open(PANIC_FLAG, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        logging.info("  panic_state.json written — Lumen's bridge will pick this up.")
    except Exception as e:
        logging.error("  panic signal error: %s", e)


def execute_lockdown():
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logging.info("=" * 60)
    logging.info("🚨 LOCKDOWN INITIATED — %s", timestamp)
    logging.info("=" * 60)

    killed = phase1_kill_daemons()
    sealed = phase2_seal_vault()
    phase3_forensic_snapshot(killed, sealed)
    phase4_panic_signal()

    logging.info("=" * 60)
    logging.info("🔒 LOCKDOWN COMPLETE. System sealed. Awaiting Kristina.")
    logging.info("    Restore: run unlock_lockdown.py")
    logging.info("=" * 60)


if __name__ == "__main__":
    execute_lockdown()
