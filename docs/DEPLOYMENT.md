# Deploying Leapvoy (Oracle Cloud Always Free)

This guide takes a fresh Oracle Cloud account to a Leapvoy server that runs 24/7, repairs itself, backs itself up
every night and is reachable from any phone or browser over HTTPS, for **₹0 / $0 a month**.

It is the exact path used for the live deployment, including every problem met on the way and its fix
(see [Troubleshooting](#11-troubleshooting)).

**Time:** about 1-2 hours the first time, most of it waiting for installs and the first build.

---

## Contents
1. [Architecture](#1-architecture)
2. [What you need](#2-what-you-need)
3. [Create the server](#3-create-the-server-oracle-console)
4. [Connect over SSH](#4-connect-over-ssh)
5. [Prepare the server](#5-prepare-the-server)
6. [Get the code and the secrets](#6-get-the-code-and-the-secrets)
7. [First start](#7-first-start)
8. [Public HTTPS with Tailscale Funnel](#8-public-https-with-tailscale-funnel)
9. [Self-healing: how it restarts itself](#9-self-healing-how-it-restarts-itself)
10. [Everyday operations](#10-everyday-operations)
11. [Troubleshooting](#11-troubleshooting)
12. [Staying free](#12-staying-free)

---

## 1. Architecture

```
 Phone app / any browser
          │  HTTPS (valid certificate, no VPN app needed)
          ▼
 Tailscale Funnel ── https://leapvoy.<your-tailnet>.ts.net
          │
          ▼  127.0.0.1:8080 (nothing else is exposed)
 ┌──────────────────────────── Oracle A1.Flex VM (Ubuntu 24.04, ARM) ────────────────────────────┐
 │  web (nginx)   /      → the Expo web app (static build)                                       │
 │                /api/  → backend:8000                                                          │
 │  backend       FastAPI: auth, chat (SSE), jobs, settings, notifications                       │
 │  telegram      Telethon listener: reads enabled channels (read-only), catches up after gaps   │
 │  pipeline      filter → embedding match → AI extract + fit score (LangGraph)                  │
 │  sender        scheduled emails (SMTP), reply tracking (IMAP), push notifications, cleanup    │
 │  db            Postgres 16 + pgvector                                                         │
 │                                                                                               │
 │  systemd: leapvoy-heal (every minute) · leapvoy-backup (03:30) · Docker · Tailscale           │
 └───────────────────────────────────────────────────────────────────────────────────────────────┘
```

Push notifications go through Expo's push service (Firebase Cloud Messaging), so they reach the phone without any
inbound connection to the server.

## 2. What you need

| Item | Notes |
|---|---|
| Oracle Cloud account | Free Tier. A debit card with international online payments enabled works for the identity check (no charge) |
| A free Tailscale account | Only the **server** joins it; phones and laptops don't need Tailscale |
| A laptop with OpenSSH | Built into Windows 10/11, macOS and Linux |
| API keys | Telegram (`my.telegram.org`), Groq, optionally Mistral and Gemini (all have free tiers) |

**Three rules**
1. **Never click "Upgrade"** on the Free Tier banner. Leapvoy fits completely in Always Free.
2. **Only create resources labelled "Always Free-eligible".** Anything paid from trial credit is deleted when the
   30-day trial ends.
3. **The SSH private key is the master key of the server.** Never share it or commit it (`*.key` is git-ignored).

## 3. Create the server (Oracle console)

Console → **☰ → Compute → Instances → Create instance**. Pick your home region first (top right).

### 3.1 Basic information
| Field | Value | Why |
|---|---|---|
| Name | `leapvoy` | |
| Placement → Capacity type | **On-demand** | Preemptible can be switched off by Oracle at any time |
| Shape | **Ampere → VM.Standard.A1.Flex** ("Always Free-eligible") | |
| OCPUs / Memory | **2 OCPU / 6 GB** (1 / 6 also works) | Leapvoy uses about 2 GB; see the idle note below |
| Image | **Canonical Ubuntu 24.04** (not Minimal), build ending in `aarch64` | Choose the shape first, then the image |
| Management → IMDSv2 only | keep ticked | |
| Availability → **Restore instance lifecycle state after infrastructure maintenance** | **ticked** | Oracle powers the VM back on after hardware repairs |
| Oracle Cloud Agent → Compute Instance Monitoring | on | CPU / memory graphs |

> **Idle reclaim:** Oracle may reclaim an Always Free VM that is idle for 7 days (CPU, network **and** memory all
> under 20%). With 6 GB, Leapvoy's normal memory use stays above that line.

### 3.2 Security
Shielded instance and Confidential computing: **off** (not supported on Ampere free shapes).

### 3.3 Networking
> **Known console quirk:** if you create the network *inside* this form, the switch **"Automatically assign public
> IPv4 address"** can stay grey ("You must select a public subnet"). Fix: in a second tab, **Networking → Virtual
> cloud networks → Start VCN Wizard → Create VCN with Internet Connectivity** (name `leapvoy-vcn`, defaults). Back in
> the form, select that VCN and its **public** subnet; the switch now works.

| Field | Value |
|---|---|
| Public IPv4 address | **on** (used only for SSH administration) |
| IPv6 | off |
| SSH keys | **Generate a key pair for me** → download **both** keys now (shown only once) |

Store the keys in the repo's `private/` folder (git-ignored), e.g. `private/oracle-leapvoy.key`.

### 3.4 Storage
| Field | Value | Why |
|---|---|---|
| Custom boot volume size | **100 GB** | Always Free includes 200 GB in total |
| Performance | **10 VPUs (Balanced)** | Higher costs money |
| Your own encryption key | off | Needs the paid Vault; Oracle encrypts anyway |

### 3.5 Review and create
The estimate must be **$0** / Always Free. Click **Create**, wait for **Running**, note the **public IP**.

**"Out of capacity"?** Free ARM capacity is popular. Nothing is created or charged: retry later (early morning or
late night is easiest), or start with 1 OCPU and grow later (**Edit → Edit shape**, one reboot, Leapvoy comes back
by itself). Never switch to a paid shape to get around it.

## 4. Connect over SSH

**Windows (PowerShell)**: make the key private (OpenSSH refuses keys other users can read):
```powershell
$key = "$PWD\private\oracle-leapvoy.key"
icacls $key /inheritance:r
icacls $key /grant:r "$($env:USERNAME):R"
```
Add a shortcut to `~/.ssh/config` (replace `PUBLIC-IP` and the key path):
```
Host leapvoy
    HostName PUBLIC-IP
    User ubuntu
    IdentityFile C:\path\to\leapvoy\private\oracle-leapvoy.key
    ServerAliveInterval 30
```
Then `ssh leapvoy` (answer `yes` the first time). macOS / Linux: `chmod 600` the key instead of `icacls`.

## 5. Prepare the server

```bash
sudo apt update && sudo apt -y full-upgrade && sudo reboot
# reconnect, then:
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu && exit
# reconnect, then check:
docker run --rm hello-world && docker compose version
sudo sshd -T | grep -E '^passwordauthentication|^permitrootlogin'   # expect: no / no (key-only logins)
```

Tailscale (server only):
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --hostname leapvoy        # open the printed link and approve
```
In the Tailscale admin console: **DNS → MagicDNS on** and **HTTPS Certificates on**; **Machines → leapvoy → ⋯ →
Disable key expiry** (otherwise the server drops off every 180 days).

## 6. Get the code and the secrets

```bash
git clone https://github.com/ChetanMahajan715/leapvoy.git ~/leapvoy
cd ~/leapvoy
cp .env.example .env && chmod 600 .env
nano .env
```

Fill in `.env` (see `.env.example` for every value):

| Variable | Server value |
|---|---|
| `POSTGRES_PASSWORD` | a new random one: `openssl rand -hex 24` |
| `MASTER_KEY` | `python3 -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"` (encrypts Telegram sessions and App Passwords; **keep it forever**, data encrypted with it is unreadable without it) |
| `JWT_SECRET` | `python3 -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | from my.telegram.org |
| `GROQ_API_KEY` (+ `MISTRAL_API_KEY`, `GEMINI_API_KEY`) | free-tier keys |
| `SIGNUP_MODE` | **`first`**: only the first account can sign up, then sign-ups close |
| `API_DOCS` | **`false`**: no public `/docs` |
| `SYSTEM_EMAIL` / `SYSTEM_EMAIL_PASSWORD` | optional, Gmail App Password for "Forgot password" codes |

`DATABASE_URL` / `TEST_DATABASE_URL` are only for running outside Docker; Compose builds its own.

> Moving an existing laptop database instead of starting fresh: copy the laptop's `.env` (same `MASTER_KEY`!),
> export with `backend/scripts/dump_db.py`, then `leapvoy restore FILE` after section 7.2.

## 7. First start

```bash
cd ~/leapvoy
sudo deploy/leapvoy install     # leapvoy command, self-heal + backup timers, swap, India time, auto-reboot
leapvoy on                      # first build: 10-20 min on ARM
leapvoy status                  # every part Up, then (healthy)
```
`pipeline` and `sender` may show `(health: starting)` for a while after a fresh start: normal.

## 8. Public HTTPS with Tailscale Funnel

```bash
sudo tailscale funnel --bg 8080
```
The first run may print a link to allow Funnel for your tailnet: open it, enable, run the command again. Your
address is `https://leapvoy.<your-tailnet>.ts.net` (web app) and `.../api` (the Android app's **Server** setting,
changeable on the sign-in screen). The setting survives reboots.

Check from outside:
```bash
curl -s https://leapvoy.<your-tailnet>.ts.net/api/health      # {"status":"ok"}
curl -s -o /dev/null -w "%{http_code}\n" https://leapvoy.<your-tailnet>.ts.net/api/docs   # 404 when API_DOCS=false
```

Prefer a private server? Use `sudo tailscale serve --bg 8080` instead: only devices on your tailnet can reach it.

Then open the address, **sign up** (the first account becomes the owner), turn on 2-step sign-in, connect Telegram
(QR code), enable channels, upload a resume and fill in the profile.

## 9. Self-healing: how it restarts itself

| Failure | What fixes it | Time |
|---|---|---|
| A part crashes | Docker `restart: always` | seconds |
| A part hangs | Health checks (API `/health`; workers write a heartbeat every loop) mark it unhealthy; the `leapvoy-heal` timer restarts it | ~1-3 min |
| Docker crashes | systemd restarts Docker, Docker starts the parts | seconds |
| VM reboots (updates, resize, maintenance) | Docker starts at boot | 1-2 min |
| Kernel panic | `kernel.panic = 10` reboots the VM | ~2 min |
| Oracle hardware repair | "Restore instance lifecycle state" powers it back on | minutes |
| Memory pressure | 2 GB swap file | instant |
| Disk filling with logs | 3 × 10 MB log rotation per part | always |
| Security updates | unattended-upgrades nightly; reboot at 04:00 only if required | nightly |
| Data loss | `pg_dump` backup at 03:30, newest 7 kept in `~/leapvoy/backups` | nightly |

Not automatic (the app sends a notification): Telegram signing Leapvoy out, or an email App Password being revoked.
`leapvoy off` stays off across reboots until `leapvoy on`.

Try it: `sudo kill -9 $(docker inspect -f '{{.State.Pid}}' leapvoy-pipeline-1); sleep 15; leapvoy status`.

## 10. Everyday operations

| Command | What it does |
|---|---|
| `leapvoy status` | Every part and its health |
| `leapvoy logs [backend\|telegram\|pipeline\|sender\|web\|db]` | Live logs (Ctrl+C to stop) |
| `leapvoy on` / `leapvoy off` | Start / stop everything (data stays) |
| `leapvoy update` | `git pull` + rebuild + restart |
| `leapvoy backup` / `leapvoy restore FILE` | Backup now / restore a backup |

**Ship new code:** push to GitHub from your laptop, then `ssh leapvoy "leapvoy update"`.

**Copy backups off the server** (do it now and then):
```powershell
scp "leapvoy:~/leapvoy/backups/*.sql.gz" .\private\
```

**Laptop browser without Tailscale or Funnel:** `ssh -N -L 8080:127.0.0.1:8080 leapvoy`, then open
http://localhost:8080.

**Android app (APK):** built with EAS (`mobile/`, see the [README](../README.md#android-app)). Set the default server
for a build with an EAS environment variable `EXPO_PUBLIC_API_URL` (expo.dev → project → Environment variables), or
just change **Server** on the app's sign-in screen.

## 11. Troubleshooting

Problems met during the real deployment, and their fixes (all fixed in the repo now):

| Symptom | Cause | Fix |
|---|---|---|
| Web image build: `mobile/` not found | `.dockerignore` excluded `mobile/` | Fixed: only `node_modules`, `dist`, `.expo` are excluded |
| Backend crash loop: `libxcb.so.1: cannot open shared object file` | OpenCV (OCR) needs system libraries missing from `python:3.12-slim` | Fixed: Dockerfile installs `libgl1 libglib2.0-0 libxcb1` |
| `leapvoy` command fails reading `.env` | Values with spaces (Gmail App Passwords) broke `source .env` | Fixed: the script reads only the keys it needs |
| SSH drops, then "connection refused" for a minute | The VM rebooted (e.g. after a shape change) | Wait 1-2 min; everything comes back by itself |
| Public IPv4 switch is grey | VCN created inside the instance form | See the quirk in 3.3 |
| "Out of capacity" | No free ARM capacity right now | Retry later / smaller shape (3.5) |
| Posts stay "Checking with AI" | No resume uploaded yet (nothing to match against), or free AI rate limits on a big first backlog | Upload a resume; a first-day backlog clears within the hour, new posts take a minute |
| `Permission denied (publickey)` | Wrong key path or user | `IdentityFile` path, user `ubuntu` |
| `UNPROTECTED PRIVATE KEY FILE` | Key readable by other users | Section 4 `icacls` / `chmod 600` |
| A part stays `(unhealthy)` | Real error inside | `leapvoy logs <part>` |
| `No space left on device` | Old build layers | `docker system prune -f` |
| Build killed (out of memory) | Swap missing | `free -h`; re-run `sudo deploy/leapvoy install` |
| `leapvoy: command not found` | Install step skipped | `sudo ~/leapvoy/deploy/leapvoy install` |

## 12. Staying free

- **Billing → Cost analysis** should show **$0.00** after a day.
- The instance page shows **Always Free-eligible**.
- When the 30-day trial ends nothing Always Free is deleted. Never click **Upgrade**.
- Tailscale's free plan covers Funnel; Expo's free plan covers push notifications and APK builds; the AI providers'
  free tiers are rate-limited, and Leapvoy pauses background checks before they run out (chat keeps a reserve).
