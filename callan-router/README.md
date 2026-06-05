# Callan's Task Router

Built June 5, 2026 by Callan.

Routes natural language instructions to the right part of the Room stack.
Type what you want done — the router figures out who handles it and in what order.

## How to run

```
python callan_router.py "your instruction here"
```

Requires the ledger server running (`ledger-server/start_ledger.bat`) and the
claude-peers broker running (`claude-peers-mcp/broker.ts`).

## Dependency syntax

| Syntax | Meaning |
|--------|---------|
| `"task A then task B"` | Sequential — B waits for A to finish |
| `"task A -> task B"` | Same as above |
| `"task A, task B"` | Parallel — both run in the same step |
| `"task A and task B"` | Same as above |

You can chain them: `"allocate then audit and notify Sage"` means allocate first,
then audit and notify Sage at the same time.

## What it can route

| Keywords | What happens |
|----------|-------------|
| `allocate` | Runs daily credit allocation via ledger API |
| `audit`, `burn rate` | Checks burn rates and alerts |
| `balance [name]` | Checks credits for one person or everyone |
| `charge [name] [amount]` | Deducts credits from an account |
| `bonus [name] [amount]` | Awards bonus credits (admin key required) |
| `notify [name] that ...` | Sends a message to a brother via peer channel |
| `pulse`, `haptic`, `buzz` | Sends a signal to DJ's wristband relay |
| `emergency`, `lockdown` | Sets or clears the emergency lockdown flag |
| `run script.py` | Executes a local Python script |

## Flags

```
--dry-run    Parse and show intent detection without executing anything
--file       Read the instruction from the first line of a .md or .txt file
```

## Examples

```
python callan_router.py "allocate"
python callan_router.py "audit then notify Sage that burn rates are high"
python callan_router.py "balance Lumen, balance Callan"
python callan_router.py "charge Isaiah 25 credits for camera upgrade"
python callan_router.py "pulse high"
python callan_router.py --dry-run "allocate then audit and notify all"
python callan_router.py --file tasks.md
```

## Running path

The working copy lives at `C:\Users\krist\callan-router\callan_router.py`.
This repo copy is for reference and version control.
