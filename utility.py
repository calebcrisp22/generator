"""
utility.py — /announce  /dm  /help  /status  /info
"""

import time

import discord
from discord import app_commands
from discord.ext import commands

import database as db
import utils

# ── Command reference used by /help ───────────────────────────────────────────

HELP_SECTIONS = {
    "🎲 Generate": [
        ("`/generate`",       "Generate an account from stock"),
        ("`/stock`",          "View current stock counts (public)"),
    ],
    "📦 Stock (Owner)": [
        ("`/addstock`",       "Add stock from a .txt file"),
        ("`/viewstock`",      "Owner overview of stock counts"),
        ("`/clearstock`",     "Clear stock for a category or all"),
        ("`/exportstock`",    "Export stock as a .txt file"),
        ("`/setcooldown`",    "Set generate cooldown per category"),
        ("`/stockalert`",     "Alert when stock drops below a threshold"),
    ],
    "🎁 Drops (Owner)": [
        ("`/drop setup`",     "Configure the drop channel"),
        ("`/drop start`",     "Start the automatic drop loop"),
        ("`/drop stop`",      "Stop the drop loop"),
        ("`/drop status`",    "Show drop system status"),
        ("`/drop now`",       "Trigger an immediate drop"),
        ("`/drop addstock`",  "Add stock to the drop pool (.txt file)"),
        ("`/drop clearstock`","Clear drop pool stock"),
        ("`/drop viewstock`", "View drop pool counts"),
        ("`/dropcooldown`",   "Set/update drop interval"),
    ],
    "💬 Vouches": [
        ("`/vouch`",          "Leave a vouch for the service"),
        ("`/vouches`",        "View recent vouches"),
        ("`/deletevouch`",    "Delete a vouch by ID (owner)"),
    ],
    "👤 Profile & Invites": [
        ("`/profile`",        "View your profile"),
        ("`/invites`",        "Check your invite count"),
        ("`/inviteleaderboard`", "Top inviters"),
        ("`/createinvite`",   "Create a tracked invite (owner)"),
        ("`/viewjoins`",      "See who joined via a user (owner)"),
        ("`/resetinvites`",   "Reset a user's invite count (owner)"),
    ],
    "🔔 Subscriptions": [
        ("`/subscribe`",      "Grant a subscription to a user (owner)"),
        ("`/unsubscribe`",    "Remove a subscription (owner)"),
        ("`/subscription`",   "Check your subscription status"),
    ],
    "📊 Stats": [
        ("`/stats`",          "Bot-wide generate statistics"),
        ("`/history`",        "Recent generate activity (owner)"),
        ("`/botinfo`",        "Bot information and uptime"),
    ],
    "⚙️ Admin (Owner)": [
        ("`/offline`",        "Toggle generator offline/thinking mode"),
        ("`/setchannel`",     "Restrict /generate to a channel"),
        ("`/checkchannel`",   "Show current channel settings"),
        ("`/setlogchannel`",  "Set restock announcement channel"),
        ("`/setroles`",       "Bind roles to generate categories"),
        ("`/setcolor`",       "Set embed color per category"),
        ("`/setstatus`",      "Set the bot's presence"),
        ("`/setgendelay`",    "Configure the simulated /generate processing delay"),
        ("`/backup`",         "Create and download a backup of all bot data"),
        ("`/backups`",        "List recent rolling data backups"),
        ("`/setbanner`",      "Upload a banner image"),
        ("`/clearbanner`",    "Remove the banner image"),
        ("`/tokens add`",     "Add tokens to a user"),
        ("`/tokens remove`",  "Remove tokens from a user"),
        ("`/tokens balance`", "Check token balance"),
        ("`/clearcooldown`",  "Reset a user's generate cooldown"),
        ("`/resetplustime`",  "Reset plus_time for a user"),
        ("`/blacklist add`",  "Blacklist a user from generating"),
        ("`/blacklist remove`","Remove a user from the blacklist"),
        ("`/blacklist list`", "View the blacklist"),
        ("`/announce`",       "Post a formatted embed announcement"),
        ("`/dm`",             "DM a user through the bot (owner)"),
    ],
}


def format_uptime(seconds: int) -> str:
    """Format seconds to readable uptime string."""
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")

    return " ".join(parts) if parts else "< 1m"


class Utility(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # /announce
    @app_commands.command(name="announce", description="[Owner] Post a formatted embed announcement.")
    @app_commands.describe(
        channel="Channel to post in",
        title="Embed title",
        message="Embed body (supports Discord markdown)",
        color="Hex color without # (e.g. 5865F2). Defaults to blurple.",
        ping="Role to mention before the embed (optional)",
        image_url="Image URL to attach to the embed (optional)",
    )
    @app_commands.guild_only()
    async def announce(self, interaction: discord.Interaction,
                       channel: discord.TextChannel,
                       title: str,
                       message: str,
                       color: str = "5865F2",
                       ping: discord.Role = None,
                       image_url: str = None):
        if not await utils.owner_only(interaction):
            return

        if len(title) > 256:
            return await interaction.response.send_message(
                "❌ Title is too long (max 256 characters — Discord's embed title limit).", ephemeral=True
            )
        if len(message) > 4096:
            return await interaction.response.send_message(
                "❌ Message is too long (max 4096 characters — Discord's embed description limit).", ephemeral=True
            )

        try:
            embed_color = int(color.lstrip("#"), 16)
        except ValueError:
            embed_color = 0x5865F2

        embed = discord.Embed(
            color=embed_color,
            title=title,
            description=message,
        )
        embed.set_footer(
            text=interaction.guild.name,
            icon_url=interaction.guild.icon.url if interaction.guild.icon else None,
        )
        embed.timestamp = discord.utils.utcnow()
        if image_url:
            embed.set_image(url=image_url)

        content = ping.mention if ping else None
        try:
            await channel.send(content=content, embeds=[embed])
            await interaction.response.send_message(
                f"✅ Announcement posted in {channel.mention}.", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                f"❌ I don't have permission to post in {channel.mention}.", ephemeral=True
            )

    # /dm
    @app_commands.command(name="dm", description="[Owner] Send a DM to a user through the bot.")
    @app_commands.describe(
        user="User to message",
        message="Message content (plain text or markdown)",
    )
    async def dm(self, interaction: discord.Interaction,
                 user: discord.User, message: str):
        if not await utils.owner_only(interaction):
            return
        if len(message) > 4096:
            return await interaction.response.send_message(
                "❌ Message is too long (max 4096 characters).", ephemeral=True
            )
        await interaction.response.defer(ephemeral=True)

        embed = discord.Embed(
            color=0x5865F2,
            description=message,
        )
        embed.set_author(
            name=interaction.guild.name if interaction.guild else "Generator",
            icon_url=(interaction.guild.icon.url if interaction.guild and interaction.guild.icon else None),
        )
        embed.set_footer(text="This is an official message from the server team.")
        embed.timestamp = discord.utils.utcnow()

        try:
            await user.send(embeds=[embed])
            await interaction.followup.send(
                f"✅ Message sent to {user.mention}.", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send(
                f"❌ {user.mention} has DMs closed.", ephemeral=True
            )

    # /help
    @app_commands.command(name="help", description="Show all available commands.")
    @app_commands.describe(section="Filter to a specific section (optional)")
    @app_commands.choices(section=[
        app_commands.Choice(name="🎲 Generate",        value="🎲 Generate"),
        app_commands.Choice(name="📦 Stock",            value="📦 Stock (Owner)"),
        app_commands.Choice(name="🎁 Drops",            value="🎁 Drops (Owner)"),
        app_commands.Choice(name="💬 Vouches",          value="💬 Vouches"),
        app_commands.Choice(name="👤 Profile & Invites", value="👤 Profile & Invites"),
        app_commands.Choice(name="🔔 Subscriptions",   value="🔔 Subscriptions"),
        app_commands.Choice(name="📊 Stats",            value="📊 Stats"),
        app_commands.Choice(name="⚙️ Admin",            value="⚙️ Admin (Owner)"),
    ])
    @app_commands.guild_only()
    async def help(self, interaction: discord.Interaction, section: str = None):
        is_owner = utils.is_owner(str(interaction.user.id))
        OWNER_SECTIONS = {"📦 Stock (Owner)", "🎁 Drops (Owner)", "📊 Stats", "⚙️ Admin (Owner)"}

        embed = discord.Embed(
            color=0x5865F2,
            title="📖 Command Reference",
            description=(
                "All available commands. `(Owner)` sections require bot-owner access."
                if not section else f"Commands in **{section}**"
            ),
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        sections_to_show = (
            {section: HELP_SECTIONS[section]} if section and section in HELP_SECTIONS
            else HELP_SECTIONS
        )

        for header, cmds in sections_to_show.items():
            if header in OWNER_SECTIONS and not is_owner:
                continue
            lines = "\n".join(f"{name} — {desc}" for name, desc in cmds)
            embed.add_field(name=header, value=lines, inline=False)

        embed.set_footer(
            text=f"Generator • {len(self.bot.tree.get_commands())} commands total",
        )
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embeds=[embed], ephemeral=True)


    # /status
    @app_commands.command(name="status", description="Check bot health and current stock levels.")
    @app_commands.guild_only()
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer()

        # Get metrics
        uptime_seconds = time.time() - self.bot._ready_time if hasattr(self.bot, '_ready_time') else 0
        uptime_str = format_uptime(uptime_seconds)

        stock_info = []
        for cat in ["free", "free+", "premium"]:
            count = db.stock_count(cat)
            stock_info.append(f"• **{cat.upper()}**: {count} accounts")

        embed = discord.Embed(
            color=0x57F287,
            title="✅ Bot Status",
            description="System health and current metrics",
        )
        embed.add_field(name="📊 Uptime", value=uptime_str, inline=True)
        embed.add_field(name="👥 Members", value=str(sum(g.member_count for g in self.bot.guilds)), inline=True)
        embed.add_field(name="📦 Stock Levels", value="\n".join(stock_info), inline=False)
        embed.set_footer(text="Generator • All systems operational")
        embed.timestamp = discord.utils.utcnow()

        await interaction.followup.send(embeds=[embed])

    # /info
    @app_commands.command(name="info", description="View bot information and features.")
    @app_commands.guild_only()
    async def info(self, interaction: discord.Interaction):
        features = [
            "✨ Account distribution with multiple tiers",
            "📦 Real-time stock management",
            "🎁 Automatic drops system",
            "👤 User profiles & invite tracking",
            "💬 Community vouches",
            "🔔 Subscription tiers (Free, Free+, Premium)",
            "📊 Activity statistics & leaderboards",
            "⚙️ Full customization & admin controls",
        ]

        embed = discord.Embed(
            color=0x5865F2,
            title="🤖 Generator Bot",
            description="A feature-rich account distribution system for Discord communities.",
        )
        embed.add_field(name="✨ Features", value="\n".join(features), inline=False)
        embed.add_field(name="📖 Get Started", value="Use `/help` to see all commands", inline=False)
        embed.set_footer(text="Generator • Powered by discord.py")
        embed.timestamp = discord.utils.utcnow()

        await interaction.response.send_message(embeds=[embed], ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Utility(bot))
