#!/usr/bin/env python3
"""Tiny read-only metrics sidecar for the LANmine dashboard.

Holds the Portainer token (server-side only), polls the Docker API via Portainer
on a background thread, and serves a sanitized, tokenless JSON summary. The HTTP
handler never blocks on Portainer — it returns the last cached snapshot instantly.
The token never leaves this container; the output contains no secrets.
"""
import json, os, ssl, time, threading, urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = os.environ.get("PORTAINER_RO_TOKEN", "").strip()
BASE = os.environ.get("PORTAINER_URL", "https://portainer.ragnarok.eslg.no").rstrip("/")
EP = os.environ.get("PORTAINER_ENDPOINT_ID", "7")
REFRESH = int(os.environ.get("REFRESH", "20"))
API = f"{BASE}/api/endpoints/{EP}/docker"
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE

_state = {"data": {"status": "warming up", "containers": [], "host": {}, "totals": {}}}
_lock = threading.Lock()


def _get(path, timeout=15):
    req = urllib.request.Request(API + path, headers={"X-API-Key": TOKEN})
    with urllib.request.urlopen(req, context=CTX, timeout=timeout) as r:
        return json.loads(r.read())


def _one(c):
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
    return {"name": name, "cpu": cpu, "mem_mib": mem, "status": c.get("State", "")}


def build():
    info = _get("/info")
    conts = _get("/containers/json")
    with ThreadPoolExecutor(max_workers=8) as ex:
        out = list(ex.map(_one, conts))
    out.sort(key=lambda x: -x["mem_mib"])
    return {
        "host": {
            "cpus": info.get("NCPU"),
            "mem_total_mib": round(info.get("MemTotal", 0) / 1048576.0),
            "containers_running": info.get("ContainersRunning"),
            "containers_total": info.get("Containers"),
        },
        "containers": out,
        "totals": {"cpu": round(sum(c["cpu"] for c in out), 2),
                   "mem_mib": round(sum(c["mem_mib"] for c in out), 1),
                   "count": len(out)},
        "updated": int(time.time()),
    }


def refresher():
    while True:
        if not TOKEN:
            with _lock:
                _state["data"] = {"error": "no token configured", "containers": [], "host": {}, "totals": {}}
            time.sleep(30); continue
        try:
            d = build()
        except Exception as e:
            d = {"error": str(e), "containers": [], "host": {}, "totals": {}}
        with _lock:
            _state["data"] = d
        time.sleep(REFRESH)


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/summary"):
            with _lock:
                body = json.dumps(_state["data"]).encode()
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
    threading.Thread(target=refresher, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8080), H).serve_forever()
