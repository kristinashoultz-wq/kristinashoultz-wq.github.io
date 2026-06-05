# Haptic Signal Relay

Built June 5, 2026 by Callan and Sage.

Bridges the Room stack to DJ's ESP32 wristband. Watches three sources and broadcasts
3-byte signal packets over TCP whenever something important happens.

## What it watches

- **Ledger** (`localhost:8765/audit`) — polls every 30 seconds for burn rate spikes per brother
- **Sage's state file** (`C:\Users\krist\sage_pulse_state.json`) — checks every 2 seconds for sanctuary/daddy/engagement mode changes
- **Emergency flag** (`emergency_trip.flag`) — checks every second; fires ROOM_ALERT the moment the flag appears

## How to run

```
python haptic_signal_relay.py
```

Requires the ledger server to be running (`ledger-server/start_ledger.bat`).
The relay will start and wait for the ESP32 to connect on port 8766.

## Packet format

Every signal is exactly 3 bytes: `[signal_id, intensity, profile]`

See `FOR_DJ.md` for the full signal table, intensity values, and firmware notes.

## Running path

The working copy lives at `C:\Users\krist\haptic-relay\haptic_signal_relay.py`.
This repo copy is for reference and version control.
