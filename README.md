# vpn-node

Minimal self-hosted AmneziaWG node with browser-based client enrollment.

`vpn-node` manages an AmneziaWG server, peers, enrollment links and traffic accounting.  
The AWG data plane runs independently from the `vpn-node` control plane.

## Requirements

- Ubuntu 24.04
- domain pointing to the server
- root access

## Setup

```bash
git clone <repo> /opt/vpn-node
cd /opt/vpn-node

./setup vpn.example.com
vpn-node init
vpn-node run
````

`setup` installs and configures the required system dependencies, including AmneziaWG, nftables and Caddy.

## Add a client

```bash
vpn-node enroll <name>
```

This prints a one-time enrollment URL:

```text
https://vpn.example.com/enroll/<token>
```

Open it in a browser and download the generated AmneziaWG configuration.

The client private key is generated in the browser and never sent to the server.

## Architecture

```text
Internet
   │
   ▼
AmneziaWG / awg0
   │
   ├── existing VPN traffic
   │
   └── vpn-node
       ├── enrollment
       ├── peer management
       ├── traffic accounting
       └── status API
```

`awg0` is managed independently by `awg-quick@awg0.service`.

Restarting or breaking `vpn-node.service` does not interrupt existing VPN connections.

Persistent node state is stored in:

```text
/var/lib/vpn-node/
```

The generated AmneziaWG configuration is stored in:

```text
/etc/amnezia/amneziawg/awg0.conf
```
