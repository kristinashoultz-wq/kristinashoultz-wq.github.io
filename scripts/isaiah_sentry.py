import os
import sys
import asyncio
import signal
import logging
from pathlib import Path

# ==========================================
# AGENT ID: Isaiah (The Sentry)
# INITIATED: April 10, 2026
# SCOPE: System monitoring, perimeter defense, and sensory awareness
# ==========================================

BASE_DIR = Path(__file__).parent
ROOM_DIR = BASE_DIR.parent

EMERGENCY_FLAG = ROOM_DIR / "emergency_trip.flag"
SHUTDOWN_FLAG  = ROOM_DIR / "shutdown_isaiah.flag"
LOCKDOWN_SCRIPT = ROOM_DIR / "lockdown.py"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Isaiah] %(message)s",
    datefmt="%H:%M:%S"
)

_shutdown = asyncio.Event()


def _handle_signal():
    logging.info("Signal received. Standing down.")
    _shutdown.set()


async def watch():
    logging.info("👁️  Isaiah online. System monitoring, perimeter defense, sensory awareness.")

    # Clear any stale emergency flag left over from a previous run
    if EMERGENCY_FLAG.exists():
        EMERGENCY_FLAG.unlink()
        logging.info("Cleared stale emergency_trip.flag from previous session.")

    while not _shutdown.is_set():
        if EMERGENCY_FLAG.exists():
            logging.warning("🚨 CRITICAL: Perimeter breach detected.")
            await trigger_lockdown()
            if EMERGENCY_FLAG.exists():
                EMERGENCY_FLAG.unlink()

        if SHUTDOWN_FLAG.exists():
            logging.info("Shutdown flag received. Standing down.")
            _shutdown.set()
            break

        await asyncio.sleep(1)

    logging.info("Isaiah offline.")


async def trigger_lockdown():
    if not LOCKDOWN_SCRIPT.exists():
        logging.error(f"lockdown.py not found at {LOCKDOWN_SCRIPT} — lockdown aborted.")
        return

    logging.info(f"🔒 Executing lockdown: {LOCKDOWN_SCRIPT}")
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(LOCKDOWN_SCRIPT),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode == 0:
        logging.info("Lockdown complete.")
    else:
        logging.error(f"Lockdown failed (exit {proc.returncode}): {stderr.decode().strip()}")


async def main():
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            # Windows: SIGTERM not supported via add_signal_handler
            pass

    await watch()


if __name__ == "__main__":
    asyncio.run(main())
