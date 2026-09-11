#!/usr/bin/env python3
"""Refresh Pandabot's lanmine.no knowledge base in Open WebUI.

Scrapes lanmine.no, consolidates the pages into a few markdown docs, builds a
fresh Open WebUI knowledge collection, points the Pandabot model at it, and
deletes the previous collection(s). Runs on a schedule (see docker-compose.yml).

Stdlib only. Auth uses the Open WebUI admin login (creds from env), because
API-key creation is disabled on this instance.
"""
import os, re, json, time, urllib.request, urllib.error

OWUI   = os.environ["OWUI_URL"].rstrip("/")
EMAIL  = os.environ["OWUI_EMAIL"]
PW     = os.environ["OWUI_PASSWORD"]
MODEL  = os.environ.get("MODEL_ID", "lanmine-panda")
CNAME  = os.environ.get("COLLECTION_NAME", "LANmine.no")
SITE   = os.environ.get("SITE_URL", "https://lanmine.no").rstrip("/")
UA     = {"User-Agent": "Mozilla/5.0 (lanmine-pandabot-kb)"}

def log(*a): print(time.strftime("%Y-%m-%d %H:%M:%S"), "|", *a, flush=True)

# ---------- Open WebUI API ----------
def api(path, token=None, data=None, method=None, timeout=180):
    hdr = {"Authorization": "Bearer " + token} if token else {}
    body = None
    if data is not None:
        body = json.dumps(data).encode(); hdr["Content-Type"] = "application/json"
    m = method or ("POST" if data is not None else "GET")
    r = urllib.request.Request(OWUI + path, data=body, headers=hdr, method=m)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read() or "null")

def upload_file(token, filename, content):
    boundary = "----kbrefresh" + os.urandom(8).hex()
    body = (f"--{boundary}\r\n".encode()
            + f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode()
            + b"Content-Type: text/markdown\r\n\r\n" + content.encode() + b"\r\n"
            + f"--{boundary}--\r\n".encode())
    r = urllib.request.Request(OWUI + "/api/v1/files/", data=body, method="POST",
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(r, timeout=180) as resp:
        return json.loads(resp.read())["id"]

# ---------- scrape ----------
def get(u, t=25):
    try:
        return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=t).read().decode("utf-8", "replace")
    except Exception:
        return ""

def clean(html):
    for tag in ["script", "style", "nav", "header", "footer", "svg", "form", "noscript"]:
        html = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", "", html, flags=re.S | re.I)
    m = re.search(r"<(?:main|article)[^>]*>(.*?)</(?:main|article)>", html, re.S | re.I)
    body = m.group(1) if m else html
    tm = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    title = re.sub(r"\s+", " ", re.sub("<[^>]+>", "", tm.group(1))).strip() if tm else ""
    text = re.sub("<[^>]+>", " ", body)
    text = re.sub(r"&nbsp;", " ", text); text = re.sub(r"&amp;", "&", text); text = re.sub(r"&[a-z]+;", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = "\n".join(l.strip() for l in text.splitlines())
    return title, re.sub(r"\n{3,}", "\n\n", text).strip()

def scrape():
    urls = set()
    for sm in ["page-sitemap.xml", "lan-event-sitemap.xml", "post-sitemap.xml"]:
        for l in re.findall(r"<loc>(.*?)</loc>", get(f"{SITE}/{sm}")):
            if not re.search(r"\.(png|jpe?g|webp|gif|pdf|svg)$", l, re.I):
                urls.add(l)
    core = {"om-oss", "bli-crew", "nyheter", "postere-og-flyers", "vi-soker-deg",
            "vi-trenger-nettopp-deg-til-crew", "sok-crew-til-hostens-lan",
            "hva-skjer-med-lanet-na", "i-dag-er-lan-sa-mye-mer-enn-bare-pc"}
    docs = {"praktisk-info-og-om": [], "events": [], "nyhetsarkiv": []}
    for u in sorted(urls):
        html = get(u)
        if not html:
            continue
        title, text = clean(html)
        if len(text) < 80:
            continue
        slug = u.rstrip("/").split("/")[-1] or "home"
        page = f"# {title}\nSource: {u}\n\n{text}\n"
        if "/lan-event/" in u:
            docs["events"].append(page)
        elif "/praktisk-info/" in u or slug in core or u.rstrip("/") == SITE:
            docs["praktisk-info-og-om"].append(page)
        else:
            docs["nyhetsarkiv"].append(page)
    return {k: "\n\n---\n\n".join(v) for k, v in docs.items() if v}

# ---------- main ----------
def main():
    log(f"login {OWUI} as {EMAIL}")
    token = api("/api/v1/auths/signin", data={"email": EMAIL, "password": PW})["token"]

    log("scraping", SITE)
    docs = scrape()
    log("scraped docs:", {k: len(v) for k, v in docs.items()})
    if not docs:
        log("no content scraped — aborting (keeping existing collection)"); return

    stamp = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    coll = api("/api/v1/knowledge/create", token,
               data={"name": CNAME, "description": f"Innhold fra {SITE} — oppdatert {stamp}.", "access_control": None})
    kid = coll["id"]; log("new collection", kid)

    for name, content in docs.items():
        fid = upload_file(token, f"lanmine-{name}.md", content)
        # text extraction is async — wait until the file's content is populated
        for _ in range(30):
            f = api(f"/api/v1/files/{fid}", token)
            if len((f.get("data") or {}).get("content") or "") > 0:
                break
            time.sleep(2)
        api(f"/api/v1/knowledge/{kid}/file/add", token, data={"file_id": fid})
        log("  added", name)

    # point Pandabot at the new collection (preserve everything else)
    m = api(f"/api/v1/models/model?id={MODEL}", token)
    meta = m.get("meta") or {}
    kobj = api(f"/api/v1/knowledge/{kid}", token); kobj["type"] = "collection"
    meta["knowledge"] = [kobj]
    api(f"/api/v1/models/model/update?id={MODEL}", token, data={
        "id": m["id"], "base_model_id": m.get("base_model_id"), "name": m.get("name"),
        "meta": meta, "params": m.get("params"),
        "access_control": m.get("access_control"), "is_active": m.get("is_active", True)})
    log("model", MODEL, "-> collection", kid)

    # delete previous collections with the same name
    for it in (api("/api/v1/knowledge/", token) or {}).get("items", []):
        if it.get("name") == CNAME and it.get("id") != kid:
            try:
                api(f"/api/v1/knowledge/{it['id']}/delete", token, method="DELETE")
                log("deleted old collection", it["id"])
            except Exception as e:
                log("could not delete", it["id"], repr(e))
    log("refresh complete")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log("ERROR:", repr(e))
