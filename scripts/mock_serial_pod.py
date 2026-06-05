"""
mock_serial_pod.py — fake ESP32 environment pod for testing without hardware.

Serves on TCP localhost:7905. Pushes JSON telemetry every INTERVAL seconds,
same format the real DHT22/BH1750 pod will use:
  {"temp": 22.4, "humidity": 51.2, "lux": 340, "ts": 1234567890}

HOW TO START
  py -3.12 mock_serial_pod.py

OPTIONS (env vars)
  POD_PROFILE  — "normal" (default), "hot", "cold", "humid", "dry", "dark"
  POD_INTERVAL — seconds between readings, default 2
  POD_PORT     — TCP port, default 7905

HOW TO CONNECT
  Any script that would normally open a serial COM port can instead open a
  TCP socket to localhost:7905 and read newline-delimited JSON.

  Python example:
    import socket, json
    s = socket.create_connection(("localhost", 7905))
    for line in s.makefile():
        data = json.loads(line)
        print(data["temp"], data["humidity"], data["lux"])
"""

import asyncio
import json
import os
import random
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("mock_serial_pod")

PORT     = int(os.getenv("POD_PORT", "7907"))
INTERVAL = float(os.getenv("POD_INTERVAL", "2"))
PROFILE  = os.getenv("POD_PROFILE", "normal").strip().lower()

# Sensor ranges per profile: (temp_base, temp_jitter, hum_base, hum_jitter, lux_base, lux_jitter)
PROFILES = {
    "normal": (22.0, 1.5, 51.0, 5.0, 340, 60),
    "hot":    (34.0, 2.0, 38.0, 4.0, 650, 80),
    "cold":   (14.0, 1.0, 60.0, 4.0, 280, 50),
    "humid":  (24.0, 1.0, 82.0, 5.0, 200, 40),
    "dry":    (26.0, 1.5, 22.0, 3.0, 480, 70),
    "dark":   (21.0, 1.0, 55.0, 4.0,  15,  8),
}

if PROFILE not in PROFILES:
    log.warning("Unknown profile '%s', falling back to 'normal'", PROFILE)
    PROFILE = "normal"

t_base, t_jit, h_base, h_jit, l_base, l_jit = PROFILES[PROFILE]

_clients: set[asyncio.StreamWriter] = set()


def _reading() -> bytes:
    payload = {
        "temp":     round(t_base + random.uniform(-t_jit, t_jit), 1),
        "humidity": round(h_base + random.uniform(-h_jit, h_jit), 1),
        "lux":      max(0, int(l_base + random.uniform(-l_jit, l_jit))),
        "ts":       int(time.time()),
        "profile":  PROFILE,
        "mock":     True,
    }
    return (json.dumps(payload) + "\n").encode()


async def _push_loop() -> None:
    while True:
        await asyncio.sleep(INTERVAL)
        if not _clients:
            continue
        data = _reading()
        dead = set()
        for writer in list(_clients):
            try:
                writer.write(data)
                await writer.drain()
            except Exception:
                dead.add(writer)
        _clients.difference_update(dead)


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    addr = writer.get_extra_info("peername")
    log.info("Client connected: %s", addr)
    _clients.add(writer)
    # Send one reading immediately so the client knows it's alive
    try:
        writer.write(_reading())
        await writer.drain()
        await reader.read(-1)   # wait until client disconnects
    except Exception:
        pass
    finally:
        _clients.discard(writer)
        log.info("Client disconnected: %s", addr)


async def main() -> None:
    server = await asyncio.start_server(_handle, "127.0.0.1", PORT)
    log.info(
        "Mock ESP32 pod running — profile: %s | interval: %ss | port: %d",
        PROFILE, INTERVAL, PORT,
    )
    log.info("Connect: socket.create_connection(('localhost', %d))", PORT)
    async with server:
        asyncio.create_task(_push_loop())
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Pod offline.")
