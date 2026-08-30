from dataclasses import dataclass


@dataclass(slots=True)
class Instance:
    interface: str
    address: str
    listen_port: int
    awg: dict[str, int]


@dataclass(slots=True)
class Peer:
    id: int
    name: str
    public_key: str
    address: str
