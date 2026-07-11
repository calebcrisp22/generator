"""
admin.py — Owner-only admin commands.
/offline /setchannel /checkchannel /setlogchannel /setroles
/setstatus /setbanner /clearbanner /tokens /resetinvites
/resetplustime /viewjoins /createinvite /dropcooldown(moved to drops)
"""

import discord
from discord import app_commands
from discord.ext import commands

import database as db
import utils

MAX_DISCORD_UPLOAD_BYTES = 8 * 1024 * 1024  # Discord's default non-boosted upload cap

ACTIVITY_TYPES = {
    "playing":   discord.ActivityType.playing,
    "watching":  discord.ActivityType.watching,
    "listening": discord.ActivityType.listening,
    "competing": discord.ActivityType.competing,
}


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # /offline — toggle generator offline/thinking mode
    @app_commands.command(name="offline",
                          description="[Owner] Take the generator offline for maintenance.")
    @app_commands.describe(mode="Turn offline mode on or off")
    @app_commands.choices(mode=[
        app_commands.Choice(name="On — /generate shows an offline notice", value="on"),
        app_commands.Choice(name="Off — generator works normally",         value="off"),
    ])
    async def offline(self, interaction: discord.Interaction, mode: str):
        if not await utils.owner_only(interaction):
            return
        on = mode == "on"
        db.set_config("gen_offline", "true" if on else "false")
        embed = discord.Embed(
            color=0xED4245 if on else 0x57F287,
            title="🔌 Offline Mode Enabled" if on else "✅ Offline Mode Disabled",
            description=(
                "Every `/generate` will now reply with a clean **\"Generator Offline\"** notice "
                "instead of delivering an account — handy for maintenance windows."
                if on else
                "The generator is back to normal — `/generate` will deliver accounts again."
            ),
        ).set_footer(text="Generator")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embeds=[embed], ephemeral=True)

    # /backup — zip up data/ and send it, plus prune old rolling backups
    @app_commands.command(name="backup",
                          description="[Owner] Create and download a backup of all bot data.")
    async def backup(self, interaction: discord.Interaction):
        if not await utils.owner_only(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        try:
            archive_path = db.create_backup()
        except Exception as exc:
            return await interaction.followup.send(f"❌ Backup failed: {exc}", ephemeral=True)

        size = archive_path.stat().st_size
        embed = discord.Embed(
            color=0x57F287, title="💾 Backup Created",
            description=f"Snapshot of `data/` saved as `{archive_path.name}` ({size / 1024:.1f} KB).",
        ).set_footer(text="Generator • Contains account credentials — keep this safe")
        embed.timestamp = discord.utils.utcnow()

        if size > MAX_DISCORD_UPLOAD_BYTES:
            embed.add_field(
                name="⚠️ Too Large to Attach",
                value=(
                    f"This backup is over Discord's upload limit, so it wasn't attached here. "
                    f"It's still saved on disk at `backups/{archive_path.name}` — use the Files "
                    f"pane or shell to download it."
                ),
                inline=False,
            )
            return await interaction.followup.send(embeds=[embed], ephemeral=True)

        file = discord.File(str(archive_path), filename=archive_path.name)
        await interaction.followup.send(embeds=[embed], file=file, ephemeral=True)

    # /backups — list recent rolling backups without creating a new one
    @app_commands.command(name="backups", description="[Owner] List recent data backups.")
    async def backups(self, interaction: discord.Interaction):
        if not await utils.owner_only(interaction):
            return
        entries = db.list_backups()
        if not entries:
            return await interaction.response.send_message(
                "📭 No backups yet — run `/backup` to create one.", ephemeral=True
            )
        lines = [
            f"`{e['name']}` — {e['size_bytes'] / 1024:.1f} KB • <t:{e['created_at']}:R>"
            for e in entries[:10]
        ]
        embed = discord.Embed(
            color=0x5865F2, title="💾 Recent Backups",
            description="\n".join(lines),
        ).set_footer(text=f"Generator • Keeping the {db.MAX_BACKUPS} most recent")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embeds=[embed], ephemeral=True)

    # /setgendelay — configure the simulated "processing" delay in /generate
    @app_commands.command(name="setgendelay",
                          description="[Owner] Set the simulated processing delay for /generate (seconds).")
    @app_commands.describe(seconds="Delay in seconds before delivery (0–30, default 10)")
    async def setgendelay(self, interaction: discord.Interaction, seconds: int):
        if not await utils.owner_only(interaction):
            return
        seconds = max(0, min(seconds, 30))
        db.set_config("gen_delay_seconds", seconds)
        embed = discord.Embed(
            color=0x57F287, title="⏱️ Generate Delay Updated",
            description=f"`/generate` will now show the \"Adding account to API...\" status for **{seconds}s** "
                        f"before delivering." if seconds > 0 else
                        "`/generate` will now deliver immediately with no simulated delay.",
        ).set_footer(text="Generator")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embeds=[embed], ephemeral=True)

    # /setchannel — restrict /generate to one channel
    @app_commands.command(name="setchannel",
                          description="[Owner] Set the channel where /generate is allowed.")
    @app_commands.describe(channel="Channel to restrict to (leave blank = all channels)")
    async def setchannel(self, interaction: discord.Interaction,
                         channel: discord.TextChannel = None):
        if not await utils.owner_only(interaction):
            return
        db.set_config("gen_channel", str(channel.id) if channel else "")
        embed = discord.Embed(
            color=0x57F287, title="✅ Gen Channel Set",
            description=f"Generate restricted to {channel.mention}." if channel
                        else "Generate allowed in all channels.",
        ).set_footer(text="Generator")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embeds=[embed], ephemeral=True)

    # /checkchannel — show current channel settings
    @app_commands.command(name="checkchannel",
                          description="[Owner] Check the current generate/log channel settings.")
    async def checkchannel(self, interaction: discord.Interaction):
        if not await utils.owner_only(interaction):
            return
        gen_ch  = db.get_config("gen_channel")
        log_ch  = db.get_config("log_channel")
        embed   = discord.Embed(color=0x5865F2, title="📋 Channel Settings")
        embed.add_field(
            name="Gen Channel",
            value=f"<#{gen_ch}>" if gen_ch else "All channels",
            inline=True,
        )
        embed.add_field(
            name="Log Channel",
            value=f"<#{log_ch}>" if log_ch else "Disabled",
            inline=True,
        )
        role_lines = []
        for cat in utils.CATEGORIES:
            rid = utils.get_category_role_id(cat)
            role_lines.append(f"{cat}: " + (f"<@&{rid}>" if rid else "⚠️ by role name (run `/setroles`)"))
        embed.add_field(name="Generate Access Roles", value="\n".join(role_lines), inline=False)
        embed.set_footer(text="Generator")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embeds=[embed], ephemeral=True)

    # /setlogchannel — set restock announcement channel
    @app_commands.command(name="setlogchannel",
                          description="[Owner] Set the channel for restock announcements.")
    @app_commands.describe(channel="Channel for restock announcements (leave blank to disable)")
    async def setlogchannel(self, interaction: discord.Interaction,
                            channel: discord.TextChannel = None):
        if not await utils.owner_only(interaction):
            return
        db.set_config("log_channel", str(channel.id) if channel else "")
        embed = discord.Embed(
            color=0x57F287, title="✅ Restock Channel Set",
            description=(
                f"Restock announcements will be posted in {channel.mention} whenever you add stock."
                if channel else "Restock announcements are now disabled."
            ),
        ).set_footer(text="Generator")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embeds=[embed], ephemeral=True)

    # /setwelcomechannel — set the channel for new-member welcome cards
    @app_commands.command(name="setwelcomechannel",
                          description="[Owner] Set the channel for new-member welcome messages.")
    @app_commands.describe(channel="Channel for welcome cards (leave blank to disable)")
    async def setwelcomechannel(self, interaction: discord.Interaction,
                                channel: discord.TextChannel = None):
        if not await utils.owner_only(interaction):
            return
        db.set_config("welcome_channel", str(channel.id) if channel else "")
        embed = discord.Embed(
            color=0x57F287, title="✅ Welcome Channel Set",
            description=(
                f"New members will get a welcome card in {channel.mention}."
                if channel else "Welcome cards are now disabled."
            ),
        ).set_footer(text="Generator")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embeds=[embed], ephemeral=True)

    # /setroles — assign Discord roles to generate categories
    @app_commands.command(name="setroles",
                          description="[Owner] Set which role grants access to a generate category.")
    @app_commands.describe(
        category="Category to configure",
        role="Role required to generate this category",
    )
    @app_commands.choices(category=[
        app_commands.Choice(name="🟢 Free",    value="free"),
        app_commands.Choice(name="🔵 Free+",   value="free+"),
        app_commands.Choice(name="⭐ Premium", value="premium"),
    ])
    async def setroles(self, interaction: discord.Interaction,
                       category: str, role: discord.Role):
        if not await utils.owner_only(interaction):
            return
        key = f"role_{category.replace('+', 'plus')}"
        db.set_config(key, str(role.id))

        free_role    = db.get_config("role_free")
        freeplus_role = db.get_config("role_freeplus")
        premium_role = db.get_config("role_premium")

        embed = discord.Embed(
            color=0x57F287, title="✅ Role Set",
            description=f"**{category}** is now gated to {role.mention}.",
        )
        embed.add_field(name="🟢 Free",    value=f"<@&{free_role}>"    if free_role    else "⚠️ By role name", inline=True)
        embed.add_field(name="🔵 Free+",   value=f"<@&{freeplus_role}>" if freeplus_role else "⚠️ By role name", inline=True)
        embed.add_field(name="⭐ Premium", value=f"<@&{premium_role}>"  if premium_role  else "⚠️ By role name", inline=True)
        unconfigured = [c for c, rid in (("free", free_role), ("free+", freeplus_role), ("premium", premium_role)) if not rid]
        if unconfigured:
            embed.add_field(
                name="⚠️ Heads up",
                value=(
                    f"{', '.join(unconfigured)} still fall back to matching **any role literally named** "
                    f"that tier. If this server has an unrelated role with that name, its members will "
                    f"unintentionally get generate access. Run `/setroles` for those categories too."
                ),
                inline=False,
            )
        embed.set_footer(text="Generator")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embeds=[embed], ephemeral=True)

    # /setstatus
    @app_commands.command(name="setstatus", description="[Owner] Set the bot's presence/status.")
    @app_commands.describe(activity_type="Activity type",
                           text="Status text (ignored if activity type is 'Live Stock Count')")
    @app_commands.choices(activity_type=[
        app_commands.Choice(name="Playing",   value="playing"),
        app_commands.Choice(name="Watching",  value="watching"),
        app_commands.Choice(name="Listening", value="listening"),
        app_commands.Choice(name="Competing", value="competing"),
        app_commands.Choice(name="🔴 Live Stock Count", value="auto"),
    ])
    async def setstatus(self, interaction: discord.Interaction,
                        activity_type: str, text: str = ""):
        if not await utils.owner_only(interaction):
            return

        if activity_type == "auto":
            db.set_config("status_type", "auto")
            from main import apply_presence
            await apply_presence()
            embed = discord.Embed(
                color=0x57F287, title="✅ Status Updated",
                description="Bot presence now shows a **live total stock count**, refreshed every 60s.",
            ).set_footer(text="Generator")
            return await interaction.response.send_message(embeds=[embed], ephemeral=True)

        if not text:
            embed = discord.Embed(color=0xED4245, title="❌ Missing Text",
                                  description="`text` is required for this activity type.")
            return await interaction.response.send_message(embeds=[embed], ephemeral=True)

        db.set_config("status_text", text)
        db.set_config("status_type", activity_type)
        act_type = ACTIVITY_TYPES.get(activity_type, discord.ActivityType.playing)
        await self.bot.change_presence(
            activity=discord.Activity(type=act_type, name=text),
            status=discord.Status.online,
        )
        embed = discord.Embed(
            color=0x57F287, title="✅ Status Updated",
            description=f"**{activity_type.capitalize()}** {text}",
        ).set_footer(text="Generator")
        await interaction.response.send_message(embeds=[embed], ephemeral=True)

    # /setimage — mirrors setimage.js exactly:
    #   attachment only  → download & store locally (never expires)
    #   url only         → store URL directly (warns about expiry)
    #   neither          → clear the banner
    @app_commands.command(name="setimage",
                          description="[Owner] Set the banner image shown in generate embeds.")
    @app_commands.describe(
        image="Upload an image file (recommended — never expires)",
        url="OR paste a direct image URL (jpg/png/gif)",
    )
    async def setimage(self, interaction: discord.Interaction,
                       image: discord.Attachment = None,
                       url: str = None):
        if not await utils.owner_only(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        # 1) Uploaded file — download & store locally
        if image:
            ct = image.content_type or ""
            if not ct.startswith("image/"):
                embed = discord.Embed(
                    color=0xED4245, title="❌ Not an Image",
                    description="That file is not an image. Please upload a `.png`, `.jpg`, or `.gif`.",
                ).set_footer(text="Generator")
                return await interaction.followup.send(embeds=[embed], ephemeral=True)
            try:
                data = await image.read()
            except Exception as exc:
                return await interaction.followup.send(
                    f"❌ Could not download that image: {exc}", ephemeral=True
                )
            ext = (ct.split("/")[1] if "/" in ct else None) or \
                  (image.filename.rsplit(".", 1)[-1] if "." in image.filename else "png")
            filename = db.save_banner(data, ext)
            db.set_config("gen_image", f"local:{filename}")
            file = discord.File(
                db.get_banner_file()["path"],
                filename=filename,
            )
            embed = discord.Embed(
                color=0x57F287, title="🖼️ Banner Image Set",
                description=(
                    "Saved! This image will appear in every generate embed (channel + DM) "
                    "and will **not** expire."
                ),
            ).set_image(url=f"attachment://{filename}").set_footer(text="Generator")
            embed.timestamp = discord.utils.utcnow()
            return await interaction.followup.send(embeds=[embed], files=[file], ephemeral=True)

        # 2) URL provided — store directly
        if url and url.strip():
            url = url.strip()
            db.clear_banner()
            db.set_config("gen_image", url)
            embed = discord.Embed(
                color=0x57F287, title="🖼️ Banner Image Set",
                description=(
                    "This image will now appear in both the channel embed and DM when an "
                    "account is generated.\n\n"
                    "⚠️ Heads up: links copied from Discord uploads **expire after ~24h**. "
                    "For a permanent banner, use the **image** upload option instead."
                ),
            ).set_image(url=url).set_footer(text="Generator")
            embed.timestamp = discord.utils.utcnow()
            return await interaction.followup.send(embeds=[embed], ephemeral=True)

        # 3) Neither provided — clear the banner
        db.clear_banner()
        db.set_config("gen_image", "")
        embed = discord.Embed(
            color=0xED4245, title="🖼️ Banner Image Removed",
            description="Generate embeds will no longer show a banner image.",
        ).set_footer(text="Generator")
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embeds=[embed], ephemeral=True)

    # Keep /setbanner as a convenience alias that just calls /setimage logic
    @app_commands.command(name="setbanner",
                          description="[Owner] Upload a banner image (alias of /setimage).")
    @app_commands.describe(attachment="Image file (PNG/JPG/GIF/WEBP)")
    async def setbanner(self, interaction: discord.Interaction,
                        attachment: discord.Attachment):
        if not await utils.owner_only(interaction):
            return
        if not attachment.content_type or not attachment.content_type.startswith("image/"):
            return await interaction.response.send_message(
                "❌ Must be an image file.", ephemeral=True
            )
        await interaction.response.defer(ephemeral=True)
        data = await attachment.read()
        ext  = attachment.filename.rsplit(".", 1)[-1] if "." in attachment.filename else "png"
        filename = db.save_banner(data, ext)
        db.set_config("gen_image", f"local:{filename}")
        embed = discord.Embed(
            color=0x57F287, title="✅ Banner Set",
            description="The banner image has been updated.",
        ).set_footer(text="Generator")
        await interaction.followup.send(embeds=[embed], ephemeral=True)

    @app_commands.command(name="clearbanner", description="[Owner] Remove the banner image.")
    async def clearbanner(self, interaction: discord.Interaction):
        if not await utils.owner_only(interaction):
            return
        db.clear_banner()
        db.set_config("gen_image", "")
        embed = discord.Embed(
            color=0xED4245, title="🗑️ Banner Cleared",
            description="Banner image removed.",
        ).set_footer(text="Generator")
        await interaction.response.send_message(embeds=[embed], ephemeral=True)

    # /tokens group
    tokens_group = app_commands.Group(name="tokens", description="Manage user token balances.")

    @tokens_group.command(name="add", description="[Owner] Add tokens to a user.")
    @app_commands.describe(user="Target user", amount="Amount to add")
    async def tokens_add(self, interaction: discord.Interaction,
                         user: discord.Member, amount: int):
        if not await utils.owner_only(interaction):
            return
        db.increment_user_field(str(user.id), "tokens", amount)
        u = db.get_user(str(user.id))
        embed = discord.Embed(
            color=0x57F287, title="✅ Tokens Added",
            description=f"Added **{amount}** tokens to {user.mention}.\nNew balance: **{u['tokens']}**",
        ).set_footer(text="Generator")
        await interaction.response.send_message(embeds=[embed])

    @tokens_group.command(name="remove", description="[Owner] Remove tokens from a user.")
    @app_commands.describe(user="Target user", amount="Amount to remove")
    async def tokens_remove(self, interaction: discord.Interaction,
                            user: discord.Member, amount: int):
        if not await utils.owner_only(interaction):
            return
        u       = db.get_user(str(user.id))
        new_bal = max(0, u.get("tokens", 0) - amount)
        db.update_user(str(user.id), {"tokens": new_bal})
        embed = discord.Embed(
            color=0xED4245, title="✅ Tokens Removed",
            description=f"Removed **{amount}** tokens from {user.mention}.\nNew balance: **{new_bal}**",
        ).set_footer(text="Generator")
        await interaction.response.send_message(embeds=[embed])

    @tokens_group.command(name="balance", description="Check your token balance.")
    @app_commands.describe(user="User to check (defaults to yourself)")
    async def tokens_balance(self, interaction: discord.Interaction,
                             user: discord.Member = None):
        target = user or interaction.user
        u      = db.get_user(str(target.id))
        embed  = discord.Embed(
            color=0x5865F2,
            title=f"💰 Tokens — {target.display_name}",
            description=f"Balance: **{u.get('tokens', 0)}** tokens",
        ).set_footer(text="Generator")
        await interaction.response.send_message(embeds=[embed], ephemeral=True)

    # /clearcooldown — reset a user's generate cooldown
    @app_commands.command(name="clearcooldown",
                          description="[Owner] Reset a user's generate cooldown.")
    @app_commands.describe(
        user="User whose cooldown to clear",
        category="Category to clear (default: all)",
    )
    @app_commands.choices(category=[
        app_commands.Choice(name="All Categories", value="all"),
        app_commands.Choice(name="🟢 Free",        value="free"),
        app_commands.Choice(name="🔵 Free+",       value="free+"),
        app_commands.Choice(name="⭐ Premium",     value="premium"),
    ])
    async def clearcooldown(self, interaction: discord.Interaction,
                            user: discord.Member, category: str = "all"):
        if not await utils.owner_only(interaction):
            return
        if category == "all":
            db.update_user(str(user.id), {
                "last_gen": 0,
                "last_gen_free": 0,
                "last_gen_freeplus": 0,
                "last_gen_premium": 0,
            })
            label = "all categories"
        else:
            db.update_user(str(user.id), {
                f"last_gen_{category.replace('+', 'plus')}": 0,
            })
            label = category
        embed = discord.Embed(
            color=0x57F287, title="✅ Cooldown Cleared",
            description=f"Cleared **{label}** cooldown for {user.mention}.",
        ).set_footer(text="Generator")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embeds=[embed], ephemeral=True)

    # /setcolor — custom embed color per generate category
    @app_commands.command(name="setcolor",
                          description="[Owner] Set the embed color for a generate category.")
    @app_commands.describe(
        category="Category to update",
        hex_color="Hex color code without # (e.g. FF5733)",
    )
    @app_commands.choices(category=[
        app_commands.Choice(name="🟢 Free",    value="free"),
        app_commands.Choice(name="🔵 Free+",   value="free+"),
        app_commands.Choice(name="⭐ Premium", value="premium"),
    ])
    async def setcolor(self, interaction: discord.Interaction,
                       category: str, hex_color: str):
        if not await utils.owner_only(interaction):
            return
        cleaned = hex_color.lstrip("#").strip()
        try:
            color_int = int(cleaned, 16)
            if not (0 <= color_int <= 0xFFFFFF):
                raise ValueError
        except ValueError:
            return await interaction.response.send_message(
                "❌ Invalid hex color. Use 6 hex digits, e.g. `FF5733`.", ephemeral=True
            )
        db.set_config(f"color_{category.replace('+', 'plus')}", str(color_int))
        embed = discord.Embed(
            color=color_int,
            title="🎨 Color Updated",
            description=f"**{category}** generate embeds will now use this color.",
        )
        embed.add_field(name="Category", value=category,          inline=True)
        embed.add_field(name="Hex",      value=f"#{cleaned.upper()}", inline=True)
        embed.set_footer(text="Generator")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embeds=[embed], ephemeral=True)

    # /resetinvites
    @app_commands.command(name="resetinvites",
                          description="[Owner] Reset a user's invite count.")
    @app_commands.describe(user="User whose invite count to reset")
    async def resetinvites(self, interaction: discord.Interaction, user: discord.Member):
        if not await utils.owner_only(interaction):
            return
        db.reset_inviter_joins(str(user.id))
        embed = discord.Embed(
            color=0x57F287, title="✅ Invites Reset",
            description=f"{user.mention}'s invite count has been reset to 0.",
        ).set_footer(text="Generator")
        await interaction.response.send_message(embeds=[embed], ephemeral=True)

    # /resetplustime
    @app_commands.command(name="resetplustime",
                          description="[Owner] Reset plus time for a user.")
    @app_commands.describe(user="Target user")
    async def resetplustime(self, interaction: discord.Interaction, user: discord.Member):
        if not await utils.owner_only(interaction):
            return
        db.update_user(str(user.id), {"plus_time": 0})
        embed = discord.Embed(
            color=0xED4245, title="🔄 Plus Time Reset",
            description=f"Plus time reset for {user.mention}.",
        ).set_footer(text="Generator")
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.send_message(embeds=[embed], ephemeral=True)

    # /viewjoins — show users who joined via a specific inviter
    @app_commands.command(name="viewjoins",
                          description="[Owner] View users who joined via a specific inviter.")
    @app_commands.describe(user="Inviter to check")
    async def viewjoins(self, interaction: discord.Interaction, user: discord.User):
        if not await utils.owner_only(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        joins = db.get_joins_by_inviter(str(user.id))[:20]
        if not joins:
            return await interaction.followup.send(
                f"📭 <@{user.id}> has no tracked joins.", ephemeral=True
            )

        lines = [
            f"<@{j['user_id']}> • `{j['code']}` • <t:{j['joined_at']}:R>"
            for j in joins
        ]
        embed = discord.Embed(
            color=0x5865F2,
            title=f"📨 Joins via @{user.name}",
            description="\n".join(lines)[:4096],
        )
        embed.set_footer(text=f"{len(joins)} shown • Generator")
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embeds=[embed], ephemeral=True)

    # /createinvite — create a tracked server invite
    @app_commands.command(name="createinvite", description="[Owner] Create a tracked server invite.")
    @app_commands.describe(
        max_uses="Max uses (0 = unlimited)",
        max_age="Expiry in seconds (0 = never)",
    )
    @app_commands.guild_only()
    async def createinvite(self, interaction: discord.Interaction,
                           max_uses: int = 0, max_age: int = 0):
        if not await utils.owner_only(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            invite = await interaction.channel.create_invite(
                max_uses=max_uses,
                max_age=max_age,
                reason=f"Created by {interaction.user}",
            )
            db.save_invite(invite.code, str(interaction.user.id), max_uses)

            embed = discord.Embed(color=0x57F287, title="✅ Invite Created")
            embed.add_field(name="Link",      value=f"https://discord.gg/{invite.code}", inline=False)
            embed.add_field(name="Max Uses",  value="Unlimited" if max_uses == 0 else str(max_uses), inline=True)
            embed.add_field(name="Expires",   value="Never" if max_age == 0 else f"in {max_age}s", inline=True)
            embed.timestamp = discord.utils.utcnow()
            await interaction.followup.send(embeds=[embed], ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(f"❌ Could not create invite: {exc}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
