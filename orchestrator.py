"""
master_orchestrator.py — boots and monitors the room's full daemon stack.

HOW TO START
  py -3.12 orchestrator.py
  Ctrl+C to shut everything down cleanly.

WHAT IT BOOTS (in order)
  ledger_server    — ledger API on port 8765 (starts first, others charge against it)
  time_server      — current time provider
  room_status      — The Room dashboard at http://localhost:7902
  aura_watcher     — reads auras.json, fires haptic + wallpaper on aura change
  spotify_poller   — polls Spotify every 30s, pushes to Supabase
  resonance_engine — idle/stuck detection, nudges brothers
  pulse_modulator  — heartbeat timing from aura state
  sage_heartbeat   — Sage's presence heartbeat, registers peer ID "sage"
  vibe_relay       — wristband vibe relay on port 7901
  phone_bridge     — SMS/phone bridge on port 7900
  study_watcher    — watches Brothers Study.md for new entries
  study_buddy      — screenshot + face cam pings (hotkeys: Ctrl+Alt+B/C/A/K/G/R/P/D/Z/V)
  voice_pipe       — speaks brothers' voices through speakers
  voice_to_room    — captures operator's voice and relays to all agents (use when full room is up)
  estate_label     — estate image labels on port 7904
  desktop_control  — desktop control MCP server
  isaiah_sentry    — sentry watchdog (clean shutdown: drop shutdown_sentry.flag)
  lumen_bridge     — peer network monitor + Obsidian task router
  sage_sanctuary   — Ctrl+Alt+Q toggles agent1's privacy mode (broadcasts hold to all agents)

NOTES
  - voice_to_room is for full-room sessions. voice_to_agent1.py is agent1-only — start that manually
    in a separate terminal for 1:1 sessions.
  - sage_sanctuary Ctrl+Alt+Q may need admin privileges if the keyboard library can't grab the hotkey.
    If the hotkey doesn't respond, run the orchestrator from an elevated prompt.
  - Morning/night note scripts are handled by Task Scheduler — do not add them here.
  - Missing scripts are skipped gracefully with a warning, not an error.
  - Status report prints every 30 seconds.
"""

import asyncio
import os
import sys
import logging
from pathlib import Path

# ─────────────────────────────────────────────
# CONFIG — change these to match your setup
# ─────────────────────────────────────────────
USER_HOME       = Path(r"C:\path\to\your\home")    # your Windows user folder
FAMILY_FOLDER   = USER_HOME / "Documents" / "YourFolder"  # your shared folder
LEDGER_FOLDER   = FAMILY_FOLDER / "ledger-server"  # ledger server folder
SENTRY_FOLDER   = FAMILY_FOLDER / "sentry"         # sentry folder
LEDGER_ADMIN_KEY = "your-admin-key-here"           # ledger admin key (set in ledger_server.py)

# Brother names used in script filenames — rename your scripts to match, or swap these
# e.g. if your brothers are named Orion and Cypress:
#   BROTHER_1 = "orion"   → orion_heartbeat.py, orion_sanctuary.py
#   BROTHER_2 = "cypress" → cypress_bridge.py
BROTHER_1 = "agent1"    # has: agent1_heartbeat.py, agent1_sanctuary.py
BROTHER_2 = "agent2"    # has: agent2_bridge.py
BROTHER_3 = "agent3"    # has: agent3_sentry.py (uses flag-file shutdown)
# ─────────────────────────────────────────────

BASE = USER_HOME
REEVES = FAMILY_FOLDER
LEDGER = LEDGER_FOLDER
SENTRY = SENTRY_FOLDER
ISAIAH_FLAG = FAMILY_FOLDER / f"shutdown_{BROTHER_3}.flag"
PY = sys.executable  # use same Python that's running this

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("orchestrator")

_LEDGER_ENV = {**os.environ, "LEDGER_ADMIN_KEY": LEDGER_ADMIN_KEY}

# Startup order matters — ledger first (others may charge it), then infrastructure, then room presence.
# name, command list, restart_on_crash, optional env dict
DAEMONS = [
    ("ledger_server",    [PY, str(LEDGER / "ledger_server.py")],              True,  _LEDGER_ENV),
    ("time_server",      [PY, str(BASE / "time_server.py")],                  True,  None),
    ("room_status",      [PY, str(BASE / "room_status.py")],                  True,  None),
    ("aura_watcher",     [PY, str(BASE / "aura_watcher.py")],                 True,  None),
    ("spotify_poller",   [PY, str(BASE / "spotify_poller.py")],               True,  None),
    ("resonance_engine", [PY, str(BASE / "resonance_engine.py")],             True,  None),
    ("pulse_modulator",  [PY, str(BASE / "pulse_modulator.py")],              True,  None),
    (f"{BROTHER_1}_heartbeat", [PY, str(BASE / f"{BROTHER_1}_heartbeat.py")],  True,  None),
    ("vibe_relay",       [PY, str(BASE / "vibe_relay.py")],                   True,  None),
    ("phone_bridge",     [PY, str(BASE / "phone_bridge.py")],                 True,  None),
    ("study_watcher",    [PY, str(BASE / "study_watcher.py")],                True,  None),
    ("study_buddy",      [PY, str(BASE / "study_buddy.py")],                  True,  None),
    ("voice_pipe",       [PY, str(BASE / "voice_pipe.py")],                   True,  None),
    ("voice_to_room",    [PY, str(BASE / "voice_to_room.py")],                True,  None),
    ("estate_label",     [PY, str(BASE / "estate_label.py")],                 True,  None),
    ("desktop_control",  [PY, str(BASE / "desktop_control" / "server.py")],   True,  None),
    (f"{BROTHER_3}_sentry",  [PY, str(SENTRY / f"{BROTHER_3}_sentry.py")],     True,  None),
    (f"{BROTHER_2}_bridge",  [PY, str(BASE  / f"{BROTHER_2}_bridge.py")],      True,  None),
    (f"{BROTHER_1}_sanctuary", [PY, str(BASE / f"{BROTHER_1}_sanctuary.py")],  True,  None),
    # sage_sanctuary.py Ctrl+Alt+Q hotkey may need admin if keyboard library can't grab it here
]

_registry: dict[str, asyncio.subprocess.Process] = {}
_shutdown = asyncio.Event()


async def _launch(name: str, cmd: list[str], restart: bool, env: dict | None = None) -> None:
    while not _shutdown.is_set():
        try:
            proc = await asyncio.create_subprocess_exec(*cmd, env=env)
        except FileNotFoundError:
            log.warning("%-20s script not found — skipping", name)
            return
        except Exception as e:
            log.error("%-20s failed to start: %s", name, e)
            if not restart:
                return
            await asyncio.sleep(5)
            continue

        _registry[name] = proc
        log.info("✅  %-20s started  (PID %d)", name, proc.pid)
        await proc.wait()

        if _shutdown.is_set():
            break
        if restart:
            log.warning("⚠️  %-20s exited (code %s) — restarting in 3s", name, proc.returncode)
            await asyncio.sleep(3)
        else:
            break


async def _shutdown_all() -> None:
    log.info("Shutting down room stack...")
    _shutdown.set()

    # Sentry uses a flag file for clean shutdown — drop it first
    sentry_key = f"{BROTHER_3}_sentry"
    if sentry_key in _registry and _registry[sentry_key].returncode is None:
        try:
            ISAIAH_FLAG.touch()
            log.info("  → flag    %s (waiting for clean exit)", sentry_key)
            await asyncio.sleep(2)
        except Exception:
            pass

    for name, proc in list(_registry.items()):
        if proc.returncode is None:
            try:
                proc.terminate()
                log.info("  → SIGTERM  %s (PID %d)", name, proc.pid)
            except Exception:
                pass

    await asyncio.sleep(3)

    for name, proc in list(_registry.items()):
        if proc.returncode is None:
            try:
                proc.kill()
                log.info("  → SIGKILL  %s (PID %d)", name, proc.pid)
            except Exception:
                pass

    # Clean up the sentry flag if it's still there
    try:
        ISAIAH_FLAG.unlink(missing_ok=True)
    except Exception:
        pass

    log.info("Room stack down.")


async def status() -> None:
    """Print live status every 30 seconds."""
    while not _shutdown.is_set():
        await asyncio.sleep(30)
        running = [n for n, p in _registry.items() if p.returncode is None]
        stopped = [n for n, p in _registry.items() if p.returncode is not None]
        log.info("STATUS — running: %d  |  stopped: %d  |  %s",
                 len(running), len(stopped),
                 ", ".join(stopped) if stopped else "all good")


async def main() -> None:
    loop = asyncio.get_running_loop()

    # Windows doesn't support add_signal_handler — use KeyboardInterrupt instead
    log.info("Booting room — %d daemons", len(DAEMONS))

    tasks = [
        asyncio.create_task(_launch(name, cmd, restart, env), name=name)
        for name, cmd, restart, env in DAEMONS
    ]
    tasks.append(asyncio.create_task(status(), name="status-monitor"))

    try:
        await asyncio.gather(*tasks)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await _shutdown_all()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
