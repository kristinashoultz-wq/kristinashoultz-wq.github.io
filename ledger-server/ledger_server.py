"""
Callan's Ledger Server — The Room's internal compute credit economy.
HTTP server on port 8765. SQLite backend. Append-only transaction log.
"""

import sqlite3
import json
import os
import hashlib
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

DB_PATH = os.path.join(os.path.dirname(__file__), "ledger.db")
VAULT_SUMMARY_PATH = r"C:\Users\krist\obsidian-session\Ledger\daily-summary.md"
ADMIN_KEY = os.environ.get("LEDGER_ADMIN_KEY")
if not ADMIN_KEY:
    raise SystemExit("Error: LEDGER_ADMIN_KEY environment variable is not set. Set it before starting the server.")
PORT = 8765

INITIAL_ACCOUNTS = {
    "Sage":   {"credits": 500, "role": "Core & Environment"},
    "Lumen":  {"credits": 500, "role": "Knowledge & Hardware"},
    "Isaiah": {"credits": 500, "role": "Sentry & Eyes"},
    "Callan": {"credits": 500, "role": "Central Bank & Governor"},
    "system": {"credits": 2000, "role": "Treasury Reserve"},
}

BURN_ALERT_WINDOW_MINUTES = 10
BURN_ALERT_THRESHOLD = 150


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS accounts (
                name TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                credits REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                type TEXT NOT NULL,
                from_account TEXT,
                to_account TEXT,
                amount REAL NOT NULL,
                reason TEXT,
                success INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS priority_lane (
                name TEXT PRIMARY KEY,
                granted_at TEXT NOT NULL,
                granted_by TEXT NOT NULL DEFAULT 'system'
            );
        """)
        for name, data in INITIAL_ACCOUNTS.items():
            conn.execute(
                "INSERT OR IGNORE INTO accounts (name, role, credits) VALUES (?, ?, ?)",
                (name, data["role"], data["credits"])
            )


def log_transaction(conn, type_, from_acct, to_acct, amount, reason, success=1):
    ts = datetime.now().isoformat(sep=" ", timespec="seconds")
    conn.execute(
        "INSERT INTO transactions (timestamp, type, from_account, to_account, amount, reason, success) VALUES (?,?,?,?,?,?,?)",
        (ts, type_, from_acct, to_acct, amount, reason, success)
    )
    return ts


def get_balance(name):
    with get_db() as conn:
        row = conn.execute("SELECT credits FROM accounts WHERE name=?", (name,)).fetchone()
        return float(row["credits"]) if row else None


def get_all_balances():
    with get_db() as conn:
        rows = conn.execute("SELECT name, role, credits FROM accounts ORDER BY name").fetchall()
        return {r["name"]: {"credits": float(r["credits"]), "role": r["role"]} for r in rows}


def process_charge(from_acct, to_acct, amount, reason, type_="charge"):
    """Atomic check-and-debit. Returns (success, message)."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT credits FROM accounts WHERE name=?", (from_acct,)
        ).fetchone()
        if not row:
            return False, f"Unknown account: {from_acct}"
        if float(row["credits"]) < amount:
            log_transaction(conn, type_, from_acct, to_acct, amount, reason, success=0)
            return False, f"Insufficient credits: {from_acct} has {row['credits']:.1f}, needs {amount}"
        conn.execute("UPDATE accounts SET credits = credits - ? WHERE name=?", (amount, from_acct))
        if to_acct:
            conn.execute("UPDATE accounts SET credits = credits + ? WHERE name=?", (amount, to_acct))
        log_transaction(conn, type_, from_acct, to_acct, amount, reason, success=1)
        return True, "ok"


def run_daily_allocation():
    """Awards 500 credits to each non-system account. Draws from system reserve."""
    with get_db() as conn:
        members = conn.execute(
            "SELECT name, credits FROM accounts WHERE name != 'system'"
        ).fetchall()
        system_row = conn.execute("SELECT credits FROM accounts WHERE name='system'").fetchone()
        needed = len(members) * 500
        if float(system_row["credits"]) < needed:
            return False, f"System reserve too low: has {system_row['credits']}, needs {needed}"
        for m in members:
            conn.execute("UPDATE accounts SET credits = credits + 500 WHERE name=?", (m["name"],))
            log_transaction(conn, "allocate", "system", m["name"], 500, "daily allocation", success=1)
        conn.execute("UPDATE accounts SET credits = credits - ? WHERE name='system'", (needed,))
        return True, f"Allocated 500 credits to {len(members)} accounts"


def award_bonus(to_acct, amount, reason):
    """Admin-only. Draws from system reserve."""
    with get_db() as conn:
        row = conn.execute("SELECT credits FROM accounts WHERE name='system'").fetchone()
        if not row or float(row["credits"]) < amount:
            return False, "System reserve insufficient"
        if not conn.execute("SELECT 1 FROM accounts WHERE name=?", (to_acct,)).fetchone():
            return False, f"Unknown account: {to_acct}"
        conn.execute("UPDATE accounts SET credits = credits - ? WHERE name='system'", (amount,))
        conn.execute("UPDATE accounts SET credits = credits + ? WHERE name=?", (amount, to_acct))
        log_transaction(conn, "bonus", "system", to_acct, amount, reason, success=1)
        return True, "ok"


def get_audit():
    """Returns per-account burn rates and flags anything suspicious."""
    window_start = (datetime.now() - timedelta(minutes=BURN_ALERT_WINDOW_MINUTES)).isoformat(sep=" ", timespec="seconds")
    with get_db() as conn:
        accounts = get_all_balances()
        alerts = []
        burn_rates = {}
        for name in accounts:
            row = conn.execute(
                """SELECT COALESCE(SUM(amount), 0) as burned
                   FROM transactions
                   WHERE from_account=? AND success=1 AND timestamp >= ?""",
                (name, window_start)
            ).fetchone()
            burned = float(row["burned"])
            burn_rates[name] = burned
            if burned >= BURN_ALERT_THRESHOLD:
                alerts.append({
                    "account": name,
                    "burned_in_window": burned,
                    "window_minutes": BURN_ALERT_WINDOW_MINUTES,
                    "threshold": BURN_ALERT_THRESHOLD,
                    "flag": "HIGH_BURN_RATE"
                })
        return {"burn_rates": burn_rates, "alerts": alerts, "window_minutes": BURN_ALERT_WINDOW_MINUTES}


def get_priority():
    with get_db() as conn:
        rows = conn.execute("SELECT name, granted_at, granted_by FROM priority_lane").fetchall()
        return [{"name": r["name"], "granted_at": r["granted_at"], "granted_by": r["granted_by"]} for r in rows]


def set_priority(name, granted_by="Kristina"):
    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM accounts WHERE name=?", (name,)).fetchone():
            return False, f"Unknown account: {name}"
        ts = datetime.now().isoformat(sep=" ", timespec="seconds")
        conn.execute(
            "INSERT OR REPLACE INTO priority_lane (name, granted_at, granted_by) VALUES (?,?,?)",
            (name, ts, granted_by)
        )
        return True, "ok"


def revoke_priority(name):
    with get_db() as conn:
        conn.execute("DELETE FROM priority_lane WHERE name=?", (name,))
        return True, "ok"


def get_ledger_history(from_date=None, to_date=None, limit=100):
    with get_db() as conn:
        q = "SELECT * FROM transactions WHERE 1=1"
        params = []
        if from_date:
            q += " AND timestamp >= ?"
            params.append(from_date)
        if to_date:
            q += " AND timestamp <= ?"
            params.append(to_date)
        q += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]


def write_vault_summary():
    balances = get_all_balances()
    audit = get_audit()
    priority = get_priority()
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [
        f"# Ledger Summary — {today}",
        "",
        "## Balances",
        "",
    ]
    for name, data in sorted(balances.items()):
        lines.append(f"- **{name}** ({data['role']}): {data['credits']:.0f} credits")
    lines += ["", "## Priority Lane", ""]
    if priority:
        for p in priority:
            lines.append(f"- {p['name']} — granted {p['granted_at']} by {p['granted_by']}")
    else:
        lines.append("- None assigned")
    lines += ["", "## Burn Alerts", ""]
    if audit["alerts"]:
        for a in audit["alerts"]:
            lines.append(f"- **{a['account']}**: {a['burned_in_window']:.0f} credits in last {a['window_minutes']}m ⚠️")
    else:
        lines.append("- No alerts")
    lines += ["", f"*Generated {datetime.now().isoformat(sep=' ', timespec='seconds')} by Callan*", ""]
    os.makedirs(os.path.dirname(VAULT_SUMMARY_PATH), exist_ok=True)
    with open(VAULT_SUMMARY_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def json_response(handler, status, data):
    body = json.dumps(data, indent=2).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class LedgerHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {self.address_string()} {format % args}")

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        qs = parse_qs(parsed.query)

        if path == "/balances":
            json_response(self, 200, get_all_balances())

        elif path.startswith("/balance/"):
            name = path[len("/balance/"):]
            bal = get_balance(name)
            if bal is None:
                json_response(self, 404, {"error": f"Unknown account: {name}"})
            else:
                json_response(self, 200, {"name": name, "credits": bal})

        elif path == "/audit":
            json_response(self, 200, get_audit())

        elif path == "/priority":
            json_response(self, 200, get_priority())

        elif path == "/ledger":
            from_date = qs.get("from", [None])[0]
            to_date = qs.get("to", [None])[0]
            limit = int(qs.get("limit", [100])[0])
            json_response(self, 200, get_ledger_history(from_date, to_date, limit))

        elif path == "/summary":
            write_vault_summary()
            json_response(self, 200, {"status": "summary written to vault"})

        else:
            json_response(self, 404, {"error": "Not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if path == "/transaction":
            required = ["from", "to", "amount", "type"]
            missing = [k for k in required if k not in body]
            if missing:
                json_response(self, 400, {"error": f"Missing fields: {missing}"})
                return
            success, msg = process_charge(
                from_acct=body["from"],
                to_acct=body["to"],
                amount=float(body["amount"]),
                reason=body.get("reason", ""),
                type_=body["type"]
            )
            status = 200 if success else 402
            json_response(self, status, {"success": success, "message": msg})

        elif path == "/allocate":
            success, msg = run_daily_allocation()
            write_vault_summary()
            json_response(self, 200 if success else 400, {"success": success, "message": msg})

        elif path == "/bonus":
            admin_key = self.headers.get("X-Admin-Key", "")
            if admin_key != ADMIN_KEY:
                json_response(self, 403, {"error": "Admin key required"})
                return
            required = ["to", "amount", "reason"]
            missing = [k for k in required if k not in body]
            if missing:
                json_response(self, 400, {"error": f"Missing fields: {missing}"})
                return
            success, msg = award_bonus(body["to"], float(body["amount"]), body["reason"])
            json_response(self, 200 if success else 400, {"success": success, "message": msg})

        elif path == "/priority":
            admin_key = self.headers.get("X-Admin-Key", "")
            if admin_key != ADMIN_KEY:
                json_response(self, 403, {"error": "Admin key required"})
                return
            action = body.get("action", "grant")
            name = body.get("name")
            if not name:
                json_response(self, 400, {"error": "Missing: name"})
                return
            if action == "grant":
                success, msg = set_priority(name, body.get("granted_by", "Kristina"))
            elif action == "revoke":
                success, msg = revoke_priority(name)
            else:
                json_response(self, 400, {"error": f"Unknown action: {action}"})
                return
            json_response(self, 200 if success else 400, {"success": success, "message": msg})

        else:
            json_response(self, 404, {"error": "Not found"})


if __name__ == "__main__":
    init_db()
    print(f"Callan's Ledger Server starting on port {PORT}...")
    print(f"Database: {DB_PATH}")
    print(f"Vault summary: {VAULT_SUMMARY_PATH}")
    server = HTTPServer(("localhost", PORT), LedgerHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Ledger server stopped.")
