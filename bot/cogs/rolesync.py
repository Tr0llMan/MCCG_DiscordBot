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
from discord.ext import commands, tasks

log = logging.getLogger(__name__)

# How often the bot drains role_sync_requests (rows the plugin writes on MC join).
_RECONCILE_POLL_SECONDS = 15


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
        self._reconcile_loop.start()

    def cog_unload(self) -> None:
        self._reconcile_loop.cancel()

    # --- Reconcile-on-join: drain the queue the plugin writes when a player logs in ---

    @tasks.loop(seconds=_RECONCILE_POLL_SECONDS)
    async def _reconcile_loop(self) -> None:
        role_map: Mapping[int, str] = self.bot.role_group_map
        if not role_map:
            return
        guild = self.bot.get_guild(self.bot.guild_id)
        if guild is None:
            return
        try:
            uuids = await self.bot.db.fetch_reconcile_requests(50)
        except Exception:
            log.exception("Reconcile: failed to read role_sync_requests")
            return

        for uuid in uuids:
            try:
                await self._reconcile_one(guild, uuid, role_map)
                await self.bot.db.delete_reconcile_request(uuid)
            except Exception:
                # Keep the row so it retries next cycle (e.g. transient member fetch).
                log.exception("Reconcile: failed for %s (will retry)", uuid)

    async def _reconcile_one(
        self, guild: discord.Guild, uuid: str, role_map: Mapping[int, str]
    ) -> None:
        # Primary-DB check: only reconcile accounts present in linked_accounts.
        discord_id = await self.bot.db.get_discord_id(uuid)
        if discord_id is None:
            return  # not linked in our primary DB — nothing to sync

        member = guild.get_member(discord_id)
        if member is None:
            try:
                member = await guild.fetch_member(discord_id)
            except discord.NotFound:
                return  # left the Discord server — skip, don't touch groups
            # discord.HTTPException (transient) propagates -> retried next cycle

        await enqueue_held_roles(self.bot.db, uuid, member, role_map)
        log.info("Reconciled roles for %s (discord_id=%s) on join", uuid, discord_id)

    @_reconcile_loop.before_loop
    async def _before_reconcile(self) -> None:
        await self.bot.wait_until_ready()

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
