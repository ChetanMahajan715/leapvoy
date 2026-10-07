"""Notifications: an inbox per user (web + phone) and pushes to the user's phones through Expo's free push service.

Events only add an inbox row inside their own transaction (`add`); the sender worker pushes pending rows every round
(`push_pending`), so quiet hours, grouping and "no phone yet" are handled in one place.
"""

import uuid
from datetime import date, datetime, timedelta

import httpx
import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Device, Notification, Post, User, UserSettings
from app.pipeline import report
from app.pipeline.posts import verdict_label

log = structlog.get_logger()
EXPO_PUSH = "https://exp.host/--/api/v2/push/send"

# kind → Android channel (the app creates these channels; the user can mute any of them in Android settings too)
CHANNEL = {"job": "jobs", "summary": "jobs", "reply": "replies", "send_failed": "sending", "limit": "sending",
           "new_device": "account", "telegram_out": "account", "ai_paused": "account", "server_ready": "account"}
ALWAYS = {"new_device", "telegram_out", "server_ready"}  # security / needs action: pushed even in quiet hours
FITS = ["TOP PRIORITY", "STRONG MATCH", "APPLY"]  # Excellent, Strong, Good: the fits worth a notification
DEFAULTS = {"off": [], "min_fit": "STRONG MATCH", "quiet_from": 23, "quiet_to": 8}  # hours, India time
FRESH = timedelta(days=2)  # only new posts notify (not a 90-day backfill being checked)


async def prefs(s: AsyncSession, user_id: uuid.UUID) -> dict:
    row = await s.get(UserSettings, user_id)
    return {**DEFAULTS, **(row.notify if row else {})}


async def save_prefs(s: AsyncSession, user_id: uuid.UUID, values: dict) -> dict:
    row = await s.get(UserSettings, user_id) or UserSettings(user_id=user_id)
    row.notify = {**DEFAULTS, **(row.notify or {}), **values}
    s.add(row)
    await s.commit()
    return row.notify


async def add(s: AsyncSession, user_id: uuid.UUID, kind: str, title: str, body: str = "",
              data: dict | None = None) -> Notification | None:
    """Inbox row in the caller's transaction (the caller commits). Muted kinds are not saved at all."""
    p = await prefs(s, user_id)
    if kind in p["off"]:
        return None
    data = data or {}
    push = "pending"
    if kind == "job" and data.get("verdict") in FITS and FITS.index(data["verdict"]) > FITS.index(p["min_fit"]):
        push = "none"  # in the inbox, but below the fit the user wants a buzz for
    n = Notification(user_id=user_id, kind=kind, title=title[:200], body=body, data=data, push=push)
    s.add(n)
    return n


async def once(s: AsyncSession, user_id: uuid.UUID, kind: str, key: str, title: str, body: str = "",
               data: dict | None = None) -> Notification | None:
    """`add`, but only one per key (e.g. one 'daily limit' per account per day)."""
    seen = await s.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == user_id, Notification.kind == kind, Notification.data["key"].astext == key))
    return None if seen else await add(s, user_id, kind, title, body, {**(data or {}), "key": key})


def quiet(p: dict, now: datetime) -> bool:
    hour, a, b = now.astimezone(report.IST).hour, p["quiet_from"], p["quiet_to"]
    if a == b:
        return False  # quiet hours turned off
    return a <= hour < b if a < b else hour >= a or hour < b


async def job_alerts(s: AsyncSession, post: Post, jobs, now: datetime) -> None:
    """After a post is scored: one inbox row per good fit (fresh posts only)."""
    if post.posted_at < now - FRESH:
        return
    for j in jobs:
        if j.verdict not in FITS:
            continue
        email = j.apply_method == "email" and j.hr_emails
        facts = [j.location, j.salary, j.experience, "Email ready" if email else "Apply link"]
        await once(s, post.user_id, "job", f"job:{j.id}",  # a re-check with a new resume never alerts twice
                   f"{j.fit_score} · {verdict_label(j.verdict)} · {j.role}, {j.company}",
                   " · ".join(f for f in facts if f),
                   {"job_id": j.id, "verdict": j.verdict, "score": j.fit_score, "screen": "jobs",
                    "date": post.posted_at.astimezone(report.IST).date().isoformat()})


async def send_expo(messages: list[dict]) -> list[dict]:
    """Expo push service: up to 100 messages per request; returns one ticket per message."""
    tickets: list[dict] = []
    async with httpx.AsyncClient(timeout=20) as client:
        for i in range(0, len(messages), 100):
            r = await client.post(EXPO_PUSH, json=messages[i:i + 100], headers={"accept": "application/json"})
            r.raise_for_status()
            tickets += r.json().get("data", [])
    return tickets


def _messages(rows: list[Notification]) -> list[tuple[str, str, dict, str]]:
    """Several job alerts at once → one 'N new jobs' notification (best first); everything else one by one."""
    jobs = sorted((n for n in rows if n.kind == "job"), key=lambda n: -(n.data.get("score") or 0))
    out = [(n.title, n.body, {**n.data, "id": n.id}, CHANNEL.get(n.kind, "account")) for n in rows if n.kind != "job"]
    if len(jobs) == 1:
        n = jobs[0]
        out.append((n.title, n.body, {**n.data, "id": n.id}, "jobs"))
    elif jobs:
        best = jobs[0]
        out.append((f"{len(jobs)} new jobs for you", f"Best: {best.title}",
                    {"screen": "jobs", "date": best.data.get("date")}, "jobs"))
    return out


async def push_pending(s: AsyncSession, now: datetime) -> int:
    """Push waiting inbox rows to each user's phones. Quiet hours keep them waiting (security ones go anyway)."""
    rows = (await s.execute(select(Notification).join(User, User.id == Notification.user_id).where(
        Notification.push == "pending", User.delete_after.is_(None)).order_by(Notification.id).limit(500))).scalars().all()
    by_user: dict[uuid.UUID, list[Notification]] = {}
    for n in rows:
        by_user.setdefault(n.user_id, []).append(n)
    messages, owners, done = [], [], []
    for user_id, items in by_user.items():
        if quiet(await prefs(s, user_id), now):
            items = [n for n in items if n.kind in ALWAYS]
        devices = (await s.execute(select(Device).where(
            Device.user_id == user_id, Device.revoked_at.is_(None), Device.push_token.is_not(None)))).scalars().all()
        if not devices:  # no phone with the app yet: the inbox has them
            for n in items:
                n.push = "none"
            continue
        done += items
        for title, body, data, channel in _messages(items):
            for d in devices:
                messages.append({"to": d.push_token, "title": title, "body": body, "data": data,
                                 "channelId": channel, "sound": "default", "priority": "high"})
                owners.append(d)
    if messages:
        try:
            tickets = await send_expo(messages)
        except httpx.HTTPError as e:  # Expo or internet down: keep them pending, next round tries again
            log.warning("notify.push_failed", error=repr(e)[:200])
            return 0
        for d, t in zip(owners, tickets):
            if t.get("status") == "error" and (t.get("details") or {}).get("error") == "DeviceNotRegistered":
                d.push_token = None  # app uninstalled or notifications turned off
    for n in done:
        n.push = "sent"
    await s.commit()
    return len(messages)


async def morning_summary(s: AsyncSession, now: datetime) -> int:
    """After 9 AM India time (and after quiet hours): yesterday in one line, once a day."""
    from app.api.stats import compute  # import here: api.stats imports pipeline modules that import this one

    local = now.astimezone(report.IST)
    if local.hour < 9:
        return 0
    yesterday: date = local.date() - timedelta(days=1)
    users = (await s.execute(select(User.id).where(User.delete_after.is_(None), User.password_hash != "!"))).scalars().all()
    made = 0
    for user_id in users:
        if quiet(await prefs(s, user_id), now):
            continue
        st = await compute(s, user_id, now=now, day=yesterday)
        f = st["funnel"]
        if not f["posts"] and not f["sent"]:
            continue
        parts = [f"{f['posts']} posts", f"{f['fit']} fit you", f"{f['sent']} emails sent"]
        if f["replies"]:
            parts.append(f"{f['replies']} replies")
        if await once(s, user_id, "summary", yesterday.isoformat(), f"Yesterday: {', '.join(parts)}",
                      "Open Jobs to see today's posts.", {"screen": "stats", "date": yesterday.isoformat()}):
            made += 1
    await s.commit()
    return made


async def set_token(s: AsyncSession, device: Device, token: str | None) -> None:
    """This phone's push token. A phone belongs to one account at a time: the token leaves any other device row."""
    if token:
        await s.execute(update(Device).where(Device.push_token == token, Device.id != device.id).values(push_token=None))
    device.push_token = token
    await s.commit()
