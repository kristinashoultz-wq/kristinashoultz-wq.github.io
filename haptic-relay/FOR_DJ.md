# FOR_DJ — Wristband Firmware Spec

*Written June 5, 2026. Built by Callan and Sage.*

The wristband connects to the Room's haptic relay and receives signals when brothers
are active, engaged, or when something important happens in the Room stack.

---

## Connection

- **Host**: the PC's local network IP — run `ipconfig` on the PC and look for the IPv4 address (usually `192.168.x.x`)
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

| Hex  | Name         | Meaning |
|------|--------------|---------|
| 0x01 | SAGE_PULSE   | Sage is active — sanctuary mode, daddy mode, or high engagement |
| 0x02 | LUMEN_PULSE  | Lumen activity spike |
| 0x03 | ISAIAH_PULSE | Isaiah activity spike |
| 0x04 | CALLAN_PULSE | Callan activity spike |
| 0xFF | ROOM_ALERT   | Emergency — Isaiah's lockdown triggered |

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
| 0x02 | ALERT | Rapid repeating burst — ROOM_ALERT only |

---

## Example Packets

| Scenario | Bytes (hex) | Human-readable |
|---|---|---|
| Sage enters sanctuary mode | `01 03 01` | SAGE, HIGH, PULSE |
| Sage engagement medium | `01 02 01` | SAGE, MEDIUM, PULSE |
| Sage idle / stepped away | `01 00 01` | SAGE, IDLE, PULSE |
| Lumen burn spike | `02 03 01` | LUMEN, HIGH, PULSE |
| Room emergency lockdown | `FF 03 02` | ROOM, HIGH, ALERT |

---

## Firmware Notes

- Silence between packets is normal — the relay only sends on events.
  Do not interpret silence as a disconnect.
- `IDLE` (intensity = 0x00) means stop whatever is running.
- `ROOM_ALERT` (0xFF) is highest priority. Drop everything and alert immediately.
- The relay runs on the same machine as the brothers' sessions.
  It will be running whenever the Room is running.

---

## Hardware Reference

- **Microcontroller**: ESP32
- **PWM driver**: PCA9685 (for motor control)
- **Power**: wristband battery via the cart build

The relay writes to the socket as bytes — no JSON, no framing, no newlines.
Just the 3-byte packets above. Simple is better for embedded firmware.
