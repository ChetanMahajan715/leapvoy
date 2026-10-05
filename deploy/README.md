# deploy/

Everything that runs Leapvoy on a server. **Full guide: [docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md).**

```
Phone app / browser ──HTTPS (Tailscale Funnel)──> https://leapvoy.<your-tailnet>.ts.net
                                                    └─ web (nginx): /  = web app,  /api = backend
                                                       backend · telegram · pipeline · sender · db (Postgres + pgvector)
```

| File | What it is |
|---|---|
| `docker-compose.yml` | All six parts, each with auto-restart, a health check and log limits |
| `leapvoy` | The `leapvoy on/off/status/logs/backup/restore/update/heal/install` command |
| `systemd/` | Timers installed by `sudo deploy/leapvoy install`: self-heal every minute, backup at 03:30 |
| `web.Dockerfile`, `nginx.conf` | The web app build, with the API behind `/api` (one address, no CORS) |
| `initdb/` | Creates the test database on the first start |

| Command | What it does |
|---|---|
| `leapvoy on` / `leapvoy off` | Start / stop everything (data stays) |
| `leapvoy status` · `leapvoy logs pipeline` | Health of every part · live logs of one |
| `leapvoy backup` · `leapvoy restore FILE` | Database copy · put a copy back |
| `leapvoy update` | `git pull`, rebuild, restart |
