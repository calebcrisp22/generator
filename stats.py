"""
stats.py — /stats  /history  /botinfo
"""

import time
import discord
from discord import app_commands
from discord.ext import commands

import database as db
import utils

_START_TIME = time.time()


def _uptime_str() -> str:
    secs = int(time.time() - _START_TIME)
    days, r = divmod(secs, 86400)
    hours, r = divmod(r, 3600)
    mins = r // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if mins:
        parts.append(f"{mins}m")
    return " ".join(parts) if parts else "< 1m"


class Stats(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # /stats
    @app_commands.command(name="stats", description="Show bot-wide generate statistics.")
    @app_commands.guild_only()
    async def stats(self, interaction: discord.Interaction):
        await interaction.response.defer()

        s = db.get_generate_stats()
        total_stock = sum(db.stock_count(c) for c in utils.CATEGORIES)

        embed = discord.Embed(
            color=0x5865F2,
            title="📊 Generator Statistics",
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        # Generate counts
        embed.add_field(
            name="🎯 Total Generated",
            value=f"**{s['total']:,}** accounts",
            inline=False,
        )
        embed.add_field(name="🟢 Free",    value=f"{s['by_category'].get('free', 0):,}",    inline=True)
        embed.add_field(name="🔵 Free+",   value=f"{s['by_category'].get('free+', 0):,}",   inline=True)
        embed.add_field(name="⭐ Premium", value=f"{s['by_category'].get('premium', 0):,}", inline=True)

        # Current stock
        embed.add_field(
            name="📦 Current Stock",
            value=(
                f"🟢 Free: **{db.stock_count('free')}**   "
                f"🔵 Free+: **{db.stock_count('free+')}**   "
                f"⭐ Premium: **{db.stock_count('premium')}**\n"
                f"Total: **{total_stock}** accounts"
            ),
            inline=False,
        )

        # Uptime
        embed.add_field(name="⏱️ Uptime", value=_uptime_str(), inline=True)
        embed.add_field(name="🏓 Latency", value=f"{round(self.bot.latency * 1000)}ms", inline=True)

        embed.set_footer(
            text=f"Generator • {interaction.guild.name}",
            icon_url=interaction.guild.icon.url if interaction.guild.icon else None,
        )
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embeds=[embed])

    # /history
    @app_commands.command(name="history", description="[Owner] Show recent generate activity.")
    @app_commands.describe(limit="Number of entries to show (1–25, default 10)")
    @app_commands.guild_only()
    async def history(self, interaction: discord.Interaction, limit: int = 10):
        if not await utils.owner_only(interaction):
            return
        limit = max(1, min(limit, 25))
        logs = db.get_generate_logs(limit)

        if not logs:
            return await interaction.response.send_message(
                "📭 No generate history yet.", ephemeral=True
            )

        CAT_EMOJI = {"free": "🟢", "free+": "🔵", "premium": "⭐"}
        lines = [
            f"{CAT_EMOJI.get(e['category'], '•')} <@{e['user_id']}> — "
            f"**{e['category']}** • <t:{e['timestamp']}:R>"
            for e in logs
        ]
        embed = discord.Embed(
            color=0x5865F2,
            title=f"📋 Recent Generates — last {len(logs)}",
            description="\n".join(lines)[:4096],
        ).set_footer(text="Generator")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embeds=[embed], ephemeral=True)

    # /botinfo
    @app_commands.command(name="botinfo", description="Show bot information and version.")
    @app_commands.guild_only()
    async def botinfo(self, interaction: discord.Interaction):
        import discord as _discord
        import platform

        bot = self.bot
        total_users = sum(g.member_count or 0 for g in bot.guilds)
        cog_names = list(bot.cogs.keys())

        embed = discord.Embed(
            color=0x5865F2,
            title=f"🤖 {bot.user.name}",
            description="Discord account generator bot.",
        )
        embed.set_thumbnail(url=bot.user.display_avatar.url)
        embed.add_field(name="🏓 Latency",       value=f"{round(bot.latency * 1000)}ms", inline=True)
        embed.add_field(name="⏱️ Uptime",         value=_uptime_str(),                   inline=True)
        embed.add_field(name="🔧 Cogs Loaded",    value=str(len(cog_names)),             inline=True)
        embed.add_field(name="📡 Servers",        value=str(len(bot.guilds)),            inline=True)
        embed.add_field(name="👥 Total Users",    value=f"{total_users:,}",              inline=True)
        embed.add_field(name="📬 Commands",       value=str(len(bot.tree.get_commands())), inline=True)
        embed.add_field(
            name="🐍 Python",
            value=f"`{platform.python_version()}`",
            inline=True,
        )
        embed.add_field(
            name="📦 discord.py",
            value=f"`{_discord.__version__}`",
            inline=True,
        )
        embed.add_field(
            name="📂 Modules",
            value=", ".join(cog_names) or "None",
            inline=False,
        )
        embed.set_footer(text="Generator")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embeds=[embed])


async def setup(bot: commands.Bot):
    await bot.add_cog(Stats(bot))
