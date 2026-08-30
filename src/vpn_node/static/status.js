const node = document.querySelector("#node");
const state = document.querySelector("#state");
const traffic = document.querySelector("#traffic");
const download = document.querySelector("#download");
const upload = document.querySelector("#upload");

node.textContent = location.hostname;

function formatBytes(bytes) {
    const units = ["B", "KB", "MB", "GB", "TB"];

    let value = bytes;
    let unit = 0;

    while (value >= 1000 && unit < units.length - 1) {
        value /= 1000;
        unit++;
    }

    const digits = unit === 0 ? 0 : value >= 100 ? 0 : value >= 10 ? 1 : 2;

    return `${value.toFixed(digits)} ${units[unit]}`;
}

function showUnavailable() {
    state.textContent = "UNAVAILABLE";
    state.className = "unavailable";
    traffic.hidden = true;
}

async function loadStatus() {
    try {
        const response = await fetch("/status/data", {
            cache: "no-store",
        });

        if (!response.ok) {
            showUnavailable();
            return;
        }

        const data = await response.json();

        if (data.state !== "online") {
            showUnavailable();
            return;
        }

        state.textContent = "ONLINE";
        state.className = "online";

        download.textContent = formatBytes(
            data.traffic.download_bytes
        );

        upload.textContent = formatBytes(
            data.traffic.upload_bytes
        );

        traffic.hidden = false;
    } catch {
        showUnavailable();
    }
}

loadStatus();
