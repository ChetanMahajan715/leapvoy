from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.conftest import TEST_DATABASE_URL, alembic, requires_db


async def scalar(sql):
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.begin() as conn:
            return (await conn.execute(text(sql))).scalar()
    finally:
        await engine.dispose()


@requires_db
async def test_upgrade_creates_users_table_and_pgvector(migrated_db):
    assert await scalar("SELECT to_regclass('public.users')") == "users"
    assert await scalar("SELECT extversion FROM pg_extension WHERE extname = 'vector'")


@requires_db
async def test_upgrade_creates_telegram_tables(migrated_db):
    for table in ("telegram_accounts", "channels", "posts"):
        assert await scalar(f"SELECT to_regclass('public.{table}')") == table


@requires_db
async def test_downgrade_to_0001_removes_telegram_tables_only(migrated_db):
    alembic("downgrade", "0001")
    assert await scalar("SELECT to_regclass('public.channels')") is None
    assert await scalar("SELECT to_regclass('public.users')") == "users"
    alembic("upgrade", "head")


@requires_db
async def test_upgrade_creates_pipeline_tables_and_columns(migrated_db):
    for table in ("resumes", "resume_chunks", "jobs"):
        assert await scalar(f"SELECT to_regclass('public.{table}')") == table
    cols = await scalar(
        "SELECT string_agg(column_name, ',' ORDER BY column_name) FROM information_schema.columns "
        "WHERE table_name = 'posts' AND column_name IN ('stage','skip_reason','text_hash','match_score','emails')"
    )
    assert cols == "emails,match_score,skip_reason,stage,text_hash"
    assert await scalar(
        "SELECT count(*) FROM information_schema.columns WHERE table_name = 'resume_chunks' "
        "AND column_name IN ('embedding','embed_model','embed_lib')"
    ) == 3


@requires_db
async def test_existing_posts_start_at_stage_new(migrated_db):
    alembic("downgrade", "0002")
    await scalar(
        "WITH u AS (INSERT INTO users (id, email, password_hash) VALUES (gen_random_uuid(), 'm@x.com', '!') RETURNING id),"
        " c AS (INSERT INTO channels (user_id, tg_chat_id, title) SELECT id, -1, 't' FROM u RETURNING id, user_id)"
        " INSERT INTO posts (user_id, channel_id, tg_message_id, text, posted_at) SELECT user_id, id, 1, 'x', now() FROM c"
        " RETURNING id"
    )
    alembic("upgrade", "head")
    assert await scalar("SELECT stage FROM posts WHERE text = 'x'") == "new"
    await scalar("DELETE FROM users WHERE email = 'm@x.com' RETURNING 1")


@requires_db
async def test_downgrade_to_0002_removes_pipeline_tables(migrated_db):
    alembic("downgrade", "0002")
    assert await scalar("SELECT to_regclass('public.jobs')") is None
    assert await scalar("SELECT to_regclass('public.posts')") == "posts"
    alembic("upgrade", "head")


@requires_db
async def test_upgrade_adds_apply_link_columns(migrated_db):
    cols = await scalar(
        "SELECT string_agg(table_name || '.' || column_name, ',' ORDER BY table_name, column_name) "
        "FROM information_schema.columns WHERE (table_name, column_name) IN "
        "(('posts','links'), ('jobs','apply_links'), ('jobs','apply_method'))"
    )
    assert cols == "jobs.apply_links,jobs.apply_method,posts.links"


@requires_db
async def test_upgrade_adds_drafts_and_resume_pdf(migrated_db):
    assert await scalar("SELECT to_regclass('public.drafts')") == "drafts"
    assert await scalar(
        "SELECT count(*) FROM information_schema.columns WHERE table_name = 'resumes' AND column_name IN ('pdf','filename')"
    ) == 2


@requires_db
async def test_upgrade_adds_sending_tables_with_test_mode_on_by_default(migrated_db):
    for table in ("sender_accounts", "user_settings", "sends", "do_not_contact"):
        assert await scalar(f"SELECT to_regclass('public.{table}')") == table
    default = await scalar(
        "SELECT column_default FROM information_schema.columns WHERE table_name='user_settings' AND column_name='test_mode'"
    )
    assert default == "true"


@requires_db
async def test_downgrade_removes_users_table(migrated_db):
    alembic("downgrade", "base")
    assert await scalar("SELECT to_regclass('public.users')") is None
    alembic("upgrade", "head")  # leave DB migrated for other tests
