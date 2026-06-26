import os
import time
from datetime import datetime

from .main import app, init_db, run_due_reminders


def interval_seconds():
    raw = os.environ.get("REMINDER_SCAN_INTERVAL_SECONDS", "3600")
    try:
        value = int(raw)
    except ValueError:
        value = 3600
    return max(value, 60)


def scan_once():
    with app.app_context():
        init_db()
        stats = run_due_reminders()
    stamp = datetime.now().isoformat(timespec="seconds")
    print(
        "[{}] reminders scanned={} matched={} sent={} failed={}".format(
            stamp,
            stats["scanned"],
            stats["matched"],
            stats["sent"],
            stats["failed"],
        ),
        flush=True,
    )


def main():
    if os.environ.get("REMINDER_WORKER_ONCE") == "1":
        scan_once()
        return

    delay = interval_seconds()
    while True:
        scan_once()
        time.sleep(delay)


if __name__ == "__main__":
    main()
