"""Discord role -> LuckPerms group synchronisation (the Discord half).

When a linked member gains or loses a mapped Discord role, we enqueue a job in
`group_sync_jobs`. The Velocity plugin (MCCGLink) consumes those jobs and applies
the LuckPerms group change in-process, which propagates to the backends via
LuckPerms' shared MySQL storage. Discord is the source of truth (one-way sync).

The role -> group map lives on the bot as `bot.role_group_map` ({role_id: group}).
"""

from __future__ import annotations

import logging
from typing import Mapping

import discord
from discord.ext import commands

log = logging.getLogger(__name__)


async def enqueue_held_roles(
    db, minecraft_uuid: str, member: discord.Member, role_group_map: Mapping[int, str]
) -> None:
    """Enqueue an 'add' for every mapped role the member currently holds.

    Used right after a fresh link so an already-roled member gets their groups
    without waiting for a role change.
    """
    held = {r.id for r in member.roles}
    for role_id, group in role_group_map.items():
        if role_id in held:
            try:
                await db.enqueue_group_sync(minecraft_uuid, group, "add")
            except Exception:
                log.exception("Failed to enqueue group '%s' for %s", group, minecraft_uuid)


class RoleSync(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        role_map: Mapping[int, str] = self.bot.role_group_map
        if not role_map:
            return

        before_ids = {r.id for r in before.roles}
        after_ids = {r.id for r in after.roles}
        gained = (after_ids - before_ids) & role_map.keys()
        lost = (before_ids - after_ids) & role_map.keys()
        if not gained and not lost:
            return  # nothing mapped changed (e.g. nickname/other role edit)

        uuid = await self.bot.db.get_minecraft_uuid(after.id)
        if uuid is None:
            return  # not linked yet; nothing to sync

        for role_id in gained:
            await self._enqueue(uuid, role_map[role_id], "add", after.id)
        for role_id in lost:
            await self._enqueue(uuid, role_map[role_id], "remove", after.id)

    async def _enqueue(self, uuid: str, group: str, action: str, discord_id: int) -> None:
        try:
            await self.bot.db.enqueue_group_sync(uuid, group, action)
            log.info("Queued %s group '%s' for %s (discord_id=%s)",
                     action, group, uuid, discord_id)
        except Exception:
            log.exception("Failed to queue %s group '%s' for %s", action, group, uuid)


async def setup(bot: commands.Bot):
    await bot.add_cog(RoleSync(bot))
