import argparse
import threading
import os
import subprocess
from pathlib import Path
import hashlib
import secrets
import time
import uvicorn

from .web import create_app

from .config import (
    generate_instance,
    load_instance,
    render_server_config,
    write_instance,
    write_server_config,
)
from .db import Database

from .traffic import collect_traffic

STATE_DIR = Path("/var/lib/vpn-node")
INSTANCE_PATH = STATE_DIR / "instance.json"
DATABASE_PATH = STATE_DIR / "state.db"
PRIVATE_KEY_PATH = STATE_DIR / "server.key"
SERVICE_PATH = Path("/etc/systemd/system/vpn-node.service")
DOMAIN_PATH = Path("/etc/vpn-node/domain")

AWG_CONFIG_DIR = Path("/etc/amnezia/amneziawg")

ENROLLMENT_LIFETIME = 24 * 60 * 60


def require_root() -> None:
    if os.geteuid() != 0:
        raise SystemExit("vpn-node: must be run as root")

def require_initialized() -> None:
    if not all(
        path.exists()
        for path in (INSTANCE_PATH, DATABASE_PATH, PRIVATE_KEY_PATH)
    ):
        raise SystemExit("vpn-node: not initialized")


def render() -> None:
    instance = load_instance(INSTANCE_PATH)

    db = Database(DATABASE_PATH)
    peers = db.list_peers()

    private_key = PRIVATE_KEY_PATH.read_text().strip()

    content = render_server_config(instance, private_key, peers)
    path = AWG_CONFIG_DIR / f"{instance.interface}.conf"

    write_server_config(path, content)


def generate_private_key() -> str:
    result = subprocess.run(
        ["awg", "genkey"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def public_key(private_key: str) -> str:
    result = subprocess.run(
        ["awg", "pubkey"],
        input=private_key,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()

def sync_interface(interface: str) -> None:
    stripped = subprocess.run(
        ["awg-quick", "strip", interface],
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    subprocess.run(
        ["awg", "syncconf", interface, "/dev/stdin"],
        input=stripped,
        check=True,
        text=True,
    )

def register_peer(token: str, peer_public_key: str) -> dict | None:
    instance = load_instance(INSTANCE_PATH)
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    db = Database(DATABASE_PATH)
    peer = db.register_peer(token_hash, peer_public_key, instance.address)

    if peer is None:
        return None

    render()
    sync_interface(instance.interface)

    server_private_key = PRIVATE_KEY_PATH.read_text().strip()

    return {
        "name": peer.name,
        "address": peer.address,
        "server_public_key": public_key(server_private_key),
        "listen_port": instance.listen_port,
        "awg": instance.awg,
    }


def get_status(address: str) -> dict:
    db = Database(DATABASE_PATH)
    traffic = db.traffic_for_address(address)

    if traffic is None:
        return {
            "state": "unavailable",
        }

    received_bytes, sent_bytes = traffic

    return {
        "state": "online",
        "traffic": {
            "download_bytes": sent_bytes,
            "upload_bytes": received_bytes,
        },
    }


def enroll(name: str) -> None:
    require_root()
    require_initialized()

    db = Database(DATABASE_PATH)

    if db.peer_exists(name):
        raise SystemExit(f"vpn-node: peer {name!r} already exists")

    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = int(time.time()) + ENROLLMENT_LIFETIME

    db.add_enrollment(name, token_hash, expires_at)

    domain = DOMAIN_PATH.read_text().strip()
    print(f"https://{domain}/enroll/{token}")


def init() -> None:
    require_root()

    if any(
        path.exists()
        for path in (INSTANCE_PATH, DATABASE_PATH, PRIVATE_KEY_PATH)
    ):
        raise SystemExit("vpn-node: already initialized")

    instance = generate_instance()
    private_key = generate_private_key()

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.chmod(0o700)

    write_instance(INSTANCE_PATH, instance)
    INSTANCE_PATH.chmod(0o600)

    PRIVATE_KEY_PATH.touch(mode=0o600)
    PRIVATE_KEY_PATH.write_text(private_key + "\n")

    db = Database(DATABASE_PATH)
    db.initialize()
    DATABASE_PATH.chmod(0o600)

    render()
    install_service()

    print("vpn-node initialized")
    print(f"interface:  {instance.interface}")
    print(f"address:    {instance.address}")
    print(f"port:       {instance.listen_port}")
    print(f"public key: {public_key(private_key)}")

def install_service() -> None:
    SERVICE_PATH.write_text(
        """\
[Unit]
Description=vpn-node
After=network-online.target vpn-node-firewall.service awg-quick@awg0.service
Wants=network-online.target
Requires=vpn-node-firewall.service awg-quick@awg0.service

[Service]
Type=simple
ExecStart=/usr/local/bin/vpn-node serve
Restart=on-failure

[Install]
WantedBy=multi-user.target
"""
    )

    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(
        ["systemctl", "enable", "awg-quick@awg0.service", "vpn-node.service"],
        check=True,
    )

def serve() -> None:
    require_root()
    require_initialized()

    instance = load_instance(INSTANCE_PATH)

    traffic_stop = threading.Event()
    traffic_thread = threading.Thread(
        target=collect_traffic,
        args=(instance.interface, DATABASE_PATH, traffic_stop),
        daemon=True,
    )
    traffic_thread.start()

    try:
        app = create_app(register_peer, get_status)
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=8080,
            access_log=False,
            proxy_headers=True,
            forwarded_allow_ips="127.0.0.1",
        )
    finally:
        traffic_stop.set()
        traffic_thread.join(timeout=2)


def run() -> None:
    require_root()

    subprocess.run(
        ["systemctl", "start", "vpn-node.service"],
        check=True,
    )

def update() -> None:
    require_root()

    root = Path("/usr/local/bin/vpn-node").resolve().parents[2]

    subprocess.run(
        ["git", "-C", root, "pull", "--ff-only"],
        check=True,
    )

    subprocess.run(
        [
            "uv", "sync",
            "--frozen",
            "--no-editable",
            "--reinstall-package", "vpn-node",
            "--project", root,
        ],
        check=True,
    )

    static = root / "src/vpn_node/static"

    subprocess.run(
        ["install", "-m", "0644", static / "status.html", "/usr/share/vpn-node/status.html"],
        check=True,
    )
    subprocess.run(
        ["install", "-m", "0644", static / "style.css", "/usr/share/vpn-node/assets/style.css"],
        check=True,
    )
    subprocess.run(
        ["install", "-m", "0644", static / "status.js", "/usr/share/vpn-node/assets/status.js"],
        check=True,
    )

    subprocess.run(
        ["systemctl", "restart", "vpn-node.service"],
        check=True,
    )

    print("vpn-node updated")


def main() -> None:
    parser = argparse.ArgumentParser(prog="vpn-node")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("init")
    commands.add_parser("render")
    commands.add_parser("run")
    commands.add_parser("update")
    commands.add_parser("serve")
    enroll_parser = commands.add_parser("enroll")
    enroll_parser.add_argument("name")

    args = parser.parse_args()

    if args.command == "init":
        init()
    elif args.command == "render":
        require_root()
        render()
    elif args.command == "run":
        run()
    elif args.command == "serve":
        serve()
    elif args.command == "enroll":
        enroll(args.name)
    elif args.command == "update":
        update()
