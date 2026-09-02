#!/usr/bin/env python3
"""Tiny read-only metrics sidecar for the LANmine dashboard.

Holds the Portainer token (server-side only), polls the Docker API via Portainer,
and exposes a sanitized, tokenless JSON summary on the internal network for Glance
to render. The token never leaves this container; the output contains no secrets.
"""
import json, os, ssl, time, threading, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = os.environ.get("PORTAINER_RO_TOKEN", "").strip()
BASE = os.environ.get("PORTAINER_URL", "https://portainer.ragnarok.eslg.no").rstrip("/")
EP = os.environ.get("PORTAINER_ENDPOINT_ID", "7")
TTL = int(os.environ.get("CACHE_TTL", "15"))
API = f"{BASE}/api/endpoints/{EP}/docker"
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE

_cache = {"t": 0.0, "data": None}
_lock = threading.Lock()


def _get(path, timeout=10):
    req = urllib.request.Request(API + path, headers={"X-API-Key": TOKEN})
    with urllib.request.urlopen(req, context=CTX, timeout=timeout) as r:
        return json.loads(r.read())


def build():
    info = _get("/info")
    conts = _get("/containers/json")
    out, tot_cpu, tot_mem = [], 0.0, 0.0
    for c in conts:
        labels = c.get("Labels") or {}
        name = labels.get("com.docker.compose.project") or c["Names"][0].lstrip("/")
        cpu = mem = 0.0
        try:
            s = _get(f'/containers/{c["Id"]}/stats?stream=false')
            cs, ps = s["cpu_stats"], s["precpu_stats"]
            cd = cs["cpu_usage"]["total_usage"] - ps["cpu_usage"]["total_usage"]
            sd = cs.get("system_cpu_usage", 0) - ps.get("system_cpu_usage", 0)
            ncpu = cs.get("online_cpus") or len(cs["cpu_usage"].get("percpu_usage") or [1])
            cpu = round((cd / sd) * ncpu * 100, 2) if sd > 0 and cd >= 0 else 0.0
            ms = s["memory_stats"]
            mem = round((ms.get("usage", 0) - ms.get("stats", {}).get("inactive_file", 0)) / 1048576.0, 1)
        except Exception:
            pass
        out.append({"name": name, "cpu": cpu, "mem_mib": mem, "status": c.get("State", "")})
        tot_cpu += cpu; tot_mem += mem
    out.sort(key=lambda x: -x["mem_mib"])
    return {
        "host": {
            "cpus": info.get("NCPU"),
            "mem_total_mib": round(info.get("MemTotal", 0) / 1048576.0),
            "containers_running": info.get("ContainersRunning"),
            "containers_total": info.get("Containers"),
        },
        "containers": out,
        "totals": {"cpu": round(tot_cpu, 2), "mem_mib": round(tot_mem, 1), "count": len(out)},
        "updated": int(time.time()),
    }


def summary():
    if not TOKEN:
        return {"error": "no token configured", "containers": [], "host": {}, "totals": {}}
    now = time.time()
    with _lock:
        if _cache["data"] and now - _cache["t"] < TTL:
            return _cache["data"]
    try:
        data = build()
    except Exception as e:
        return {"error": str(e), "containers": [], "host": {}, "totals": {}}
    with _lock:
        _cache["t"] = now; _cache["data"] = data
    return data


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/summary"):
            body = json.dumps(summary()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404); self.end_headers()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), H).serve_forever()
