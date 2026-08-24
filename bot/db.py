"""Async MySQL access for the linking bot.

The bot only ever *reads* pending codes and *writes* links; the Velocity plugin
is what generates codes and reads link status. Both sides share the same schema
(see schema.sql), so this module keeps its SQL in lock-step with the plugin.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

import aiomysql

log = logging.getLogger(__name__)

# Table names cannot be passed as SQL parameters, so a configurable one is
# interpolated into the query. Restrict it to a safe identifier just in case.
_IDENTIFIER_RE = re.compile(r"\A[A-Za-z0-9_]+\Z")

# Kept identical to schema.sql so the bot can bootstrap an empty database on its own.
_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS linked_accounts (
        minecraft_uuid CHAR(36)    NOT NULL PRIMARY KEY,
        minecraft_name VARCHAR(16) NOT NULL,
        discord_id     BIGINT      NOT NULL UNIQUE,
        linked_at      TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS link_codes (
        code           CHAR(6)     NOT NULL PRIMARY KEY,
        minecraft_uuid CHAR(36)    NOT NULL UNIQUE,
        minecraft_name VARCHAR(16) NOT NULL,
        created_at     TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
)


@dataclass(frozen=True)
class PendingCode:
    """A row from link_codes, plus whether it is still within the expiry window."""

    code: str
    minecraft_uuid: str
    minecraft_name: str
    still_valid: bool


class LinkError(Exception):
    """Raised when a link cannot be created (e.g. the account is already linked)."""


class Database:
    """Thin async wrapper around an aiomysql connection pool."""

    def __init__(self, *, host: str, port: int, user: str, password: str, db: str,
                 discordsrv_accounts_table: Optional[str] = None):
        self._config = dict(host=host, port=port, user=user, password=password, db=db)
        self._pool: Optional[aiomysql.Pool] = None
        # DiscordSRV owns its own account table (created by DiscordSRV on boot). When set,
        # every new link is mirrored into it so DiscordSRV's group-role sync recognises the
        # player without anyone having to relink. Blank/None disables the mirror.
        if discordsrv_accounts_table and not _IDENTIFIER_RE.match(discordsrv_accounts_table):
            raise ValueError(
                f"DISCORDSRV_ACCOUNTS_TABLE must be a plain table identifier, "
                f"got: {discordsrv_accounts_table!r}"
            )
        self._discordsrv_accounts_table = discordsrv_accounts_table or None

    async def connect(self) -> None:
        self._pool = await aiomysql.create_pool(
            autocommit=True,
            charset="utf8mb4",
            **self._config,
        )
        log.info("Connected to MySQL at %s:%s/%s",
                 self._config["host"], self._config["port"], self._config["db"])

    async def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None

    async def ensure_schema(self) -> None:
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                for statement in _SCHEMA_STATEMENTS:
                    await cur.execute(statement)

    async def get_code(self, code: str, expiry_minutes: int) -> Optional[PendingCode]:
        """Look up a pending code. Returns None if it does not exist.

        Validity is evaluated with the database's own clock (NOW()) so the bot
        and the DB server never disagree about whether a code has expired.
        """
        query = (
            "SELECT code, minecraft_uuid, minecraft_name, "
            "       (created_at >= NOW() - INTERVAL %s MINUTE) AS still_valid "
            "FROM link_codes WHERE code = %s"
        )
        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(query, (expiry_minutes, code))
                row = await cur.fetchone()
        if row is None:
            return None
        return PendingCode(
            code=row["code"],
            minecraft_uuid=row["minecraft_uuid"],
            minecraft_name=row["minecraft_name"],
            still_valid=bool(row["still_valid"]),
        )

    async def create_link(self, code: PendingCode, discord_id: int) -> None:
        """Atomically bind the Minecraft account to a Discord user.

        Runs inside a transaction: we re-check both uniqueness guards and consume
        the pending code so a code can never be redeemed twice. Raises LinkError
        if either the Discord user or the Minecraft account is already linked.
        """
        async with self._pool.acquire() as conn:
            await conn.begin()
            try:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT 1 FROM linked_accounts WHERE discord_id = %s",
                        (discord_id,),
                    )
                    if await cur.fetchone() is not None:
                        raise LinkError("Your Discord account is already linked.")

                    await cur.execute(
                        "SELECT 1 FROM linked_accounts WHERE minecraft_uuid = %s",
                        (code.minecraft_uuid,),
                    )
                    if await cur.fetchone() is not None:
                        raise LinkError("That Minecraft account is already linked.")

                    await cur.execute(
                        "INSERT INTO linked_accounts "
                        "(minecraft_uuid, minecraft_name, discord_id) VALUES (%s, %s, %s)",
                        (code.minecraft_uuid, code.minecraft_name, discord_id),
                    )
                    # Consume the code so it cannot be reused.
                    await cur.execute(
                        "DELETE FROM link_codes WHERE code = %s", (code.code,)
                    )
                    # Mirror the link into DiscordSRV's own account table (best effort).
                    await self._mirror_to_discordsrv(cur, discord_id, code.minecraft_uuid)
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

    async def _mirror_to_discordsrv(self, cur, discord_id: int, minecraft_uuid: str) -> None:
        """Copy a freshly created link into DiscordSRV's accounts table.

        Best effort: if the table is missing (DiscordSRV not booted yet) or the insert
        otherwise fails, we log and let the core link stand. A failed statement does not
        abort the surrounding InnoDB transaction, so the linked_accounts row still commits;
        the one-time import / periodic reconciliation heals any missed mirror.
        """
        if self._discordsrv_accounts_table is None:
            return
        try:
            await cur.execute(
                f"INSERT IGNORE INTO {self._discordsrv_accounts_table} (discord, uuid) "
                "VALUES (%s, %s)",
                (str(discord_id), minecraft_uuid),
            )
        except Exception:
            log.warning(
                "Could not mirror link (discord=%s uuid=%s) into DiscordSRV table %s; "
                "the link itself was saved. Run the reconciliation import to backfill.",
                discord_id, minecraft_uuid, self._discordsrv_accounts_table,
                exc_info=True,
            )
