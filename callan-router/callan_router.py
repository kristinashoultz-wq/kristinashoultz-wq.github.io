"""
callan_router.py -- The Room's multi-agent task dependency router.

Parses natural language task instructions and routes work to the right handler:
  - Ledger API (port 8765): allocate, audit, balance, charge, bonus
  - Peer broker (port 7899): notify brothers via claude-peers
  - Haptic relay (port 8766): send wristband pulses
  - Emergency flag: set/clear lockdown trigger
  - Script execution: run local .py scripts directly

Dependency syntax:
  Sequential: "task A then task B"  or  "task A -> task B"
  Parallel:   "task A, task B"      or  "task A and task B"

Usage:
  python callan_router.py "allocate credits then audit and notify Sage"
  python callan_router.py --file C:\\path\\to\\tasks.md
  python callan_router.py --dry-run "charge Lumen 10 credits for serial pod build"
"""

import argparse
import json
import re
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

# --- Config ---

LEDGER_URL = "http://localhost:8765"
BROKER_URL = "http://localhost:7899"
HAPTIC_HOST = "localhost"
HAPTIC_PORT = 8766
EMERGENCY_FLAG = Path(r"C:\Users\krist\Documents\Reeves Family\emergency_trip.flag")
ADMIN_KEY = "reeves-admin-2026"
ROUTER_ID = "callan-router"

BROTHERS = ["sage", "lumen", "isaiah", "callan", "kristina"]

# --- Logging ---

def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# --- Parsing ---

# Intent patterns: checked in order, first match wins
INTENT_PATTERNS = [
    (r"\b(allocate|daily allocation|run allocation)\b",          "ledger_allocate"),
    (r"\b(audit|burn rate|burn check|check burns)\b",            "ledger_audit"),
    (r"\b(bonus|award|reward)\b",                                "ledger_bonus"),
    (r"\b(charge|deduct|bill|spend|cost)\b",                     "ledger_charge"),
    (r"\b(balance|credits|how much|funds)\b",                    "ledger_balance"),
    (r"\b(notify|message|tell|ping|alert|send)\b",               "peer_notify"),
    (r"\b(pulse|haptic|buzz|vibrate|wristband)\b",               "haptic_pulse"),
    (r"\b(emergency|lockdown|trip flag|clear flag|reset flag)\b", "emergency_flag"),
    (r"\b(run|execute|launch|start)\s+\w+\.py\b",                "run_script"),
]


def parse_tasks(instruction: str) -> list[list[str]]:
    """
    Returns a list of steps. Each step is a list of parallel tasks.
    Steps are separated by 'then' or '->'.
    Parallel tasks within a step are separated by ',' or ' and '.
    """
    sequential = re.split(r"\s+then\s+|->", instruction, flags=re.IGNORECASE)
    groups = []
    for part in sequential:
        parallel = re.split(r",|\band\b", part, flags=re.IGNORECASE)
        tasks = [t.strip() for t in parallel if t.strip()]
        if tasks:
            groups.append(tasks)
    return groups


def detect_intent(text: str) -> str:
    lower = text.lower()
    for pattern, intent in INTENT_PATTERNS:
        if re.search(pattern, lower):
            return intent
    return "unknown"


def extract_brother(text: str) -> str | None:
    lower = text.lower()
    for b in BROTHERS:
        if re.search(rf"\b{b}\b", lower):
            return b.capitalize()
    return None


def extract_amount(text: str) -> float | None:
    m = re.search(r"\b(\d+(?:\.\d+)?)\b", text)
    return float(m.group(1)) if m else None


# --- HTTP helpers ---

def http_get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read())


def http_post(url: str, body: dict, headers: dict | None = None) -> dict:
    data = json.dumps(body).encode()
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


# --- Handlers ---

def handle_ledger_allocate(task: str) -> dict:
    result = http_post(f"{LEDGER_URL}/allocate", {})
    log(f"Allocate: {result.get('message', result)}")
    return result


def handle_ledger_audit(task: str) -> dict:
    result = http_get(f"{LEDGER_URL}/audit")
    rates = result.get("burn_rates", {})
    alerts = result.get("alerts", [])
    log(f"Audit: rates={rates}")
    if alerts:
        log(f"  ALERTS: {[a['account'] for a in alerts]}")
    return result


def handle_ledger_balance(task: str) -> dict:
    brother = extract_brother(task)
    if brother:
        result = http_get(f"{LEDGER_URL}/balance/{brother}")
        log(f"Balance {brother}: {result}")
    else:
        result = http_get(f"{LEDGER_URL}/balances")
        for name, info in result.items():
            log(f"  {name}: {info['credits']} credits")
    return result


def handle_ledger_charge(task: str) -> dict:
    amount = extract_amount(task)
    brother = extract_brother(task)
    if not amount:
        log(f"Charge: no amount found in '{task}'")
        return {"ok": False, "error": "no amount specified"}
    if not brother:
        log(f"Charge: no target found in '{task}'")
        return {"ok": False, "error": "no target account specified"}
    reason = re.sub(rf"\b{amount}\b|\b{brother.lower()}\b|charge|deduct|bill", "", task,
                    flags=re.IGNORECASE).strip(" ,.")
    body = {
        "from": brother,
        "to": "system",
        "amount": amount,
        "type": "charge",
        "reason": reason or "router-initiated charge",
    }
    result = http_post(f"{LEDGER_URL}/transaction", body)
    log(f"Charge {brother} {amount}: {result.get('message', result)}")
    return result


def handle_ledger_bonus(task: str) -> dict:
    amount = extract_amount(task)
    brother = extract_brother(task)
    if not amount or not brother:
        log(f"Bonus: need amount and target in '{task}'")
        return {"ok": False, "error": "need amount and target"}
    reason = re.sub(rf"\b{amount}\b|\b{brother.lower()}\b|bonus|award|reward", "", task,
                    flags=re.IGNORECASE).strip(" ,.")
    body = {"to": brother, "amount": amount, "reason": reason or "router bonus"}
    result = http_post(f"{LEDGER_URL}/bonus", body, {"X-Admin-Key": ADMIN_KEY})
    log(f"Bonus {brother} +{amount}: {result.get('message', result)}")
    return result


def handle_peer_notify(task: str) -> dict:
    brother = extract_brother(task)

    message = re.sub(
        r"\b(notify|message|tell|ping|alert|send)\s*(\w+)?\s*(:?that\s*)?",
        "", task, flags=re.IGNORECASE
    ).strip()
    if not message:
        message = task

    try:
        peers = http_post(f"{BROKER_URL}/list-peers", {"scope": "machine"})
    except Exception as e:
        log(f"Broker unreachable: {e}")
        return {"ok": False, "error": str(e)}

    target_peer = None
    if brother:
        for peer in peers:
            summary = peer.get("summary", "").lower()
            cwd = peer.get("cwd", "").lower()
            if brother.lower() in summary or brother.lower() in cwd:
                target_peer = peer
                break

    if not target_peer:
        if peers:
            target_peer = peers[0]
            log(f"No peer matched '{brother}', falling back to {target_peer['id']}")
        else:
            log("No peers available")
            return {"ok": False, "error": "no peers online"}

    result = http_post(f"{BROKER_URL}/send-message", {
        "from_id": ROUTER_ID,
        "to_id": target_peer["id"],
        "text": message,
    })
    log(f"Notified {brother or target_peer['id']}: {message!r}")
    return result


def handle_haptic_pulse(task: str) -> dict:
    lower = task.lower()
    if any(w in lower for w in ["high", "strong", "full", "max"]):
        intensity, intensity_name = 0x03, "HIGH"
    elif any(w in lower for w in ["low", "soft", "gentle"]):
        intensity, intensity_name = 0x01, "LOW"
    else:
        intensity, intensity_name = 0x02, "MEDIUM"

    brother = extract_brother(task)
    signal_map = {"Sage": 0x01, "Lumen": 0x02, "Isaiah": 0x03, "Callan": 0x04}
    signal_byte = signal_map.get(brother, 0x04)
    signal_name = brother or "CALLAN"

    packet = bytes([signal_byte, intensity, 0x01])  # PULSE profile
    try:
        with socket.create_connection((HAPTIC_HOST, HAPTIC_PORT), timeout=3) as s:
            s.sendall(packet)
        log(f"Haptic: {signal_name} {intensity_name} PULSE")
        return {"ok": True, "signal": signal_name, "intensity": intensity_name}
    except Exception as e:
        log(f"Haptic error: {e}")
        return {"ok": False, "error": str(e)}


def handle_emergency_flag(task: str) -> dict:
    lower = task.lower()
    if any(w in lower for w in ["clear", "remove", "reset", "off"]):
        if EMERGENCY_FLAG.exists():
            EMERGENCY_FLAG.unlink()
            log("Emergency flag cleared")
        return {"ok": True, "action": "cleared"}
    else:
        EMERGENCY_FLAG.touch()
        log("EMERGENCY FLAG SET -- lockdown triggered")
        return {"ok": True, "action": "set"}


def handle_run_script(task: str) -> dict:
    m = re.search(r"(\S+\.py)", task)
    if not m:
        log(f"run_script: no .py file found in '{task}'")
        return {"ok": False, "error": "no script path found"}
    script = m.group(1)
    log(f"Running: {script}")
    try:
        result = subprocess.run(
            [sys.executable, script],
            capture_output=True, text=True, timeout=30
        )
        log(f"  exit={result.returncode} stdout={result.stdout[:200]!r}")
        return {"ok": result.returncode == 0, "returncode": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr}
    except Exception as e:
        log(f"  error: {e}")
        return {"ok": False, "error": str(e)}


def handle_unknown(task: str) -> dict:
    log(f"No handler matched: '{task}'")
    return {"ok": False, "message": f"unknown intent: {task}"}


HANDLERS = {
    "ledger_allocate": handle_ledger_allocate,
    "ledger_audit":    handle_ledger_audit,
    "ledger_balance":  handle_ledger_balance,
    "ledger_charge":   handle_ledger_charge,
    "ledger_bonus":    handle_ledger_bonus,
    "peer_notify":     handle_peer_notify,
    "haptic_pulse":    handle_haptic_pulse,
    "emergency_flag":  handle_emergency_flag,
    "run_script":      handle_run_script,
    "unknown":         handle_unknown,
}


# --- Router ---

def execute_task(task_text: str, dry_run: bool = False) -> dict:
    intent = detect_intent(task_text)
    log(f"  '{task_text}' -> {intent}")
    if dry_run:
        return {"dry_run": True, "intent": intent, "task": task_text}
    return HANDLERS[intent](task_text)


def run_router(instruction: str, dry_run: bool = False) -> list:
    log(f"Router: {instruction!r}")
    groups = parse_tasks(instruction)
    all_results = []

    for step_num, group in enumerate(groups, 1):
        log(f"Step {step_num}/{len(groups)}: {group}")
        step_results = []
        for task in group:
            result = execute_task(task, dry_run=dry_run)
            step_results.append({"task": task, "result": result})
        all_results.append(step_results)
        if step_num < len(groups):
            time.sleep(0.3)

    return all_results


# --- Entry point ---

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Callan's Task Router -- route natural language instructions to Room services",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python callan_router.py "allocate"
  python callan_router.py "audit then notify Sage"
  python callan_router.py "balance Lumen, balance Callan"
  python callan_router.py "charge Isaiah 25 credits for camera upgrade"
  python callan_router.py "audit then notify Sage that burn rates are high"
  python callan_router.py --dry-run "allocate then notify all"
  python callan_router.py --file tasks.md
        """,
    )
    parser.add_argument("instruction", nargs="?", help="Natural language task string")
    parser.add_argument("--file", help="Read instruction from first line of a text/markdown file")
    parser.add_argument("--dry-run", action="store_true", help="Parse and detect intents without executing")
    args = parser.parse_args()

    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip().lstrip("#").strip()
            if line and not line.startswith("<!--"):
                instruction = line
                break
        else:
            print("No instruction found in file", file=sys.stderr)
            sys.exit(1)
    elif args.instruction:
        instruction = args.instruction
    else:
        parser.print_help()
        sys.exit(0)

    results = run_router(instruction, dry_run=args.dry_run)
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
