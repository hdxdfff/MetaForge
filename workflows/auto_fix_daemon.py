#!/usr/bin/env python3
"""
Continuous Background Auto-Fix Daemon for MetaForge OS
Runs in the background and periodically applies fixes.
"""

import time
import json
import subprocess
from pathlib import Path
from datetime import datetime

ROOT = Path("D:/codex")
DATA_DIR = ROOT / "orchestrator-mvp" / "data"
LOG_FILE = ROOT / "workflows" / "auto_fix_daemon.log"
PID_FILE = ROOT / "workflows" / "auto_fix_daemon.pid"


def log(message):
    timestamp = datetime.now().isoformat()
    log_entry = f"[{timestamp}] {message}"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_entry + "\n")
    print(log_entry)


def write_pid():
    """Write current process ID to file."""
    import os

    pid = os.getpid()
    with open(PID_FILE, "w", encoding="utf-8") as f:
        f.write(str(pid))
    log(f"Daemon started with PID: {pid}")


def run_auto_fix():
    """Execute the auto-fix workflow."""
    script_path = ROOT / "workflows" / "background_auto_fix.py"

    try:
        result = subprocess.run(
            ["python", str(script_path)], capture_output=True, text=True, timeout=120
        )

        if result.returncode == 0:
            log("Auto-fix workflow executed successfully")
            return True
        else:
            log(f"Auto-fix workflow failed with code {result.returncode}")
            log(f"Error: {result.stderr}")
            return False

    except Exception as e:
        log(f"Error running auto-fix: {e}")
        return False


def main():
    """Main daemon loop."""
    log("=" * 60)
    log("Background Auto-Fix Daemon Starting")
    log("=" * 60)

    write_pid()

    cycle_count = 0

    try:
        while True:
            cycle_count += 1
            log(f"\n--- Auto-Fix Cycle #{cycle_count} ---")

            # Run the auto-fix workflow
            success = run_auto_fix()

            if success:
                log(f"Cycle #{cycle_count} completed successfully")
            else:
                log(f"Cycle #{cycle_count} completed with errors")

            # Wait before next cycle (60 seconds)
            log("Waiting 60 seconds before next cycle...")
            time.sleep(60)

    except KeyboardInterrupt:
        log("\nDaemon stopped by user")
    except Exception as e:
        log(f"\nDaemon error: {e}")
    finally:
        log("=" * 60)
        log("Background Auto-Fix Daemon Stopped")
        log("=" * 60)

        # Clean up PID file
        if PID_FILE.exists():
            PID_FILE.unlink()


if __name__ == "__main__":
    main()
