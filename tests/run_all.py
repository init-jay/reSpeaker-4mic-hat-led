#!/usr/bin/env python3
"""Run every check in turn.

    uv run python tests/run_all.py

Each check is a plain script full of assertions rather than a pytest suite:
they need no dependency beyond `websockets`, and they run on a development
machine as happily as on the Pi, because nothing here touches real hardware.
"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

CHECKS = [
    ("check_frames.py", "APA102 frame construction"),
    ("check_animations.py", "animations and event mapping"),
    ("check_light.py", "Home Assistant light entity"),
    ("check_client.py", "WebSocket client and reconnect"),
]


def main() -> int:
    failed = []

    for script, description in CHECKS:
        print(f"\n=== {script} — {description} ===", flush=True)
        result = subprocess.run([sys.executable, str(HERE / script)], cwd=HERE)
        if result.returncode != 0:
            failed.append(script)

    print()
    if failed:
        print(f"FAILED: {', '.join(failed)}")
        return 1

    print(f"All {len(CHECKS)} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
