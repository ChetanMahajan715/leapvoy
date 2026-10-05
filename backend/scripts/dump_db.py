"""Copy of the laptop database for moving it to the server (plain SQL, gzipped). Run from backend/:

  uv run python scripts/dev.py python scripts/dump_db.py ../leapvoy-dump.sql.gz

On the server: deploy/leapvoy restore leapvoy-dump.sql.gz. Secrets inside (Telegram session, App Passwords, 2FA keys)
stay encrypted with MASTER_KEY, so the server's .env must have the same MASTER_KEY and JWT_SECRET as the laptop.
"""

import gzip
import os
import subprocess
import sys
from pathlib import Path

import pgserver

if len(sys.argv) != 2:
    sys.exit(__doc__)
pg_dump = Path(pgserver.__file__).parent / "pginstall" / "bin" / ("pg_dump.exe" if os.name == "nt" else "pg_dump")
url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)
out = subprocess.run([str(pg_dump), "--clean", "--if-exists", "--no-owner", "--no-privileges", "-d", url],
                     capture_output=True, check=True).stdout
Path(sys.argv[1]).write_bytes(gzip.compress(out))
print(f"{sys.argv[1]}: {len(out) // 1024} KB of SQL (gzipped {Path(sys.argv[1]).stat().st_size // 1024} KB)")
