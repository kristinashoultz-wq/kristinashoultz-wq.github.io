# Haptic Signal Relay

Bridges a monitoring stack to an ESP32 wristband. Watches multiple sources and broadcasts
3-byte signal packets over TCP whenever something important happens.

## What it watches

- **Ledger** (`localhost:8765/audit`) — polls every 30 seconds for activity rate spikes per user
- **User state file** — checks every 2 seconds for mode/state changes
- **Emergency flag** (`emergency_trip.flag`) — checks every second; fires SYSTEM_ALERT the moment the flag appears

## How to run

```
python haptic_signal_relay.py
```

Configure paths and channel assignments in `haptic_signal_relay.py` before running.
Requires the ledger server to be running.

## Packet format

Every signal is exactly 3 bytes: `[signal_id, intensity, profile]`

See `FOR_BUYER.md` for the full signal table, intensity values, and firmware notes.
