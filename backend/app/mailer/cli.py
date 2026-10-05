"""Email CLI (the app's job cards and settings replace this in Steps 7–8).

  python -m app.mailer.cli draft      --email me@x.com --job 12
  python -m app.mailer.cli drafts     --email me@x.com [--date today|yesterday|YYYY-MM-DD]
  python -m app.mailer.cli sender-add --email me@x.com --address you@gmail.com      (asks for the App Password)
  python -m app.mailer.cli test-mode  --email me@x.com on|off|status               (off asks you to type YES)
  python -m app.mailer.cli approve    --email me@x.com --job 12 [--at "tomorrow 10am"] [--to hr@x.com]
  python -m app.mailer.cli cancel     --email me@x.com --send 3
  python -m app.mailer.cli reschedule --email me@x.com --send 3 --at "monday 10am"
  python -m app.mailer.cli outbox     --email me@x.com
  python -m app.mailer.cli send-due   --email me@x.com                             (send what is due now)
  python -m app.mailer.cli replies    --email me@x.com                             (check inbox for HR replies)
"""

import argparse
import asyncio
import getpass
import sys
from datetime import UTC, datetime

from sqlalchemy import select

from app.accounts.profile import get_profile
from app.db.models import Draft, Job, Resume, Send
from app.db.session import get_sessionmaker
from app.mailer import drafts, outbox, replies, senders
from app.mailer.when import parse_when
from app.pipeline import report
from app.pipeline.report import IST
from app.pipeline.resume import link_mismatches, pdf_links
from app.telegram.store import get_or_create_user


def confirm_live() -> bool:
    print("Test mode OFF means approved emails go to REAL HR addresses.")
    return input("Type YES to continue: ").strip() == "YES"


async def show(s, draft: Draft) -> None:
    resume = await s.get(Resume, draft.resume_id)
    size = f"{len(resume.pdf) // 1024} KB" if resume.pdf else "PDF MISSING: run resume-add again"
    print("=" * 78)
    print(f"Job #{draft.job_id} · status: {draft.status.upper()}"
          + ("  · OUTDATED (newer resume active, run draft again)" if await drafts.is_outdated(s, draft) else ""))
    print(f"To:         {', '.join(draft.to_emails)}")
    print(f"Subject:    {draft.subject}")
    print(f"Attachment: {resume.filename or 'resume.pdf'} ({size})")
    print("-" * 78)
    print(draft.body)
    print("-" * 78)
    for issue in draft.issues:
        print(f"NEEDS REVIEW: {issue}")
    if resume.pdf:
        for w in link_mismatches(pdf_links(resume.pdf), await get_profile(s, draft.user_id)):
            print(f"WARNING: {w}")


async def draft_one(s, user_id, job_id: int) -> None:
    try:
        d = await drafts.write_draft(s, user_id, job_id)
    except drafts.JobNotFound:
        sys.exit(f"No job #{job_id}.")
    except drafts.NotAnEmailJob:
        sys.exit(f"Job #{job_id} is applied to through a link/form, not by email.")
    except drafts.NoResume:
        sys.exit("Add a resume first (python -m app.pipeline.cli resume-add ...).")
    await show(s, d)


async def draft_day(s, user_id, d) -> None:
    job_ids = await drafts.email_jobs_needing_drafts(s, user_id, *report.day_bounds(d))
    print(f"{len(job_ids)} email job(s) on {d:%d %b %Y} need a draft.")
    for job_id in job_ids:
        await show(s, await drafts.write_draft(s, user_id, job_id))


async def sender_add(s, user_id, address: str) -> None:
    provider = senders.PROVIDERS[senders.provider_for(address)]
    print(f"Create an App Password here: {provider.app_password_help}")
    password = getpass.getpass("App Password (hidden while typing): ")
    name = (await get_profile(s, user_id)).get("full_name") or "Leapvoy"
    try:
        acc = await senders.add_sender(s, user_id, address, password, name=name)
    except senders.SenderLoginFailed as e:
        sys.exit(str(e))
    print(f"OK: {acc.email} connected{' (default sender)' if acc.is_default else ''}. "
          "A test email was sent to that inbox. Check it arrived.")


def when_text(t: datetime) -> str:
    return f"{t.astimezone(IST):%a %d %b, %I:%M %p} IST"


async def show_outbox(s, user_id) -> None:
    rows = (await s.execute(
        select(Send, Job).join(Job, Send.job_id == Job.id).where(Send.user_id == user_id).order_by(Send.send_at)
    )).tuples().all()
    print(f"Test mode: {'ON (all mail goes to you)' if await outbox.is_test_mode(s, user_id) else 'OFF (real HR)'}")
    for send, job in rows:
        replied = f"  REPLIED {send.replied_at.astimezone(IST):%d %b}" if send.replied_at else ""
        print(f"#{send.id:<4} {send.status:<10} {when_text(send.sent_at or send.send_at):<28} "
              f"{'[TEST] ' if send.test_mode else ''}{job.company} · {job.role} → {send.to_email}{replied}"
              + (f"\n      {send.error}" if send.error else ""))
    print(f"\n{len(rows)} email(s).")


async def send_due(s) -> None:
    now = datetime.now(UTC)
    due = await outbox.due_sends(s, now, limit=50)
    for send in due:
        print(f"#{send.id}: {await outbox.deliver(s, send.id, now=now)}")
    print(f"{len(due)} due email(s) processed.")


async def run(a) -> None:
    async with get_sessionmaker()() as s:
        user_id = await get_or_create_user(s, a.email)
        try:
            match a.cmd:
                case "draft":
                    await draft_one(s, user_id, a.job)
                case "drafts":
                    await draft_day(s, user_id, a.date)
                case "sender-add":
                    await sender_add(s, user_id, a.address)
                case "test-mode":
                    if a.state == "off" and not confirm_live():
                        sys.exit("Test mode stays ON.")
                    if a.state != "status":
                        await outbox.set_test_mode(s, user_id, a.state == "on")
                    on = await outbox.is_test_mode(s, user_id)
                    print(f"Test mode is {'ON: every email goes to your own inbox' if on else 'OFF: emails go to HR'}.")
                case "approve":
                    send = await outbox.approve(s, user_id, a.job, parse_when(a.at), to=a.to)
                    print(f"OK: email #{send.id} scheduled for {when_text(send.send_at)} → "
                          f"{send.to_email}{'  (TEST MODE: goes to your own inbox)' if send.test_mode else ''}")
                case "cancel":
                    await outbox.cancel(s, user_id, a.send)
                    print(f"OK: email #{a.send} cancelled.")
                case "reschedule":
                    send = await outbox.reschedule(s, user_id, a.send, parse_when(a.at))
                    print(f"OK: email #{send.id} now at {when_text(send.send_at)}.")
                case "outbox":
                    await show_outbox(s, user_id)
                case "send-due":
                    await send_due(s)
                case "replies":
                    print(f"{await replies.check_replies(s, user_id)} new reply(ies).")
        except (outbox.NotAllowed, drafts.JobNotFound, ValueError) as e:
            sys.exit(f"Not done: {e}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m app.mailer.cli", description="Leapvoy emails")
    sub = p.add_subparsers(dest="cmd", required=True)
    specs = {
        "draft": "write/rewrite the email for one job and show it",
        "drafts": "write emails for all email jobs of a day that fit your resume",
        "sender-add": "connect a sender email (App Password)",
        "test-mode": "on / off / status. ON sends every email to your own inbox",
        "approve": "approve a job's email and schedule it (default: now)",
        "cancel": "cancel a scheduled email",
        "reschedule": "move a scheduled email",
        "outbox": "list scheduled and sent emails",
        "send-due": "send the emails that are due now (the server worker does this automatically)",
        "replies": "check your inbox for HR replies",
    }
    for name, help_ in specs.items():
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("--email", required=True, help="your Leapvoy login email")
        if name in ("draft", "approve"):
            sp.add_argument("--job", required=True, type=int)
        if name == "drafts":
            sp.add_argument("--date", type=report.parse_day, default="today", help="today | yesterday | YYYY-MM-DD")
        if name == "sender-add":
            sp.add_argument("--address", required=True, help="the email to send from, e.g. you@gmail.com")
        if name == "test-mode":
            sp.add_argument("state", choices=["on", "off", "status"])
        if name == "approve":
            sp.add_argument("--at", default="now", help='"now", "tomorrow 10am", "monday 10am", "2026-10-01 11:15"')
            sp.add_argument("--to", help="which HR address, if the job lists several")
        if name in ("cancel", "reschedule"):
            sp.add_argument("--send", required=True, type=int, help="email # from outbox")
        if name == "reschedule":
            sp.add_argument("--at", required=True)
    a = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    asyncio.run(run(a))


if __name__ == "__main__":
    main()
