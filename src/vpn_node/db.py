import sqlite3
import ipaddress
import time
from pathlib import Path

from .model import Peer


class Database:
    def __init__(self, path: Path):
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row

    def initialize(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS peers (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                public_key TEXT NOT NULL UNIQUE,
                address TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS enrollments (
                token_hash TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                expires_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS traffic_hourly (
                peer_name TEXT NOT NULL,
                bucket_start INTEGER NOT NULL,
                received_bytes INTEGER NOT NULL DEFAULT 0,
                sent_bytes INTEGER NOT NULL DEFAULT 0,

                PRIMARY KEY (peer_name, bucket_start)
            );

            CREATE TABLE IF NOT EXISTS traffic_state (
                public_key TEXT PRIMARY KEY,
                received_bytes INTEGER NOT NULL,
                sent_bytes INTEGER NOT NULL
            );
            """
        )
        self.connection.commit()

    def list_peers(self) -> list[Peer]:
        rows = self.connection.execute(
            "SELECT id, name, public_key, address FROM peers ORDER BY id"
        ).fetchall()

        return [
            Peer(
                id=row["id"],
                name=row["name"],
                public_key=row["public_key"],
                address=row["address"],
            )
            for row in rows
        ]

    def add_peer(self, name: str, public_key: str, address: str) -> Peer:
        cursor = self.connection.execute(
            """
            INSERT INTO peers (name, public_key, address)
            VALUES (?, ?, ?)
            """,
            (name, public_key, address),
        )
        self.connection.commit()

        return Peer(
            id=cursor.lastrowid,
            name=name,
            public_key=public_key,
            address=address,
        )

    def remove_peer(self, name: str) -> bool:
        self.connection.execute("BEGIN IMMEDIATE")

        try:
            peer = self.connection.execute(
                "SELECT public_key FROM peers WHERE name = ?",
                (name,),
            ).fetchone()

            if peer is None:
                self.connection.rollback()
                return False

            self.connection.execute(
                "DELETE FROM traffic_hourly WHERE peer_name = ?",
                (name,),
            )
            self.connection.execute(
                "DELETE FROM traffic_state WHERE public_key = ?",
                (peer["public_key"],),
            )
            self.connection.execute(
                "DELETE FROM peers WHERE name = ?",
                (name,),
            )

            self.connection.commit()
            return True

        except Exception:
            self.connection.rollback()
            raise

    def rename_peer(self, old_name: str, new_name: str) -> bool:
        self.connection.execute("BEGIN IMMEDIATE")

        try:
            peer = self.connection.execute(
                "SELECT 1 FROM peers WHERE name = ?",
                (old_name,),
            ).fetchone()

            if peer is None:
                self.connection.rollback()
                return False

            conflict = self.connection.execute(
                """
                SELECT 1 FROM peers WHERE name = ?
                UNION ALL
                SELECT 1 FROM enrollments WHERE name = ?
                LIMIT 1
                """,
                (new_name, new_name),
            ).fetchone()

            if conflict is not None:
                raise ValueError(f"name {new_name!r} already exists")

            self.connection.execute(
                "UPDATE peers SET name = ? WHERE name = ?",
                (new_name, old_name),
            )
            self.connection.execute(
                "UPDATE traffic_hourly SET peer_name = ? WHERE peer_name = ?",
                (new_name, old_name),
            )

            self.connection.commit()
            return True

        except Exception:
            self.connection.rollback()
            raise

    def add_enrollment(
        self,
        name: str,
        token_hash: str,
        expires_at: int,
    ) -> None:
        now = int(time.time())

        with self.connection:
            self.connection.execute(
                "DELETE FROM enrollments WHERE expires_at <= ?",
                (now,),
            )
            self.connection.execute(
                "DELETE FROM enrollments WHERE name = ?",
                (name,),
            )
            self.connection.execute(
                """
                INSERT INTO enrollments (token_hash, name, expires_at)
                VALUES (?, ?, ?)
                """,
                (token_hash, name, expires_at),
            )

    def register_peer(
        self,
        token_hash: str,
        public_key: str,
        instance_address: str,
    ) -> Peer | None:
        now = int(time.time())
        interface = ipaddress.ip_interface(instance_address)
        network = interface.network
        server_address = str(interface.ip)

        self.connection.execute("BEGIN IMMEDIATE")

        try:
            self.connection.execute(
                "DELETE FROM enrollments WHERE expires_at <= ?",
                (now,),
            )

            enrollment = self.connection.execute(
                """
                SELECT name
                FROM enrollments
                WHERE token_hash = ?
                """,
                (token_hash,),
            ).fetchone()

            if enrollment is None:
                self.connection.rollback()
                return None

            used_addresses = {
                row["address"]
                for row in self.connection.execute(
                    "SELECT address FROM peers"
                )
            }

            address = next(
                (
                    str(address)
                    for address in network.hosts()
                    if str(address) != server_address
                    and str(address) not in used_addresses
                ),
                None,
            )

            if address is None:
                raise RuntimeError("vpn-node: no free peer addresses")

            cursor = self.connection.execute(
                """
                INSERT INTO peers (name, public_key, address)
                VALUES (?, ?, ?)
                """,
                (enrollment["name"], public_key, address),
            )

            self.connection.execute(
                "DELETE FROM enrollments WHERE token_hash = ?",
                (token_hash,),
            )

            self.connection.commit()

            return Peer(
                id=cursor.lastrowid,
                name=enrollment["name"],
                public_key=public_key,
                address=address,
            )

        except Exception:
            self.connection.rollback()
            raise

    def peer_exists(self, name: str) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM peers WHERE name = ?",
            (name,),
        ).fetchone() is not None

    def record_transfer(
        self,
        public_key: str,
        received_bytes: int,
        sent_bytes: int,
        bucket_start: int,
    ) -> None:
        self.connection.execute("BEGIN IMMEDIATE")

        try:
            peer = self.connection.execute(
                "SELECT name FROM peers WHERE public_key = ?",
                (public_key,),
            ).fetchone()

            if peer is None:
                self.connection.rollback()
                return

            state = self.connection.execute(
                """
                SELECT received_bytes, sent_bytes
                FROM traffic_state
                WHERE public_key = ?
                """,
                (public_key,),
            ).fetchone()

            if state is None:
                received_delta = received_bytes
                sent_delta = sent_bytes
            else:
                received_delta = (
                    received_bytes - state["received_bytes"]
                    if received_bytes >= state["received_bytes"]
                    else received_bytes
                )
                sent_delta = (
                    sent_bytes - state["sent_bytes"]
                    if sent_bytes >= state["sent_bytes"]
                    else sent_bytes
                )

            self.connection.execute(
                """
                INSERT INTO traffic_hourly (
                    peer_name,
                    bucket_start,
                    received_bytes,
                    sent_bytes
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT (peer_name, bucket_start) DO UPDATE SET
                    received_bytes = received_bytes + excluded.received_bytes,
                    sent_bytes = sent_bytes + excluded.sent_bytes
                """,
                (
                    peer["name"],
                    bucket_start,
                    received_delta,
                    sent_delta,
                ),
            )

            self.connection.execute(
                """
                INSERT INTO traffic_state (
                    public_key,
                    received_bytes,
                    sent_bytes
                )
                VALUES (?, ?, ?)
                ON CONFLICT (public_key) DO UPDATE SET
                    received_bytes = excluded.received_bytes,
                    sent_bytes = excluded.sent_bytes
                """,
                (public_key, received_bytes, sent_bytes),
            )

            self.connection.commit()

        except Exception:
            self.connection.rollback()
            raise

    def traffic_for_address(self, address: str) -> tuple[int, int] | None:
        row = self.connection.execute(
            """
            SELECT
                COALESCE(SUM(t.received_bytes), 0) AS received_bytes,
                COALESCE(SUM(t.sent_bytes), 0) AS sent_bytes
            FROM peers p
            LEFT JOIN traffic_hourly t ON t.peer_name = p.name
            WHERE p.address = ?
            GROUP BY p.id
            """,
            (address,),
        ).fetchone()

        if row is None:
            return None

        return row["received_bytes"], row["sent_bytes"]

    def traffic_summary(self) -> list[tuple[str, str, int, int]]:
        rows = self.connection.execute(
            """
            SELECT
                p.name,
                p.address,
                COALESCE(SUM(t.received_bytes), 0) AS received_bytes,
                COALESCE(SUM(t.sent_bytes), 0) AS sent_bytes
            FROM peers p
            LEFT JOIN traffic_hourly t ON t.peer_name = p.name
            GROUP BY p.id
            ORDER BY p.id
            """
        ).fetchall()

        return [
            (
                row["name"],
                row["address"],
                row["received_bytes"],
                row["sent_bytes"],
            )
            for row in rows
        ]
