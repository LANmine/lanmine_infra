#!/usr/bin/env python3
"""Deploy changed stacks to Portainer, injecting secrets from GitHub.

Called by .github/workflows/deploy.yml after a change to stacks/** lands on main.
For each stack name passed as an argument:
  - if a Portainer stack with that name already exists -> redeploy it from Git
  - if it does not exist yet -> create it from Git (first deploy)

Secrets
-------
A stack can reference secrets in its docker-compose.yml with ${VAR}, e.g.:

    environment:
      - ADMIN_PASSWORD=${ADMIN_PASSWORD}

For each ${VAR} a compose file references, this script looks for a matching
**GitHub Actions secret** of the same name and passes it to Portainer as a stack
environment variable (stored on the server, never written into the repo).
So the flow is: apprentice references ${VAR} in the compose and says "needs VAR";
a maintainer adds a repo secret named VAR in GitHub. No workflow edits needed.

Secret names are a single global namespace, so use unique, descriptive names
(e.g. UPTIME_ADMIN_PASSWORD, not just PASSWORD) to avoid two stacks colliding.

Configuration comes from environment variables (set in the workflow):
  PORTAINER_URL          e.g. https://portainer.ragnarok.eslg.no
  PORTAINER_API_KEY      the Portainer API key (a GitHub Actions secret)
  PORTAINER_ENDPOINT_ID  the Docker environment id (default: 7)
  REPO_URL               https://github.com/LANmine/lanmine_infra
  GIT_REF                git ref to deploy (default: refs/heads/main)
  SECRETS_JSON           JSON object of all GitHub secrets: {"NAME": "value", ...}
                         (produced in the workflow with ${{ toJSON(secrets) }})
"""
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request

BASE = os.environ["PORTAINER_URL"].rstrip("/")
KEY = os.environ["PORTAINER_API_KEY"]
ENDPOINT = int(os.environ.get("PORTAINER_ENDPOINT_ID", "7"))
REPO_URL = os.environ["REPO_URL"]
GIT_REF = os.environ.get("GIT_REF", "refs/heads/main")

# All GitHub secrets, as a name->value map. Empty when run locally.
try:
    ALL_SECRETS = json.loads(os.environ.get("SECRETS_JSON", "") or "{}")
except json.JSONDecodeError:
    ALL_SECRETS = {}

# Never inject these into a service, even if a compose file references them.
RESERVED = {"PORTAINER_API_KEY", "GITHUB_TOKEN"}

# The server uses a self-signed certificate, so we skip TLS verification here.
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

# ${VAR}, ${VAR:-default}, ${VAR-default}, $VAR   (but not $$ which is a literal $)
VAR_RE = re.compile(r"(?<!\$)\$\{?([A-Za-z_][A-Za-z0-9_]*)")


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


def env_for(compose_path):
    """Return the [{name,value}] env this stack needs, from GitHub secrets."""
    text = open(compose_path).read().replace("$$", "")  # drop escaped literals
    referenced = set(VAR_RE.findall(text))
    env, missing = [], []
    for name in sorted(referenced):
        if name in RESERVED:
            continue
        if name in ALL_SECRETS:
            env.append({"name": name, "value": ALL_SECRETS[name]})
        else:
            missing.append(name)
    return env, missing


def main(names):
    by_name = existing_stacks()
    failures = 0
    for name in names:
        compose = f"stacks/{name}/docker-compose.yml"
        if not os.path.exists(compose):
            print(f"~ {name}: folder was removed in this change — "
                  f"skipping (delete it in Portainer manually if needed)")
            continue

        env, missing = env_for(compose)
        if env:
            print(f"  {name}: injecting secrets -> {', '.join(e['name'] for e in env)}")
        if missing:
            # Not fatal: the var may have a default in the compose, or be optional.
            print(f"  {name}: NOTE referenced but no GitHub secret set -> "
                  f"{', '.join(missing)} (add repo secrets if these are required)")

        if name in by_name:
            sid = by_name[name]["Id"]
            status, resp = api(
                "PUT",
                f"/api/stacks/{sid}/git/redeploy?endpointId={ENDPOINT}",
                {"repositoryReferenceName": GIT_REF, "pullImage": True, "env": env},
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
                    "env": env,
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
