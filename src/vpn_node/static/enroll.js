const button = document.querySelector("#download");
const action = document.querySelector("#action");
const status = document.querySelector("#status");
const endpoint = document.querySelector("#endpoint");

endpoint.textContent = location.hostname;

const DEFAULT_ACTION = "acquire configuration";

function fromBase64Url(value) {
    value = value.replaceAll("-", "+").replaceAll("_", "/");
    return value + "=".repeat((4 - value.length % 4) % 4);
}

async function showButtonError(message) {
    action.textContent = message;
    button.classList.add("error");

    await new Promise(resolve => setTimeout(resolve, 1600));

    action.textContent = DEFAULT_ACTION;
    button.classList.remove("error");
    button.disabled = false;
}

button.addEventListener("click", async () => {
    button.disabled = true;
    status.textContent = "";
    
    if (!crypto.subtle) {
        await showButtonError("secure connection required");
        return;
    }

    try {
        const keys = await crypto.subtle.generateKey(
            { name: "X25519" },
            true,
            ["deriveBits"]
        );

        const privateJwk = await crypto.subtle.exportKey(
            "jwk",
            keys.privateKey
        );

        const publicJwk = await crypto.subtle.exportKey(
            "jwk",
            keys.publicKey
        );

        const privateKey = fromBase64Url(privateJwk.d);
        const publicKey = fromBase64Url(publicJwk.x);

        const response = await fetch(location.pathname, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                public_key: publicKey,
            }),
        });

        const data = await response.json();

        if (response.status === 410) {
            await showButtonError("expired or already used");
            return;
        }

        if (!response.ok) {
            throw new Error(data.error || "enrollment failed");
        }

        const host = location.hostname.includes(":")
            ? `[${location.hostname}]`
            : location.hostname;

        const awg = Object.entries(data.awg)
            .map(([name, value]) => `${name} = ${value}`)
            .join("\n");

        const config = `[Interface]
PrivateKey = ${privateKey}
Address = ${data.address}/32
${awg}

[Peer]
PublicKey = ${data.server_public_key}
Endpoint = ${host}:${data.listen_port}
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
`;

        const blob = new Blob(
            [config],
            { type: "text/plain" }
        );

        const url = URL.createObjectURL(blob);

        const link = document.createElement("a");
        link.href = url;
        link.download = `awg0.conf`;
        link.click();

        URL.revokeObjectURL(url);

        action.textContent = "configuration acquired";
    } catch (error) {
        status.textContent = error.message;
        button.disabled = false;
    }
});
