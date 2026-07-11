"""
stock.py — Stock management commands (owner-only).
/addstock  /viewstock  /clearstock  /setcooldown  /exportstock  /stockalert
"""

import io
import time
import discord
from discord import app_commands
from discord.ext import commands, tasks

import database as db
import utils
from utils import fetch_text, FetchTextError

CAT_LABELS = {"free": "🟢 Free", "free+": "🔵 Free+", "premium": "⭐ Premium"}

# Cooldown: don't re-fire an alert for the same category within this window (seconds)
ALERT_REFIRE_COOLDOWN = 3600


class Stock(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.stock_alert_loop.start()

    def cog_unload(self):
        self.stock_alert_loop.cancel()

    # ── Background stock-alert loop ────────────────────────────────────────────

    @tasks.loop(seconds=60)
    async def stock_alert_loop(self):
        await self.bot.wait_until_ready()
        alerts = db.get_stock_alerts()
        now = int(time.time())
        for category, cfg in alerts.items():
            count = db.stock_count(category)
            threshold = int(cfg.get("threshold", 0))
            if count > threshold:
                continue
            # Don't spam — re-fire at most once per hour
            if now - int(cfg.get("last_fired", 0)) < ALERT_REFIRE_COOLDOWN:
                continue
            channel_id = cfg.get("channel_id")
            if not channel_id:
                continue
            try:
                channel = await self.bot.fetch_channel(int(channel_id))
            except Exception:
                continue
            role_id = cfg.get("role_id")
            mention = f"<@&{role_id}> " if role_id else ""
            embed = discord.Embed(
                color=0xFEE75C,
                title="⚠️ Low Stock Alert",
                description=(
                    f"{CAT_LABELS.get(category, category)} stock has dropped to "
                    f"**{count}** account(s) — at or below the alert threshold of **{threshold}**.\n\n"
                    f"Use `/addstock` to restock."
                ),
            )
            embed.set_footer(text="Generator • Stock Alert")
            embed.timestamp = discord.utils.utcnow()
            try:
                await channel.send(content=mention or None, embeds=[embed])
                db.update_stock_alert_fired(category)
            except Exception:
                pass

    @stock_alert_loop.before_loop
    async def before_alert_loop(self):
        await self.bot.wait_until_ready()

    # /stock — public stock overview with status bars (mirrors stockview.js)
    @app_commands.command(name="stock", description="View how many accounts are available in each tier.")
    @app_commands.guild_only()
    async def stock(self, interaction: discord.Interaction):
        free    = db.stock_count("free")
        freepl  = db.stock_count("free+")
        premium = db.stock_count("premium")
        total   = free + freepl + premium

        # Reference cap for bar fill — scales up if stock is unusually high, floors at 20
        cap = max(20, free, freepl, premium)

        def status_word(count: int) -> str:
            if count == 0:
                return "🔴 Out of Stock"
            if count < 5:
                return "🟡 Low Stock"
            return "🟢 In Stock"

        def field(count: int) -> str:
            return f"`{utils.progress_bar(count, cap)}`\n{status_word(count)} • **{count}** available"

        embed = discord.Embed(
            color=0x5865F2,
            title="📦 Account Stock",
            description=f"**{total}** total accounts available across all tiers",
        )
        embed.add_field(name="🟢 Free",    value=field(free),    inline=False)
        embed.add_field(name="🔵 Free+",   value=field(freepl),  inline=False)
        embed.add_field(name="⭐ Premium", value=field(premium), inline=False)
        embed.set_footer(text="Generator • Use /generate to claim an account")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embeds=[embed])

    # /addstock — file upload (.txt)
    @app_commands.command(name="addstock",
                          description="[Owner] Add stock from a .txt file — one account per line.")
    @app_commands.describe(
        category="Account category to add to",
        file=".txt file — one account per line (email:password or any format)",
    )
    @app_commands.choices(category=[
        app_commands.Choice(name="🟢 Free",    value="free"),
        app_commands.Choice(name="🔵 Free+",   value="free+"),
        app_commands.Choice(name="⭐ Premium", value="premium"),
    ])
    @app_commands.guild_only()
    async def addstock(self, interaction: discord.Interaction,
                       category: str, file: discord.Attachment):
        if not await utils.owner_only(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        if not file.filename.endswith(".txt"):
            return await interaction.followup.send("❌ Please attach a `.txt` file.", ephemeral=True)

        try:
            text = await fetch_text(file.url)
        except Exception as exc:
            return await interaction.followup.send(f"❌ Failed to read file: {exc}", ephemeral=True)

        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if not lines:
            return await interaction.followup.send("❌ The file is empty.", ephemeral=True)

        added = db.add_stock_bulk(category, lines)
        total = db.stock_count(category)
        cat_label = CAT_LABELS.get(category, category)
        stock_summary = "   •   ".join(
            f"{CAT_LABELS[c]} **{db.stock_count(c)}**" for c in ["free", "free+", "premium"]
        )

        embed = discord.Embed(color=0x57F287, title="✅ Stock Added")
        embed.add_field(name="Category", value=cat_label, inline=True)
        embed.add_field(name="Added",    value=str(added), inline=True)
        embed.add_field(name="Total",    value=str(total), inline=True)
        embed.add_field(name="📊 All Stock", value=stock_summary, inline=False)
        embed.set_footer(text="Generator")
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embeds=[embed], ephemeral=True)

        # Restock announcement to log channel
        log_channel_id = db.get_config("log_channel")
        if log_channel_id:
            try:
                ch = await self.bot.fetch_channel(int(log_channel_id))
                gen_image = db.get_config("gen_image", "")
                announce = discord.Embed(
                    color=0x57F287,
                    title="📦 Stock Restocked!",
                    description=(
                        f"**{added}** new {cat_label} account"
                        f"{'s' if added != 1 else ''} just dropped!"
                    ),
                )
                announce.add_field(name="Category",      value=cat_label,     inline=True)
                announce.add_field(name="Just Added",    value=str(added),    inline=True)
                announce.add_field(name="Now in Stock",  value=str(total),    inline=True)
                announce.add_field(name="📊 Available Now", value=stock_summary, inline=False)
                announce.set_footer(text="Generator • Use /generate to claim one")
                announce.timestamp = discord.utils.utcnow()
                if gen_image and gen_image.startswith("http"):
                    announce.set_image(url=gen_image)
                await ch.send(embeds=[announce])
            except Exception:
                pass

    # /viewstock
    @app_commands.command(name="viewstock", description="[Owner] View current stock counts.")
    @app_commands.guild_only()
    async def viewstock(self, interaction: discord.Interaction):
        if not await utils.owner_only(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        counts = {c: db.stock_count(c) for c in utils.CATEGORIES}
        total = sum(counts.values())
        cap = max(20, *counts.values())
        embed = discord.Embed(
            color=0x5865F2,
            title="📦 Stock Overview",
            description=f"**{total}** total accounts across all categories",
        ).set_footer(text="Generator")
        embed.timestamp = discord.utils.utcnow()
        for cat, label in zip(utils.CATEGORIES, [CAT_LABELS[c] for c in utils.CATEGORIES]):
            count = counts[cat]
            embed.add_field(
                name=label,
                value=f"`{utils.progress_bar(count, cap)}`\n**{count}** account(s)",
                inline=False,
            )
        await interaction.followup.send(embeds=[embed], ephemeral=True)

    # /clearstock
    @app_commands.command(name="clearstock",
                          description="[Owner] Clear stock for a category (or all).")
    @app_commands.describe(category="Category to clear, or 'all' to wipe everything")
    @app_commands.choices(category=[
        app_commands.Choice(name="🟢 Free",    value="free"),
        app_commands.Choice(name="🔵 Free+",   value="free+"),
        app_commands.Choice(name="⭐ Premium", value="premium"),
        app_commands.Choice(name="All",        value="all"),
    ])
    async def clearstock(self, interaction: discord.Interaction, category: str):
        if not await utils.owner_only(interaction):
            return
        target = None if category == "all" else category
        label = category if target else "ALL categories"

        view = utils.ConfirmView(interaction.user.id)
        await interaction.response.send_message(
            f"⚠️ This will permanently delete every account currently in **{label}** stock. Continue?",
            view=view, ephemeral=True,
        )
        await view.wait()
        if not view.confirmed:
            return

        removed = db.clear_stock(target)
        embed = discord.Embed(
            color=0xED4245, title="🗑️ Stock Cleared",
            description=f"Removed **{removed}** account(s) from **{label}**.",
        ).set_footer(text="Generator")
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embeds=[embed], ephemeral=True)

    # /exportstock — send stock as downloadable .txt file
    @app_commands.command(name="exportstock",
                          description="[Owner] Export current stock for a category as a .txt file.")
    @app_commands.describe(category="Category to export")
    @app_commands.choices(category=[
        app_commands.Choice(name="🟢 Free",    value="free"),
        app_commands.Choice(name="🔵 Free+",   value="free+"),
        app_commands.Choice(name="⭐ Premium", value="premium"),
    ])
    async def exportstock(self, interaction: discord.Interaction, category: str):
        if not await utils.owner_only(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        # Read directly so stock is NOT consumed
        from database import _load_stock
        stock_data = _load_stock("stock")
        items = stock_data.get(category, [])

        if not items:
            return await interaction.followup.send(
                f"❌ No stock in **{CAT_LABELS.get(category, category)}**.", ephemeral=True
            )

        content = "\n".join(str(i) for i in items)
        buf = io.BytesIO(content.encode("utf-8"))
        buf.seek(0)
        file = discord.File(buf, filename=f"stock_{category.replace('+', 'plus')}.txt")

        embed = discord.Embed(
            color=0x5865F2,
            title="📤 Stock Export",
            description=f"Exported **{len(items)}** accounts from {CAT_LABELS.get(category, category)}.",
        ).set_footer(text="Generator • This file contains sensitive credentials")
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embeds=[embed], file=file, ephemeral=True)

    # /stockalert
    @app_commands.command(name="stockalert",
                          description="[Owner] Send an alert when stock falls to or below a threshold.")
    @app_commands.describe(
        category="Category to monitor",
        threshold="Alert fires when stock reaches this number (use 0 to disable)",
        channel="Channel to post the alert in",
        role="Role to ping in the alert (optional)",
    )
    @app_commands.choices(category=[
        app_commands.Choice(name="🟢 Free",    value="free"),
        app_commands.Choice(name="🔵 Free+",   value="free+"),
        app_commands.Choice(name="⭐ Premium", value="premium"),
    ])
    async def stockalert(self, interaction: discord.Interaction,
                         category: str, threshold: int,
                         channel: discord.TextChannel,
                         role: discord.Role = None):
        if not await utils.owner_only(interaction):
            return

        if threshold == 0:
            removed = db.clear_stock_alert(category)
            msg = (f"🔕 Stock alert for **{CAT_LABELS.get(category, category)}** disabled."
                   if removed else f"⚠️ No alert was set for **{category}**.")
            return await interaction.response.send_message(msg, ephemeral=True)

        db.set_stock_alert(
            category, threshold, str(channel.id),
            str(role.id) if role else None,
        )
        embed = discord.Embed(color=0x57F287, title="🔔 Stock Alert Set")
        embed.add_field(name="Category",  value=CAT_LABELS.get(category, category), inline=True)
        embed.add_field(name="Threshold", value=f"≤ {threshold} accounts",          inline=True)
        embed.add_field(name="Channel",   value=channel.mention,                    inline=True)
        embed.add_field(name="Ping",      value=role.mention if role else "None",   inline=True)
        embed.set_footer(text="Generator • Alert checks every 60 seconds")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embeds=[embed], ephemeral=True)

    # /fixstock — repair corrupted stock.json (stray newline/empty entries, malformed JSON)
    @app_commands.command(name="fixstock",
                          description="[Owner] Validate and repair stock.json if corrupted.")
    async def fixstock(self, interaction: discord.Interaction):
        if not await utils.owner_only(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        report = db.validate_stock("stock")

        if not report["was_corrupt"] and report["total_removed"] == 0:
            embed = discord.Embed(
                color=0x57F287,
                title="✅ Stock File Healthy",
                description="No corruption detected — `stock.json` is valid and clean.",
            )
        else:
            details = "\n".join(
                f"• **{CAT_LABELS.get(cat, cat)}** — removed {count} corrupted entr{'y' if count == 1 else 'ies'}"
                for cat, count in report["categories"].items()
            ) or "No per-category corrupted entries found."
            embed = discord.Embed(
                color=0xFEE75C,
                title="🛠️ Stock File Repaired",
                description=(
                    f"{'⚠️ The file had malformed JSON and was repaired.' if report['was_corrupt'] else 'Malformed JSON structure was not detected, but stray entries were cleaned.'}\n\n"
                    f"**Total corrupted entries removed:** {report['total_removed']}\n\n{details}"
                ),
            )

        counts = {c: db.stock_count(c) for c in utils.CATEGORIES}
        embed.add_field(
            name="📊 Current Stock",
            value="   •   ".join(f"{CAT_LABELS.get(c, c)} **{n}**" for c, n in counts.items()),
            inline=False,
        )
        embed.set_footer(text="Generator • /fixstock")
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embeds=[embed], ephemeral=True)

    # /setcooldown
    @app_commands.command(name="setcooldown",
                          description="[Owner] Set the generate cooldown per category.")
    @app_commands.describe(
        seconds="Cooldown in seconds (0 = no cooldown, max 86400)",
        category="Category to apply to (default: all)",
    )
    @app_commands.choices(category=[
        app_commands.Choice(name="All Categories", value="all"),
        app_commands.Choice(name="🟢 Free",        value="free"),
        app_commands.Choice(name="🔵 Free+",       value="free+"),
        app_commands.Choice(name="⭐ Premium",     value="premium"),
    ])
    async def setcooldown(self, interaction: discord.Interaction,
                          seconds: int, category: str = "all"):
        if not await utils.owner_only(interaction):
            return
        seconds = max(0, min(seconds, 86400))

        if category == "all":
            db.set_config("gen_cooldown", str(seconds))
            for c in utils.CATEGORIES:
                db.set_config(f"cooldown_{c.replace('+', 'plus')}", str(seconds))
        else:
            db.set_config(f"cooldown_{category.replace('+', 'plus')}", str(seconds))

        pretty = "No cooldown" if seconds == 0 else f"{seconds}s ({seconds / 60:.1f} min)"
        labels = {
            "all": "All Categories", "free": "🟢 Free",
            "free+": "🔵 Free+", "premium": "⭐ Premium",
        }
        embed = discord.Embed(color=0x57F287, title="⏱️ Generate Cooldown Set")
        embed.add_field(name="Category", value=labels.get(category, category), inline=True)
        embed.add_field(name="Cooldown", value=pretty,                         inline=True)
        embed.set_footer(text="Generator")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embeds=[embed], ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Stock(bot))
