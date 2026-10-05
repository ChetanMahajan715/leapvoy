"""Oracle server hunter: applies the saved 'leapvoy' stack about once a minute until Oracle has a free ARM spot, then
stops by itself and tells you (Windows pop-up + sound, and a Leapvoy notification on your phone).

Safety: it only runs that one stack, refuses if the stack doesn't ask for the Always Free ARM shape (A1.Flex, at most
4 OCPU / 24 GB / 200 GB disk), stops as soon as a 'leapvoy' server exists (never two), and never changes the account.
Close its window to stop it. Delete the API key in Oracle after the server exists.

Files (in private/, never committed):  private/oci/config  (Oracle's config text, key_file = the .pem below)
                                       private/oci/oci_api_key.pem
                                       private/oci/stack_ocid.txt
Run (PowerShell, from backend/):
  $py = "$env:APPDATA\\uv\\python\\cpython-3.12-windows-x86_64-none\\python.exe"
  $env:PYTHONPATH = "C:\\Users\\Chetan\\Desktop\\Leapvoy\\.venv\\Lib\\site-packages;C:\\Users\\Chetan\\Desktop\\Leapvoy\\backend"
  & $py scripts\\dev.py python scripts\\oracle_hunt.py
"""

import asyncio
import io
import re
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

PRIVATE = Path(__file__).resolve().parents[2] / "private" / "oci"
LOG = PRIVATE / "hunt.log"
PAUSE = 60  # seconds between tries (each try itself takes ~1-2 min)
SLOW = 600  # after "too many requests"
NAME = "leapvoy"
ALIVE = ("PROVISIONING", "STARTING", "RUNNING", "STOPPING", "STOPPED")


def shape_ok(tf: str) -> str | None:
    """None when the stack only asks for the Always Free ARM server, else why not."""
    if "VM.Standard.A1.Flex" not in tf:
        return "the stack is not the Always Free ARM shape (VM.Standard.A1.Flex)"
    limits = {"ocpus": 4, "memory_in_gbs": 24, "boot_volume_size_in_gbs": 200}
    for key, most in limits.items():
        m = re.search(rf'{key}\s*=\s*"?(\d+(?:\.\d+)?)', tf)
        if m and float(m.group(1)) > most:
            return f"{key} = {m.group(1)} is above the free limit ({most})"
    return None


def classify(state: str, text: str) -> str:
    """What to do after a job: success | retry (Oracle full) | slow (too many requests) | stop (something else)."""
    t = text.lower()
    if state == "SUCCEEDED":
        return "success"
    if state == "CANCELED" or "capacity" in t:
        return "retry"
    if "429" in t or "toomanyrequests" in t or "too many requests" in t:
        return "slow"
    return "stop"


def log(msg: str) -> None:
    line = f"{datetime.now():%d %b %H:%M:%S}  {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def tell_windows(title: str, text: str) -> None:
    script = ("[console]::beep(880,350); [console]::beep(1175,500); Add-Type -AssemblyName PresentationFramework; "
              f"[System.Windows.MessageBox]::Show('{text}', '{title}') | Out-Null")
    subprocess.Popen(["powershell", "-NoProfile", "-Command", script])


async def tell_phone(ip: str) -> None:
    """A Leapvoy notification for every signed-up account (pushed by the sender worker when it runs). Best effort."""
    try:
        from sqlalchemy import select

        from app import notify
        from app.db.models import User
        from app.db.session import get_sessionmaker

        async with get_sessionmaker()() as s:
            for uid in (await s.execute(select(User.id).where(User.password_hash != "!"))).scalars():
                await notify.add(s, uid, "server_ready", "Your Oracle server is ready",
                                 f"Public IP {ip}. Next: section 4 of docs/DEPLOYMENT.md.", {"screen": "settings"})
            await s.commit()
    except Exception as e:  # noqa: BLE001 - no database here: the Windows pop-up still came
        log(f"(phone notification skipped: {type(e).__name__})")


def main() -> None:
    import oci

    PRIVATE.mkdir(parents=True, exist_ok=True)
    missing = [f for f in ("config", "oci_api_key.pem", "stack_ocid.txt") if not (PRIVATE / f).exists()]
    if missing:
        sys.exit(f"Missing in {PRIVATE}: {', '.join(missing)}. See the steps Claude gave you.")
    config = oci.config.from_file(str(PRIVATE / "config"))
    oci.config.validate_config(config)
    stack_id = (PRIVATE / "stack_ocid.txt").read_text(encoding="utf-8").strip()
    rm = oci.resource_manager.ResourceManagerClient(config)
    compute = oci.core.ComputeClient(config)
    network = oci.core.VirtualNetworkClient(config)
    tenancy = config["tenancy"]

    def existing():
        found = compute.list_instances(tenancy, display_name=NAME).data
        return next((i for i in found if i.lifecycle_state in ALIVE), None)

    def public_ip(instance) -> str:
        for a in compute.list_vnic_attachments(tenancy, instance_id=instance.id).data:
            vnic = network.get_vnic(a.vnic_id).data
            if vnic.public_ip:
                return vnic.public_ip
        return "(not assigned yet: see the instance page)"

    def finish(instance) -> None:
        for _ in range(20):  # the public IP appears a moment after the instance
            ip = public_ip(instance)
            if not ip.startswith("("):
                break
            time.sleep(15)
        log(f"SERVER READY: {instance.display_name}, {instance.lifecycle_state}, public IP {ip}. Hunter stopped.")
        tell_windows("Leapvoy", f"Your Oracle server is ready! Public IP {ip}")
        asyncio.run(tell_phone(ip))

    zipped = rm.get_stack_tf_config(stack_id).data.content
    tf = "\n".join(zipfile.ZipFile(io.BytesIO(zipped)).read(n).decode("utf-8", "replace")
                   for n in zipfile.ZipFile(io.BytesIO(zipped)).namelist() if n.endswith(".tf"))
    if why := shape_ok(tf):
        log(f"REFUSED: {why}. Nothing was created.")
        sys.exit(1)
    log(f"Hunting for a free ARM server with stack {rm.get_stack(stack_id).data.display_name}. Close this window to stop.")

    tries = 0
    while True:
        try:
            if inst := existing():
                finish(inst)
                return
            tries += 1
            job = rm.create_job(oci.resource_manager.models.CreateJobDetails(
                stack_id=stack_id,
                job_operation_details=oci.resource_manager.models.CreateApplyJobOperationDetails(
                    execution_plan_strategy="AUTO_APPROVED"))).data
            while job.lifecycle_state in ("ACCEPTED", "IN_PROGRESS", "CANCELING"):
                time.sleep(15)
                job = rm.get_job(job.id).data
            text = job.failure_details.message if job.failure_details else ""
            if job.lifecycle_state == "FAILED":
                text += "\n" + rm.get_job_logs_content(job.id).data[-4000:]
            verdict = classify(job.lifecycle_state, text)
        except oci.exceptions.ServiceError as e:
            verdict, text = ("slow" if e.status == 429 else "stop"), f"{e.status} {e.code}: {e.message}"
        except (oci.exceptions.RequestException, OSError) as e:  # no internet for a moment: just try again
            verdict, text = "retry", f"connection problem ({type(e).__name__})"
        if verdict == "success":
            if inst := existing():
                finish(inst)
                return
            verdict = "retry"
        if verdict == "stop":
            log(f"STOPPED on an unexpected answer from Oracle (try {tries}): {text.strip()[:500]}")
            tell_windows("Leapvoy hunter stopped", "Oracle gave an unexpected error. See private\\oci\\hunt.log")
            sys.exit(2)
        wait = SLOW if verdict == "slow" else PAUSE
        why = "too many requests" if verdict == "slow" else text if text.startswith("connection") else "Oracle is full (out of capacity)"
        log(f"try {tries}: {why}, next try in {wait // 60} min")
        time.sleep(wait)


if __name__ == "__main__":
    main()
