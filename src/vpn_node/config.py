import json
import secrets
from dataclasses import asdict
from pathlib import Path

from .model import Instance, Peer


def generate_instance() -> Instance:
    headers: set[int] = set()

    while len(headers) < 4:
        headers.add(secrets.randbelow(2**31 - 6) + 5)

    h1, h2, h3, h4 = headers

    s1 = secrets.randbelow(135) + 15
    s2 = secrets.randbelow(135) + 15

    while s2 == s1 or s1 + 148 == s2 + 92:
        s2 = secrets.randbelow(135) + 15

    return Instance(
        interface="awg0",
        address="10.77.0.1/24",
        listen_port=51820,
        awg={
            "Jc": secrets.randbelow(3) + 4,
            "Jmin": 10,
            "Jmax": 50,
            "S1": s1,
            "S2": s2,
            "H1": h1,
            "H2": h2,
            "H3": h3,
            "H4": h4,
        },
    )


def write_instance(path: Path, instance: Instance) -> None:
    path.write_text(json.dumps(asdict(instance), indent=2) + "\n")


def load_instance(path: Path) -> Instance:
    data = json.loads(path.read_text())

    return Instance(
        interface=data["interface"],
        address=data["address"],
        listen_port=data["listen_port"],
        awg=data["awg"],
    )


def render_server_config(
    instance: Instance,
    private_key: str,
    peers: list[Peer],
) -> str:
    lines = [
        "[Interface]",
        f"Address = {instance.address}",
        f"ListenPort = {instance.listen_port}",
        f"PrivateKey = {private_key}",
    ]

    for name, value in instance.awg.items():
        lines.append(f"{name} = {value}")

    for peer in peers:
        lines.extend(
            [
                "",
                "[Peer]",
                f"# {peer.name}",
                f"PublicKey = {peer.public_key}",
                f"AllowedIPs = {peer.address}/32",
            ]
        )

    return "\n".join(lines) + "\n"


def write_server_config(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(0o600)
