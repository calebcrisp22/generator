"""
drops.py — Auto-drop system + drop management commands.
/drop setup /drop start /drop stop /drop status /drop now
/drop addstock (file upload) /drop clearstock /drop viewstock
/dropcooldown
"""

import asyncio
import logging
import random
import discord
from discord import app_commands
from discord.ext import commands

import database as db
import utils
from utils import fetch_text

log = logging.getLogger("generator.drops")


class Drops(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._drop_task: asyncio.Task | None = None

    # ── drop loop ──────────────────────────────────────────────────────────────

    def _start_drop_loop(self):
        if self._drop_task and not self._drop_task.done():
            self._drop_task.cancel()
        self._drop_task = asyncio.create_task(self._drop_loop())

    def _stop_drop_loop(self):
        if self._drop_task and not self._drop_task.done():
            self._drop_task.cancel()
        self._drop_task = None

    def is_drop_active(self) -> bool:
        return self._drop_task is not None and not self._drop_task.done()

    async def _drop_loop(self):
        while True:
            cooldown_secs = int(db.get_drop_config("cooldown", "300"))
            await asyncio.sleep(cooldown_secs)
            await self._do_drop()

    async def _do_drop(self):
        account = None
        cat     = None
        try:
            guild_id   = db.get_drop_config("guild_id")
            channel_id = db.get_drop_config("channel_id")
            if not guild_id or not channel_id:
                return

            guild   = self.bot.get_guild(int(guild_id))
            channel = guild.get_channel(int(channel_id)) if guild else None
            if not guild or not channel:
                return

            cats = db.drop_categories()
            if not cats:
                db.set_drop_config("active", "false")
                self._stop_drop_loop()
                try:
                    await channel.send("⚠️ Drop stopped — no more drop stock available.")
                except Exception:
                    pass
                return

            cat     = random.choice(cats)
            account = db.pop_drop_stock(cat)
            if not account:
                return

            embed = discord.Embed(
                color=0x5865F2,
                title="🎁 Account Drop!",
                description=f"A free **{cat}** account has been dropped!\n"
                            f"React with 🎁 to claim it — first come first served!",
            )
            embed.add_field(name="Category",       value=cat, inline=True)
            embed.add_field(name="Stock Remaining", value=str(db.drop_stock_count(cat)), inline=True)
            embed.set_footer(text="Generator • React to claim!")
            embed.timestamp = discord.utils.utcnow()

            msg = await channel.send(embeds=[embed])
            await msg.add_reaction("🎁")

            def check(reaction, user):
                return str(reaction.emoji) == "🎁" and not user.bot and reaction.message.id == msg.id

            try:
                reaction, user = await self.bot.wait_for("reaction_add", timeout=30.0, check=check)
            except asyncio.TimeoutError:
                # Nobody claimed — restore the account so it isn't lost
                db.restore_drop_stock(cat, account)
                account = None   # mark restored so finally block skips
                expired = discord.Embed(
                    color=0xED4245,
                    description="⏰ Drop expired — nobody claimed it in time.",
                )
                await channel.send(embeds=[expired])
                return

            dm_embed = discord.Embed(
                color=0x57F287,
                title=f"✅ Drop Claimed — {cat}",
                description="You were first! Here are your credentials:",
            )
            dm_embed.add_field(name="🔑 Login Credentials", value=f"```{account}```", inline=False)
            dm_embed.set_footer(text="Generator • Keep these safe!")
            dm_embed.timestamp = discord.utils.utcnow()

            try:
                await user.send(embeds=[dm_embed])
                account = None   # successfully delivered — do not restore
                claim = discord.Embed(
                    color=0x57F287,
                    description=f"✅ <@{user.id}> claimed the drop! Credentials sent to DMs.",
                )
                claim.timestamp = discord.utils.utcnow()
                await channel.send(embeds=[claim])
            except discord.Forbidden:
                # DM closed — restore account
                db.restore_drop_stock(cat, account)
                account = None
                await channel.send(
                    f"⚠️ <@{user.id}> couldn't receive DMs. Enable DMs to claim drops. "
                    f"The account was returned to the drop pool."
                )

        except Exception:
            log.exception("Drop loop error")
        finally:
            # Safety net: if we popped but never confirmed delivery or explicit restore, put it back
            if account is not None and cat is not None:
                db.restore_drop_stock(cat, account)

    # ── slash command group ────────────────────────────────────────────────────

    drop = app_commands.Group(name="drop", description="Manage the account drop system.")

    @drop.command(name="setup", description="[Owner] Configure which channel receives drops.")
    @app_commands.describe(
        channel="Channel to send drops to",
        cooldown="Seconds between drops (default 300)",
    )
    async def drop_setup(self, interaction: discord.Interaction,
                         channel: discord.TextChannel, cooldown: int = 300):
        if not await utils.owner_only(interaction):
            return
        db.set_drop_config("guild_id",   str(interaction.guild_id))
        db.set_drop_config("channel_id", str(channel.id))
        db.set_drop_config("cooldown",   str(cooldown))
        embed = discord.Embed(
            color=0x57F287, title="✅ Drop Configured",
            description=f"Channel: {channel.mention}\nCooldown: **{cooldown}s**",
        ).set_footer(text="Generator")
        await interaction.response.send_message(embeds=[embed], ephemeral=True)

    @drop.command(name="start", description="[Owner] Start the automatic drop loop.")
    async def drop_start(self, interaction: discord.Interaction):
        if not await utils.owner_only(interaction):
            return
        if not db.get_drop_config("channel_id"):
            return await interaction.response.send_message(
                "❌ Run `/drop setup` first to configure a channel.", ephemeral=True
            )
        db.set_drop_config("active", "true")
        self._start_drop_loop()
        embed = discord.Embed(
            color=0x57F287, title="▶️ Drop Started",
            description="Drops are now active!",
        ).set_footer(text="Generator")
        await interaction.response.send_message(embeds=[embed])

    @drop.command(name="stop", description="[Owner] Stop the automatic drop loop.")
    async def drop_stop(self, interaction: discord.Interaction):
        if not await utils.owner_only(interaction):
            return
        db.set_drop_config("active", "false")
        self._stop_drop_loop()
        embed = discord.Embed(
            color=0xED4245, title="⏹️ Drop Stopped",
            description="Drops have been paused.",
        ).set_footer(text="Generator")
        await interaction.response.send_message(embeds=[embed])

    @drop.command(name="status", description="Show drop system status.")
    async def drop_status(self, interaction: discord.Interaction):
        active     = self.is_drop_active()
        channel_id = db.get_drop_config("channel_id")
        cooldown   = db.get_drop_config("cooldown", "300")
        cats       = db.drop_categories()

        embed = discord.Embed(
            color=0x57F287 if active else 0xED4245,
            title="🎁 Drop Status",
        )
        embed.add_field(name="Active",   value="✅ Yes" if active else "❌ No", inline=True)
        embed.add_field(name="Channel",  value=f"<#{channel_id}>" if channel_id else "Not set", inline=True)
        embed.add_field(name="Cooldown", value=f"{cooldown}s", inline=True)
        if cats:
            embed.add_field(
                name="Drop Stock",
                value="\n".join(f"• {c}: **{db.drop_stock_count(c)}**" for c in cats),
                inline=False,
            )
        else:
            embed.add_field(name="Drop Stock", value="None", inline=False)
        embed.set_footer(text="Generator")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embeds=[embed])

    @drop.command(name="now", description="[Owner] Trigger an immediate drop right now.")
    async def drop_now(self, interaction: discord.Interaction):
        if not await utils.owner_only(interaction):
            return
        await interaction.response.send_message("🎁 Triggering a drop now...", ephemeral=True)
        await self._do_drop()

    # /drop addstock — file upload (.txt), mirrors adddropstock.js
    @drop.command(name="addstock", description="[Owner] Add stock to the drop pool from a .txt file.")
    @app_commands.describe(
        category="Drop category",
        file=".txt file — one account per line",
    )
    @app_commands.choices(category=[
        app_commands.Choice(name="🟢 Free",    value="free"),
        app_commands.Choice(name="🔵 Free+",   value="free+"),
        app_commands.Choice(name="⭐ Premium", value="premium"),
    ])
    async def drop_addstock(self, interaction: discord.Interaction,
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

        added = db.add_stock_bulk(category, lines, table="drop_stock")
        total = db.drop_stock_count(category)

        embed = discord.Embed(color=0x57F287, title="✅ Drop Stock Added")
        embed.add_field(name="Category",          value=category,   inline=True)
        embed.add_field(name="Added",             value=str(added), inline=True)
        embed.add_field(name="Total in Drop Pool", value=str(total), inline=True)
        embed.set_footer(text="Generator")
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embeds=[embed], ephemeral=True)

    @drop.command(name="clearstock", description="[Owner] Clear drop stock.")
    @app_commands.choices(category=[
        app_commands.Choice(name="🟢 Free",    value="free"),
        app_commands.Choice(name="🔵 Free+",   value="free+"),
        app_commands.Choice(name="⭐ Premium", value="premium"),
        app_commands.Choice(name="All",        value="all"),
    ])
    async def drop_clearstock(self, interaction: discord.Interaction, category: str):
        if not await utils.owner_only(interaction):
            return
        target = None if category == "all" else category
        label  = category if target else "ALL drop categories"

        view = utils.ConfirmView(interaction.user.id)
        await interaction.response.send_message(
            f"⚠️ This will permanently delete every item in **{label}** drop stock. Continue?",
            view=view, ephemeral=True,
        )
        await view.wait()
        if not view.confirmed:
            return

        removed = db.clear_drop_stock(target)
        embed = discord.Embed(
            color=0xED4245, title="🗑️ Drop Stock Cleared",
            description=f"Removed **{removed}** item(s) from **{label}**.",
        ).set_footer(text="Generator")
        await interaction.followup.send(embeds=[embed], ephemeral=True)

    @drop.command(name="viewstock", description="View drop pool stock counts.")
    async def drop_viewstock(self, interaction: discord.Interaction):
        cats = db.drop_categories()
        embed = discord.Embed(color=0x5865F2, title="🎁 Drop Stock")
        if not cats:
            embed.description = "No drop stock loaded."
        else:
            for cat in ["free", "free+", "premium"]:
                count = db.drop_stock_count(cat)
                embed.add_field(name=cat, value=f"{count} account(s)", inline=True)
        embed.set_footer(text="Generator")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embeds=[embed], ephemeral=True)

    # /dropcooldown — standalone command that also restarts the loop if active
    @app_commands.command(name="dropcooldown",
                          description="[Owner] Set the interval between drops in seconds.")
    @app_commands.describe(seconds="Seconds between each drop (e.g. 300 = 5 minutes)")
    async def dropcooldown(self, interaction: discord.Interaction, seconds: int):
        if not await utils.owner_only(interaction):
            return
        seconds = max(10, min(seconds, 86400))
        db.set_drop_config("cooldown", str(seconds))

        # Restart the loop immediately so the new interval takes effect
        if self.is_drop_active():
            self._start_drop_loop()

        embed = discord.Embed(color=0x57F287, title="⏱️ Drop Interval Updated")
        embed.add_field(name="New Interval", value=f"{seconds}s ({seconds / 60:.1f} min)", inline=True)
        embed.set_footer(text="Changes take effect immediately")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embeds=[embed], ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Drops(bot))
