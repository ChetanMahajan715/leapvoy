"""Remove the em dash (U+2014, chr(8212)) from saved email drafts and not-yet-sent emails (user's rule, 3 Oct).
" X " becomes ", ", a joined one a hyphen. Sent emails and Telegram posts are left as they were.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-03
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

CLEAN = "replace(replace({c}, ' ' || chr(8212) || ' ', ', '), chr(8212), '-')"


def upgrade() -> None:
    op.execute(f"UPDATE drafts SET subject = {CLEAN.format(c='subject')}, body = {CLEAN.format(c='body')} "
               "WHERE strpos(subject || body, chr(8212)) > 0")
    op.execute(f"UPDATE sends SET subject = {CLEAN.format(c='subject')}, body = {CLEAN.format(c='body')} "
               "WHERE status = 'scheduled' AND strpos(subject || body, chr(8212)) > 0")


def downgrade() -> None:
    pass  # data fix only
