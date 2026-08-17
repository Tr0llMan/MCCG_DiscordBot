"""Entry point for the MCCG linking bot.

Run from the repo root with:  python -m bot.main
"""

from __future__ import annotations

import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from bot.db import Database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
log = logging.getLogger("mccg.bot")


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


class MCCGBot(commands.Bot):
    def __init__(self, *, guild_id: int, db: Database,
                 linked_role_id: int | None, code_expiry_minutes: int):
        # No privileged intents needed: slash commands work with the default set.
        super().__init__(command_prefix="!", intents=discord.Intents.default())
        self.guild_id = guild_id
        self.db = db
        self.linked_role_id = linked_role_id
        self.code_expiry_minutes = code_expiry_minutes

    async def setup_hook(self) -> None:
        await self.db.connect()
        await self.db.ensure_schema()
        await self.load_extension("bot.cogs.link")

        # Register commands to the one guild so they appear instantly (no global propagation wait).
        guild = discord.Object(id=self.guild_id)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        log.info("Slash commands synced to guild %s", self.guild_id)

    async def on_ready(self):
        log.info("Logged in as %s (id=%s)", self.user, self.user.id)

    async def close(self):
        await self.db.close()
        await super().close()


def main() -> None:
    load_dotenv()

    db = Database(
        host=_require("DB_HOST"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=_require("DB_USER"),
        password=_require("DB_PASSWORD"),
        db=_require("DB_NAME"),
    )

    role_env = os.getenv("LINKED_ROLE_ID", "").strip()
    bot = MCCGBot(
        guild_id=int(_require("GUILD_ID")),
        db=db,
        linked_role_id=int(role_env) if role_env else None,
        code_expiry_minutes=int(os.getenv("CODE_EXPIRY_MINUTES", "10")),
    )
    bot.run(_require("DISCORD_TOKEN"))


if __name__ == "__main__":
    main()
