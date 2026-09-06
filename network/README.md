# network/ — switch configuration as code

GitHub is the **source of truth** for the LAN's network. You edit config here,
open a PR, and on merge the switches are made to match. Nothing is configured by
hand on the devices — if it's not in git, it's drift.

This is intentionally public so other LAN parties can copy it almost 1:1. The only
things that are *not* in git are secrets (device credentials, SNMP community,
Tailscale key) — those are injected at run time from GitHub Actions secrets.

## Topology

| Role  | Devices        | Platform            |
|-------|----------------|---------------------|
| gw    | gw1, gw2       | Cisco IOS/IOS-XE    | routers (gw1 primary, gw2 backup — HSRP)
| core  | core1, core2   | Cisco NX-OS (Nexus) | core switches
| edge  | edge01..edgeNN | Cisco IOS           | participant access switches

## How it flows

```
edit network/**  ──PR──▶  net-validate (hosted runner)      lint + render + (containerlab test)
                          no secrets, no device access, safe for fork PRs
        │
      merge to main (only maintainers)
        │
        ▼
   net-deploy (self-hosted runner on the on-site mgmt box)
   render intended config ▶ dry-run diff ▶ apply (config-replace) ▶ verify
        │
   net-drift (scheduled) ── compares running config vs intended, flags drift
```

The self-hosted runner lives on a dual-homed management box (Tailscale on one
side for admin, a leg in the management VLAN on the other). Switches are **not**
on the tailnet — the runner reaches them over the mgmt VLAN. See the repo root
docs for the runner setup.

## Layout

```
inventory/hosts.yaml     devices, roles, mgmt IPs, platform
group_vars/{all,gw,core,edge}.yaml   settings shared per role
host_vars/edge01.yaml    per-device values (hostname, uplink, access VLANs, table/row)
templates/{gw,core,edge}.j2          Jinja config templates
intended/                rendered configs (CI output)
backups/                 running-config pulled by the drift job
playbooks/{render,deploy,backup}.yml
```

## Add / change a switch

1. Add the device to `inventory/hosts.yaml` and a `host_vars/<name>.yaml`.
2. Adjust the relevant template if needed.
3. Open a PR. `net-validate` lints and renders it (no device is touched).
4. A maintainer reviews the rendered diff and merges. `net-deploy` applies it.

## Secrets (never commit these)

Set as GitHub Actions secrets; the playbooks read them from the environment:

- `NET_USER`, `NET_PASSWORD` — device login (a dedicated automation account)
- `NET_SNMP_COMMUNITY` — SNMP community

IP addresses, VLANs, and ACLs *are* in git on purpose — security must not depend
on them being secret (the firewall and crypto-authenticated management are the
real controls). Keys, passwords and community strings never go in git.

## Safety

- Deploys run a `--check --diff` dry-run first; a maintainer reviews it in the PR.
- Apply uses config-replace so the device is forced to match git (out-of-band
  changes get reverted). Use commit-confirm / `reload in` on real gear so a bad
  push self-reverts and can't lock you out.
- Legacy switches (older IOS) need permissive SSH crypto on the runner
  (ssh-rsa / SHA-1); modern IOS-XE / NX-OS are fine.
