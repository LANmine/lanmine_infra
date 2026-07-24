#!/usr/bin/env python3
"""Deploy changed stacks to Portainer.

Called by .github/workflows/deploy.yml after a change to stacks/** lands on main.
For each stack name passed as an argument:
  - if a Portainer stack with that name already exists -> redeploy it from Git
  - if it does not exist yet -> create it from Git (first deploy)

Configuration comes from environment variables (set in the workflow):
  PORTAINER_URL          e.g. https://portainer.ragnarok.eslg.no
  PORTAINER_API_KEY      the Portainer API key (a GitHub Actions secret)
  PORTAINER_ENDPOINT_ID  the Docker environment id (default: 7)
  REPO_URL               https://github.com/LANmine/lanmine_infra
  GIT_REF                git ref to deploy (default: refs/heads/main)
"""
import json
import os
import ssl
import sys
import urllib.error
import urllib.request

BASE = os.environ["PORTAINER_URL"].rstrip("/")
KEY = os.environ["PORTAINER_API_KEY"]
ENDPOINT = int(os.environ.get("PORTAINER_ENDPOINT_ID", "7"))
REPO_URL = os.environ["REPO_URL"]
GIT_REF = os.environ.get("GIT_REF", "refs/heads/main")

# The server uses a self-signed certificate, so we skip TLS verification here.
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path,
        method=method,
        data=data,
        headers={"X-API-Key": KEY, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, context=CTX) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def existing_stacks():
    status, data = api("GET", "/api/stacks")
    if status != 200:
        sys.exit(f"Could not list stacks (HTTP {status}): {data}")
    return {s["Name"]: s for s in data if s.get("EndpointId") == ENDPOINT}


def main(names):
    by_name = existing_stacks()
    failures = 0
    for name in names:
        compose = f"stacks/{name}/docker-compose.yml"
        if not os.path.exists(compose):
            print(f"~ {name}: folder was removed in this change — "
                  f"skipping (delete it in Portainer manually if needed)")
            continue

        if name in by_name:
            sid = by_name[name]["Id"]
            status, resp = api(
                "PUT",
                f"/api/stacks/{sid}/git/redeploy?endpointId={ENDPOINT}",
                {"repositoryReferenceName": GIT_REF, "pullImage": True},
            )
            action = f"redeployed (id {sid})"
        else:
            status, resp = api(
                "POST",
                f"/api/stacks/create/standalone/repository?endpointId={ENDPOINT}",
                {
                    "name": name,
                    "repositoryURL": REPO_URL,
                    "repositoryReferenceName": GIT_REF,
                    "composeFile": compose,
                    "repositoryAuthentication": False,
                },
            )
            action = "created"

        if 200 <= status < 300:
            print(f"✓ {name}: {action}")
        else:
            failures += 1
            print(f"✗ {name}: FAILED (HTTP {status}): {resp}")

    if failures:
        sys.exit(f"{failures} stack(s) failed to deploy")


if __name__ == "__main__":
    stack_names = sys.argv[1:]
    if not stack_names:
        print("No changed stacks to deploy.")
    else:
        print("Deploying stacks:", ", ".join(stack_names))
        main(stack_names)
