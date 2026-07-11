"""
blacklist.py — /blacklist add / remove / list
Blacklisted users are silently blocked from /generate.
"""

import discord
from discord import app_commands
from discord.ext import commands

import database as db
import utils


class Blacklist(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    bl = app_commands.Group(name="blacklist", description="Manage the generate blacklist.")

    @bl.command(name="add", description="[Owner] Prevent a user from generating accounts.")
    @app_commands.describe(user="User to blacklist", reason="Reason (optional, shown to mods)")
    async def bl_add(self, interaction: discord.Interaction,
                     user: discord.User, reason: str = "No reason given"):
        if not await utils.owner_only(interaction):
            return
        added = db.blacklist_add(str(user.id), reason)
        if not added:
            return await interaction.response.send_message(
                f"⚠️ {user.mention} is already blacklisted.", ephemeral=True
            )
        embed = discord.Embed(
            color=0xED4245, title="🔨 User Blacklisted",
            description=f"{user.mention} can no longer use `/generate`.",
        )
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text="Generator")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embeds=[embed])

    @bl.command(name="remove", description="[Owner] Restore a user's generate access.")
    @app_commands.describe(user="User to unblacklist")
    async def bl_remove(self, interaction: discord.Interaction, user: discord.User):
        if not await utils.owner_only(interaction):
            return
        removed = db.blacklist_remove(str(user.id))
        if not removed:
            return await interaction.response.send_message(
                f"⚠️ {user.mention} isn't blacklisted.", ephemeral=True
            )
        embed = discord.Embed(
            color=0x57F287, title="✅ Blacklist Removed",
            description=f"{user.mention} can generate accounts again.",
        ).set_footer(text="Generator")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embeds=[embed])

    @bl.command(name="list", description="[Owner] View all blacklisted users.")
    async def bl_list(self, interaction: discord.Interaction):
        if not await utils.owner_only(interaction):
            return
        entries = db.get_blacklist()
        if not entries:
            return await interaction.response.send_message(
                "✅ Blacklist is empty.", ephemeral=True
            )
        lines = []
        for e in entries[:25]:
            ts = f" • <t:{e['added_at']}:R>" if e.get("added_at") else ""
            reason = f" — {e['reason']}" if e.get("reason") and e["reason"] != "No reason given" else ""
            lines.append(f"<@{e['user_id']}>{reason}{ts}")

        embed = discord.Embed(
            color=0xED4245,
            title=f"🔨 Blacklist — {len(entries)} user(s)",
            description="\n".join(lines)[:4096],
        ).set_footer(text="Generator • /blacklist remove to unban")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embeds=[embed], ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Blacklist(bot))
