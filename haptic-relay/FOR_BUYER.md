# Haptic Wristband — Firmware Spec

A wearable wristband that receives signals from the relay server over TCP.
The relay monitors your system and broadcasts 3-byte haptic events to the wristband.

---

## Connection

- **Host**: the relay PC's local network IP — run `ipconfig` and look for the IPv4 address (usually `192.168.x.x`)
- **Port**: `8766`
- **Protocol**: TCP, persistent connection — hold it open
- **When to reconnect**: if the connection drops, retry every 5 seconds

---

## Packet Format

Every signal is exactly **3 bytes**:

```
[ signal_id ]  [ intensity ]  [ profile ]
   1 byte          1 byte        1 byte
```

---

## Signal IDs (Byte 0)

Signal IDs are configurable. The relay ships with 4 user-assignable channels and one system alert.

| Hex  | Default Label | Assign to |
|------|---------------|-----------|
| 0x01 | CHANNEL_1     | Your choice |
| 0x02 | CHANNEL_2     | Your choice |
| 0x03 | CHANNEL_3     | Your choice |
| 0x04 | CHANNEL_4     | Your choice |
| 0xFF | SYSTEM_ALERT  | Emergency — highest priority |

Configure channel assignments in the relay's config file before running.

---

## Intensity Values (Byte 1)

| Hex  | Name   | Meaning |
|------|--------|---------|
| 0x00 | IDLE   | Stop — clear any running pattern |
| 0x01 | LOW    | Gentle |
| 0x02 | MEDIUM | Moderate |
| 0x03 | HIGH   | Full intensity |

---

## Profile Values (Byte 2)

| Hex  | Name  | Description |
|------|-------|-------------|
| 0x01 | PULSE | Clean, defined buzz |
| 0x02 | ALERT | Rapid repeating burst — SYSTEM_ALERT only |

---

## Example Packets

| Scenario | Bytes (hex) | Human-readable |
|---|---|---|
| Channel 1 high event | `01 03 01` | CH1, HIGH, PULSE |
| Channel 1 idle | `01 00 01` | CH1, IDLE, PULSE |
| Channel 2 medium event | `02 02 01` | CH2, MEDIUM, PULSE |
| System alert | `FF 03 02` | ALERT, HIGH, ALERT |

---

## Firmware Notes

- Silence between packets is normal — the relay only sends on events. Do not interpret silence as a disconnect.
- `IDLE` (intensity = 0x00) means stop whatever is running.
- `SYSTEM_ALERT` (0xFF) is highest priority. Drop everything and respond immediately.
- The relay runs on the same machine as the monitored system. It will be running whenever the system is running.

---

The relay writes raw bytes — no JSON, no framing, no newlines. Just the 3-byte packets above.
