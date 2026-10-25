#!/bin/sh
set -e

# Run alembic migrations only if the database has no alembic_version table
# (i.e., it's a fresh postgres instance). If the table exists, skip migrations
# to avoid interfering with an existing schema.
python -c "
import sys, asyncio, asyncpg, os

async def check():
    url = os.environ['DATABASE_URL']
    # asyncpg needs a postgres:// scheme, not postgresql+asyncpg://
    dsn = url.replace('postgresql+asyncpg://', 'postgres://')
    conn = await asyncpg.connect(dsn)
    row = await conn.fetchval(
        \"SELECT to_regclass('public.alembic_version')\"
    )
    await conn.close()
    # Exit 0 if table does NOT exist (fresh DB → run migrations)
    sys.exit(0 if row is None else 1)

asyncio.run(check())
" && {
    echo "Fresh database detected — running alembic upgrade head"
    alembic upgrade head
} || {
    echo "Existing database detected — skipping alembic migrations"
}

exec python -m rest_api
