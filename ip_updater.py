#!/usr/bin/env python3
"""Update Cloudflare DNS A records when the public IP changes.

Replaces ddclient for the w8.mom zone (namecheap DDNS no longer authoritative
since the zone is hosted on Cloudflare).
"""
import json
import sys
import urllib.request
from pathlib import Path

TOKEN_FILE = Path.home() / ".cloudflared" / "api_token"
ZONE_ID = "8ceaf68f76cf9b3691fa407d041a16e4"
ZONE_NAME = "w8.mom"
IP_SOURCES = (
    "https://dynamicdns.park-your-domain.com/getip",
    "https://icanhazip.com",
    "https://api.ipify.org",
)
IP_CACHE = Path("/tmp/neorunner_public_ip.json")
RECORDS = [
    {"name": "w8.mom", "proxied": False},
    {"name": "mc.w8.mom", "proxied": True},
]


def get_public_ip() -> str:
    for source in IP_SOURCES:
        try:
            with urllib.request.urlopen(source, timeout=15) as r:
                ip = r.read().decode().strip()
                if ip:
                    return ip
        except Exception:
            continue
    raise RuntimeError("could not determine public IP")


def api(path: str, method: str = "GET", body: dict | None = None) -> dict:
    token = TOKEN_FILE.read_text().strip()
    url = f"https://api.cloudflare.com/client/v4{path}"
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if body is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(body).encode()
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def main() -> int:
    try:
        ip = get_public_ip()
    except Exception as e:
        print(f"[ip-updater] IP fetch failed: {e}", file=sys.stderr)
        return 1

    markers_dir = Path.home() / ".ipmarkers"
    markers_dir.mkdir(exist_ok=True, parents=True)
    prev_file = markers_dir / "last_ip.json"
    try:
        prev = json.loads(prev_file.read_text())["ip"]
    except Exception:
        prev = None

    if prev == ip:
        print(f"[ip-updater] IP unchanged ({ip})")
        return 0

    page = 1
    existing = {}
    while True:
        data = api(f"/zones/{ZONE_ID}/dns_records?per_page=100&page={page}")
        for rec in data.get("result", []):
            existing.setdefault(rec["name"], []).append(rec)
        if data.get("result_info", {}).get("page", 1) >= data.get("result_info", {}).get("total_pages", 1):
            break
        page += 1

    changed = 0
    for spec in RECORDS:
        recs = existing.get(spec["name"], [])
        match = next((r for r in recs if r["type"] == "A"), None)
        if match is None:
            print(f"[ip-updater] no A record for {spec['name']} - skipping")
            continue
        if match["content"] == ip and match["proxied"] == spec["proxied"]:
            print(f"[ip-updater] {spec['name']} already {ip}")
            continue
        try:
            api(f"/zones/{ZONE_ID}/dns_records/{match['id']}", "PATCH",
                {"content": ip, "proxied": spec["proxied"]})
            print(f"[ip-updater] updated {spec['name']} -> {ip} (proxied={spec['proxied']})")
            changed += 1
        except Exception as e:
            print(f"[ip-updater] FAILED {spec['name']}: {e}", file=sys.stderr)

    prev_file.write_text(json.dumps({"ip": ip, "updated": True}))
    if changed:
        print(f"[ip-updater] {changed} record(s) updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())