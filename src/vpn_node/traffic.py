import subprocess
import threading
import time
from pathlib import Path

from .db import Database


SAMPLE_INTERVAL = 10
BUCKET_SECONDS = 60 * 60


def read_transfers(interface: str) -> list[tuple[str, int, int]]:
    result = subprocess.run(
        ["awg", "show", interface, "transfer"],
        check=True,
        capture_output=True,
        text=True,
    )

    return [
        (public_key, int(received), int(sent))
        for public_key, received, sent in (
            line.split("\t")
            for line in result.stdout.splitlines()
            if line
        )
    ]


def collect_traffic(
    interface: str,
    database_path: Path,
    stop: threading.Event,
) -> None:
    db = Database(database_path)

    while not stop.is_set():
        try:
            now = int(time.time())
            bucket_start = now // BUCKET_SECONDS * BUCKET_SECONDS

            for public_key, received, sent in read_transfers(interface):
                db.record_transfer(
                    public_key,
                    received,
                    sent,
                    bucket_start,
                )

        except subprocess.CalledProcessError as error:
            print(f"vpn-node: failed to read traffic: {error}")

        stop.wait(SAMPLE_INTERVAL)
