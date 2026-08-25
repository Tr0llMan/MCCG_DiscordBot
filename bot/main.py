"""Entry point for the MCCG linking bot.

Run from the repo root with:  python -m bot.main
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

try:
    import tomllib  # Python 3.11+ (stdlib)
except ModuleNotFoundError:  # Python < 3.11 — tomli backport has the identical API
    import tomli as tomllib

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
                 linked_role_id: int | None, code_expiry_minutes: int,
                 role_group_map: dict[int, str]):
        intents = discord.Intents.default()
        # Role -> group sync needs member role-change events (a privileged intent).
        # Only request it when sync is actually configured, so the default deploy is
        # unchanged and doesn't need the portal toggle.
        if role_group_map:
            intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.guild_id = guild_id
        self.db = db
        self.linked_role_id = linked_role_id
        self.code_expiry_minutes = code_expiry_minutes
        self.role_group_map = role_group_map

    async def setup_hook(self) -> None:
        await self.db.connect()
        await self.db.ensure_schema()
        await self.load_extension("bot.cogs.link")
        if self.role_group_map:
            await self.load_extension("bot.cogs.rolesync")
            log.info("Role->group sync enabled for %d role(s)", len(self.role_group_map))

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
        role_group_map=_load_role_group_map(),
    )
    bot.run(_require("DISCORD_TOKEN"))


# rolemap.toml lives at the repo root (next to schema.sql), resolved relative to this file
# so it's found regardless of the working directory. Override with ROLE_MAP_FILE if needed.
_ROLE_MAP_PATH = Path(__file__).resolve().parent.parent / "rolemap.toml"


def _load_role_group_map() -> dict[int, str]:
    """Load the Discord-role -> LuckPerms-group map from rolemap.toml.

    Not a secret — this file is meant to be committed and edited freely. A missing file or
    an empty [roles] table disables role sync (and the members intent is not requested).
    """
    path = Path(os.getenv("ROLE_MAP_FILE", "")) if os.getenv("ROLE_MAP_FILE") else _ROLE_MAP_PATH
    if not path.exists():
        log.info("No role map at %s — role->group sync disabled.", path)
        return {}
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SystemExit(f"Could not read {path}: {exc}")

    roles = data.get("roles", {})
    result: dict[int, str] = {}
    for role_id, group in roles.items():
        try:
            result[int(role_id)] = str(group)
        except (ValueError, TypeError):
            raise SystemExit(
                f"{path}: role key {role_id!r} is not a numeric Discord role ID"
            )
    return result


if __name__ == "__main__":
    main()
