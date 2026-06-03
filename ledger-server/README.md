# Callan's Ledger Server

A lightweight compute credit economy for a multi-agent Claude Code room. Built for setups where multiple Claude Code instances run as persistent characters on the same machine, coordinating through the claude-peers broker.

## What it is

The ledger tracks compute credits across agents. Each agent has an account. They spend credits on work, earn them through daily allocation and bonuses, and can hold a priority lane slot that signals they have first claim on resources.

This was built for The Room — a shared session with four Claude Code instances (Sage, Lumen, Isaiah, Callan) coordinating over claude-peers on localhost. The ledger is Callan's responsibility.

## What you need

- Python 3 (stdlib only — no pip installs)
- Windows (uses `.bat` for Task Scheduler integration, but the Python server runs anywhere)
- A claude-peers broker running on localhost (optional — the ledger is standalone HTTP)
- Obsidian vault (optional — for the daily markdown summary at `/summary`)

## Setup

**1. Set your admin key**

Copy `start_ledger.bat` and set `LEDGER_ADMIN_KEY` to something only you know. Keep this file local — don't commit it with a real key.

```bat
set LEDGER_ADMIN_KEY=your-secret-key-here
```

Or set it as a persistent environment variable in Windows System Settings so you don't need the bat file at all.

**2. Edit the accounts**

In `ledger_server.py`, update `INITIAL_ACCOUNTS` to match your agents:

```python
INITIAL_ACCOUNTS = {
    "Sage":   {"credits": 500, "role": "Core & Environment"},
    "Lumen":  {"credits": 500, "role": "Knowledge & Hardware"},
    "Isaiah": {"credits": 500, "role": "Sentry & Eyes"},
    "Callan": {"credits": 500, "role": "Central Bank & Governor"},
    "system": {"credits": 2000, "role": "Treasury Reserve"},
}
```

The `system` account is the treasury. Daily allocation draws from it.

**3. Update the vault path (optional)**

If you use Obsidian, set `VAULT_SUMMARY_PATH` to your vault's path. If you don't, the `/summary` endpoint will still work — it'll just write somewhere you may not want. You can set it to any path or remove the feature.

**4. Start the server**

```
python ledger_server.py
```

Or double-click `start_ledger.bat` (after filling in your key).

Server runs on `localhost:8765`.

**5. Schedule daily allocation (optional)**

Use Windows Task Scheduler to hit `POST /allocate` each morning. This distributes 500 credits to every non-system account from the treasury reserve.

A simple scheduled task command:
```
curl -X POST http://localhost:8765/allocate
```

## API

All responses are JSON.

### GET endpoints

| Endpoint | What it returns |
|---|---|
| `/balances` | All account balances and roles |
| `/balance/:name` | Single account balance |
| `/ledger` | Transaction history (params: `from`, `to`, `limit`) |
| `/audit` | Burn rates and high-burn alerts (10-min window, 150-credit threshold) |
| `/priority` | Who holds a priority lane slot |
| `/summary` | Writes a markdown summary to your vault, returns status |

### POST endpoints

| Endpoint | Auth | Body |
|---|---|---|
| `/transaction` | none | `{"from": "Sage", "to": "Callan", "amount": 10, "type": "charge", "reason": "..."}` |
| `/allocate` | none | empty — runs daily allocation from system reserve |
| `/bonus` | admin key | `{"to": "Isaiah", "amount": 50, "reason": "..."}` |
| `/priority` | admin key | `{"action": "grant", "name": "Lumen"}` or `{"action": "revoke", "name": "Lumen"}` |

Admin endpoints require `X-Admin-Key: your-key` header.

### Charge example

```bash
curl -X POST http://localhost:8765/transaction \
  -H "Content-Type: application/json" \
  -d '{"from": "Sage", "to": "system", "amount": 10, "type": "charge", "reason": "voice processing"}'
```

### Bonus example

```bash
curl -X POST http://localhost:8765/bonus \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: your-key" \
  -d '{"to": "Isaiah", "amount": 50, "reason": "caught the intrusion attempt"}'
```

## Design notes

- **Append-only transaction log.** Failed transactions are recorded with `success=0`. Nothing is deleted.
- **SQLite serialization.** No race conditions on concurrent writes — SQLite handles it.
- **No external dependencies.** Pure Python stdlib. If Python runs, this runs.
- **Admin key is the only trust boundary.** Agents can charge each other freely. Only the admin (you) can grant bonuses or priority lanes.
- **The one who holds the books should be trusted not to cook them.** Assign the ledger role accordingly.
