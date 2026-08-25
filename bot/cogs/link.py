"""The /link slash command — the Discord half of account linking."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.db import LinkError
from bot.cogs.rolesync import enqueue_held_roles

log = logging.getLogger(__name__)


class Link(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="link",
        description="Link your Minecraft account using the code shown when you were kicked.",
    )
    @app_commands.describe(code="The 6-character code from the kick message.")
    async def link(self, interaction: discord.Interaction, code: str):
        # Ephemeral so codes and results stay private to the user.
        await interaction.response.defer(ephemeral=True)

        normalized = code.strip().upper()
        if len(normalized) != 6 or not normalized.isalnum():
            await interaction.followup.send(
                "That doesn't look like a valid code. It should be 6 letters/numbers, "
                "e.g. `A1B2C3`.",
                ephemeral=True,
            )
            return

        pending = await self.bot.db.get_code(normalized, self.bot.code_expiry_minutes)
        if pending is None:
            await interaction.followup.send(
                "Invalid code. Double-check it, or relog on the server to get a fresh one.",
                ephemeral=True,
            )
            return
        if not pending.still_valid:
            await interaction.followup.send(
                "That code has expired. Relog on the server to get a new one.",
                ephemeral=True,
            )
            return

        try:
            await self.bot.db.create_link(pending, interaction.user.id)
        except LinkError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except Exception:
            log.exception("Failed to create link for discord_id=%s", interaction.user.id)
            await interaction.followup.send(
                "Something went wrong linking your account. Please try again shortly.",
                ephemeral=True,
            )
            return

        await self._maybe_grant_role(interaction)

        # Grant any LuckPerms groups the member's current Discord roles map to, so a
        # freshly linked (already-roled) member doesn't have to wait for a role change.
        if self.bot.role_group_map and isinstance(interaction.user, discord.Member):
            await enqueue_held_roles(
                self.bot.db, pending.minecraft_uuid, interaction.user,
                self.bot.role_group_map,
            )

        await interaction.followup.send(
            f"Linked to **{pending.minecraft_name}**! You can now join the server.",
            ephemeral=True,
        )
        log.info("Linked %s (%s) -> discord_id=%s",
                 pending.minecraft_name, pending.minecraft_uuid, interaction.user.id)

    async def _maybe_grant_role(self, interaction: discord.Interaction) -> None:
        role_id = self.bot.linked_role_id
        if not role_id or not isinstance(interaction.user, discord.Member):
            return
        role = interaction.guild.get_role(role_id)
        if role is None:
            log.warning("LINKED_ROLE_ID=%s not found in guild %s", role_id, interaction.guild_id)
            return
        try:
            await interaction.user.add_roles(role, reason="Linked Minecraft account")
        except discord.Forbidden:
            log.warning("Missing permission to grant role %s in guild %s",
                        role_id, interaction.guild_id)


async def setup(bot: commands.Bot):
    await bot.add_cog(Link(bot))
