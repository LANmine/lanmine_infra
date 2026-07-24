# lanmine_infra

This repository **is** the LANmine server. Whatever is described here is what runs on our
machine. You never need to log into a server, use a terminal, or click around in any admin panel.

> **The golden rule:** if you want to change what runs on the server, you change a file in this
> repository and open a Pull Request. When it's merged, it goes live automatically.

---

## How a change reaches the server

```
  You edit a file        You open a          A teammate           It goes live
  in this repo    ─────▶  Pull Request  ────▶ reviews & merges ───▶ automatically
                          (a "PR")             it into  main        (~30 seconds later)
```

1. **You edit or add a file** under `stacks/` (see below).
2. **You open a Pull Request.** A robot checks your file for mistakes and comments on the PR.
3. **A teammate reviews and merges** your PR into the `main` branch.
4. **The server updates itself.** A GitHub Action tells our server to pull the new version and
   restart just the service you changed. Nothing else is touched.

That's the whole system. GitHub is the only thing you ever interface with.

---

## What is a "stack"?

A **stack** is one service running on the server — a website, a bot, a dashboard, etc.
Each stack lives in its own folder:

```
stacks/
└── example/
    └── docker-compose.yml   <- describes ONE service
```

A `docker-compose.yml` file is just a recipe that says *"run this program, with these settings."*

---

## Add a new service (the 3 things you change)

Copy the `example` folder to a new name and edit **three things**. Here is the example, annotated:

```yaml
services:
  web:
    image: httpd:latest          # 1. WHICH program to run (an image from Docker Hub)
    restart: unless-stopped
    networks:
      - traefik
    labels:
      - traefik.enable=true
      - traefik.docker.network=traefik
      # 2. WHICH web address points to this service:
      - traefik.http.routers.example.rule=Host(`example.tech.lanmine.no`)
      - traefik.http.routers.example.service=example
      # 3. WHICH port the program listens on inside the container:
      - traefik.http.services.example.loadbalancer.server.port=80

networks:
  traefik:
    external: true
```

So to add a service called `scoreboard`:

1. Create `stacks/scoreboard/docker-compose.yml`.
2. Set the **image** to the program you want (e.g. `image: nginx:latest`).
3. Set the **web address** to `scoreboard.tech.lanmine.no` (any name under `*.tech.lanmine.no`
   works instantly — no DNS setup needed).
4. Set the **port** to whatever your program listens on.
5. **Important:** in the three `traefik.http...` lines, replace the word `example` with your
   service name (`scoreboard`) so it doesn't collide with other services.

Open a PR. Once merged, visit `https://scoreboard.tech.lanmine.no`. Done.

---

## Change an existing service

Edit its `docker-compose.yml`, open a PR, get it merged. That's it — only that one service restarts.

---

## Rules

- ✅ **Every change goes through a Pull Request.** No pushing straight to `main`.
- 🚫 **Never put secrets in this repo** (passwords, API keys, tokens). This repo is public.
  If a service needs a secret, ask a maintainer — secrets are set separately on the server.
- 🏷️ **Give each service its own unique name** in the `traefik.http...` labels.
- 🌐 **Web addresses** are always `something.tech.lanmine.no` and work automatically.

---

## For maintainers

The automation lives in `.github/workflows/`:

- `validate.yml` — runs on every PR, checks each changed compose file is valid.
- `deploy.yml` — runs when something under `stacks/` lands on `main`; figures out which stacks
  changed and tells Portainer to redeploy just those (creating the stack the first time it sees it).

Deployment target: Portainer environment **Ragnarok** (`portainer.ragnarok.eslg.no`, endpoint 7).
The Portainer API key is stored as the GitHub Actions secret **`PORTAINER_API_KEY`** — never in the repo.
