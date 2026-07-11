"""
generate.py — /generate command.
Faithful Python port of generate.js including:
  - parseAccount pipe-format parser
  - offline mode (gen_offline)
  - gen_channel restriction
  - per-category cooldown (last_gen_<catkey>)
  - DM-first flow with cascade status messages
  - stock restore on DM delivery failure
  - separate channel embed (minimal) + DM embed (full)
  - Copy Email:Pass / Skin Link / How to Link / Upgrade buttons
"""

import asyncio
import time
import discord
from discord import app_commands
from discord.ext import commands

import database as db
import utils

_DEFAULT_COLORS = {"free": 0x57F287, "free+": 0x5865F2, "premium": 0xFEE75C}
CATEGORY_LABELS = {"free": "🟢 Free", "free+": "🔵 Free+", "premium": "⭐ Premium"}


def _category_color(category: str) -> int:
    """Return custom color from config, falling back to defaults."""
    key = f"color_{category.replace('+', 'plus')}"
    stored = db.get_config(key)
    if stored:
        try:
            return int(stored)
        except (ValueError, TypeError):
            pass
    return _DEFAULT_COLORS.get(category, 0x5865F2)


def parse_account(raw) -> dict:
    """
    Parse a pipe-delimited account string.
    Format: credentials|URL_or_field|Credits: 119 / Renown: 5972|...
    Returns: {credentials, skin_link, username, detail_lines, currency_fields}
    """
    if not isinstance(raw, str):
        if isinstance(raw, dict):
            raw = raw.get("credentials") or raw.get("account") or raw.get("data") \
                  or raw.get("value") or raw.get("text") or str(raw)
        else:
            raw = str(raw or "")

    parts = [p.strip() for p in raw.split("|") if p.strip()]
    credentials = parts[0] if parts else raw.strip()
    skin_link = None
    username = None
    detail_lines = []
    currency_fields = []

    for part in parts[1:]:
        # Bare URL → skin link
        if part.startswith("http://") or part.startswith("https://"):
            skin_link = part
            continue

        # Currency-style: "Credits: 119 / Renown: 5972"
        if " / " in part:
            subs = [s.strip() for s in part.split(" / ") if s.strip()]
            if len(subs) > 1 and all(":" in s or "➡" in s for s in subs):
                for sub in subs:
                    ai = sub.find("➡")
                    ci = sub.find(":")
                    idx = ai if ai != -1 else ci
                    name = sub[:idx].strip()
                    val = sub[idx + 1:].strip()
                    if val.startswith("http://") or val.startswith("https://"):
                        skin_link = val
                        continue
                    currency_fields.append({"name": name, "value": val or "\u200b", "inline": True})
                continue

        # label➡value or label:value
        ai = part.find("➡")
        ci = part.find(":")
        if ai != -1:
            label, value = part[:ai].strip(), part[ai + 1:].strip()
        elif ci != -1:
            label, value = part[:ci].strip(), part[ci + 1:].strip()
        else:
            detail_lines.append(part)
            continue

        if value.startswith("http://") or value.startswith("https://"):
            skin_link = value
            continue
        if label.lower() == "username" and not username:
            username = value
        detail_lines.append(f"**{label}** ➡️ {value}")

    return {
        "credentials": credentials,
        "skin_link": skin_link,
        "username": username,
        "detail_lines": detail_lines,
        "currency_fields": currency_fields,
    }


class Generate(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="generate", description="Generate an account from stock.")
    @app_commands.describe(category="Account tier to generate")
    @app_commands.choices(category=[
        app_commands.Choice(name="🟢 Free",    value="free"),
        app_commands.Choice(name="🔵 Free+",   value="free+"),
        app_commands.Choice(name="⭐ Premium", value="premium"),
    ])
    @app_commands.guild_only()
    async def generate(self, interaction: discord.Interaction, category: str):

        # ── Offline mode ───────────────────────────────────────────────────────
        if db.get_config("gen_offline", "false") == "true":
            embed = discord.Embed(
                color=0xFEE75C, title="🔌 Generator Offline",
                description="The generator is temporarily offline for maintenance. Please check back soon!",
            ).set_footer(text="Generator")
            return await interaction.response.send_message(embeds=[embed], ephemeral=True)

        # ── Channel restriction ────────────────────────────────────────────────
        gen_channel_id = db.get_config("gen_channel")
        if gen_channel_id and str(interaction.channel_id) != str(gen_channel_id):
            return await interaction.response.send_message(
                f"❌ Head to <#{gen_channel_id}> to generate accounts.", ephemeral=True
            )

        # ── Blacklist check ────────────────────────────────────────────────────
        if db.is_blacklisted(str(interaction.user.id)):
            embed = discord.Embed(
                color=0xED4245, title="❌ Access Denied",
                description="You are not permitted to use the generator.",
            ).set_footer(text="Generator")
            return await interaction.response.send_message(embeds=[embed], ephemeral=True)

        # ── Access check ───────────────────────────────────────────────────────
        member = interaction.user if isinstance(interaction.user, discord.Member) \
            else await interaction.guild.fetch_member(interaction.user.id)

        if not utils.has_generate_access(member, category):
            role_id = utils.get_category_role_id(category)
            role_ref = f"<@&{role_id}>" if role_id else f"**{category}**"
            embed = discord.Embed(
                color=0xED4245, title="❌ No Access",
                description=f"You need the {role_ref} role to generate **{category}** accounts.\n\n"
                            f"Upgrade your membership to unlock this tier.",
            )
            return await interaction.response.send_message(embeds=[embed], ephemeral=True)

        # ── Cooldown check ─────────────────────────────────────────────────────
        cat_key = category.replace("+", "plus")
        try:
            cooldown = int(db.get_config(f"cooldown_{cat_key}") or db.get_config("gen_cooldown") or 0)
        except (ValueError, TypeError):
            cooldown = 0
        now = int(time.time())
        user = db.get_user(str(interaction.user.id))
        last_gen = user.get(f"last_gen_{cat_key}", 0)
        remaining = (last_gen + cooldown) - now

        if cooldown > 0 and remaining > 0 and not utils.is_owner(str(interaction.user.id)):
            embed = discord.Embed(
                color=0xED4245, title="⏳ Cooldown Active",
                description=f"You must wait **{remaining}s** before generating again.",
            )
            return await interaction.response.send_message(embeds=[embed], ephemeral=True)

        # ── Quick stock check before burning a DM slot ─────────────────────────
        await interaction.response.defer()

        if db.stock_count(category) <= 0:
            embed = discord.Embed(
                color=0xED4245, title="❌ Out of Stock",
                description=f"**{CATEGORY_LABELS[category]}** accounts are currently out of stock.\nCheck back soon!",
            )
            return await interaction.followup.send(embeds=[embed])

        # ── Open DM first — if closed, bail before popping stock ───────────────
        try:
            status_msg = await interaction.user.send("⏳ **Processing Your Account** • Fetching details...")
        except discord.Forbidden:
            embed = discord.Embed(
                color=0xFEE75C, title="⚠️ Could Not Send DM",
                description=f"<@{interaction.user.id}> your DMs are closed. Enable "
                            f"**\"Allow Direct Messages from Server Members\"** in Privacy Settings and try again.",
            )
            return await interaction.followup.send(embeds=[embed])

        # ── Pop stock ──────────────────────────────────────────────────────────
        raw = db.pop_stock(category)
        if not raw:
            await status_msg.edit(
                content=f"❌ **{CATEGORY_LABELS[category]}** just sold out — someone grabbed the last one!"
            )
            embed = discord.Embed(
                color=0xED4245, title="❌ Out of Stock",
                description=f"**{CATEGORY_LABELS[category]}** accounts are currently out of stock.\nCheck back soon!",
            )
            return await interaction.followup.send(embeds=[embed])

        # ── Record cooldown ────────────────────────────────────────────────────
        db.update_user(str(interaction.user.id), {f"last_gen_{cat_key}": now, "last_gen": now})
        left = db.stock_count(category)

        # ── Parse account ──────────────────────────────────────────────────────
        parsed = parse_account(raw)
        credentials = parsed["credentials"]
        skin_link    = parsed["skin_link"]
        username     = parsed["username"]
        detail_lines = parsed["detail_lines"]
        currency_fields = parsed["currency_fields"]

        # ── Banner ─────────────────────────────────────────────────────────────
        gen_image   = db.get_config("gen_image", "")
        banner_file = db.get_banner_file() if str(gen_image).startswith("local:") else None
        if banner_file:
            banner_url = f"attachment://{banner_file['name']}"
        elif gen_image and gen_image.startswith("http"):
            banner_url = gen_image
        else:
            banner_url = None

        color         = _category_color(category)
        guild_icon    = interaction.guild.icon.url if interaction.guild.icon else None
        stock_cap     = max(20, left)
        stock_bar     = utils.progress_bar(left, stock_cap)

        # ── Channel embed (card-style, no credentials) ─────────────────────────
        channel_embed = discord.Embed(
            color=color,
            title=f"✨ {CATEGORY_LABELS[category]} Account Claimed ✨",
            description=f"<@{interaction.user.id}> just generated an account! Check your DMs 📬",
        )
        channel_embed.set_author(name=interaction.guild.name, icon_url=guild_icon)
        channel_embed.set_thumbnail(url=interaction.user.display_avatar.url)
        channel_embed.add_field(name="📦 Stock Remaining", value=f"`{stock_bar}` {left} left", inline=False)
        channel_embed.set_footer(text="Generator • Use /generate to claim your own")
        channel_embed.timestamp = discord.utils.utcnow()
        if banner_url:
            channel_embed.set_image(url=banner_url)

        # ── DM embed (full card) ────────────────────────────────────────────────
        dm_description = "\n".join(detail_lines) if detail_lines else "\u200b"
        title = f"🎁✨ Account Delivered — {username or CATEGORY_LABELS[category]} ✨🎁"

        dm_embed = discord.Embed(color=color, title=title, description=dm_description)
        dm_embed.set_author(name=f"{interaction.guild.name} ✨ {CATEGORY_LABELS[category].upper()}", icon_url=guild_icon)
        dm_embed.set_thumbnail(url=guild_icon)
        dm_embed.set_footer(text="Generator • Do NOT share your credentials with anyone")
        dm_embed.timestamp = discord.utils.utcnow()

        for field in currency_fields[:3]:
            dm_embed.add_field(name=field["name"], value=field["value"], inline=field["inline"])

        dm_embed.add_field(name="🔑 Login Credentials", value=f"```{credentials}```", inline=False)
        dm_embed.add_field(name="", value="━━━━━━━━━━━━━━━━━━", inline=False)
        if skin_link:
            dm_embed.add_field(name="🎨 Skin Link", value=skin_link, inline=False)
        dm_embed.add_field(name="📦 Tier Stock Remaining", value=f"`{stock_bar}` {left} left", inline=False)
        if banner_url:
            dm_embed.set_image(url=banner_url)

        # ── Buttons ────────────────────────────────────────────────────────────
        buttons: list[discord.ui.Button] = [
            discord.ui.Button(
                label="Copy Email:Pass", style=discord.ButtonStyle.primary,
                custom_id="copy_creds", emoji="📋",
            ),
        ]
        if skin_link:
            buttons.append(discord.ui.Button(
                label="Copy Skin Link", style=discord.ButtonStyle.link,
                url=skin_link, emoji="🎨",
            ))
        buttons.append(discord.ui.Button(
            label="How to Link", style=discord.ButtonStyle.secondary,
            custom_id="how_to_link", emoji="❓",
        ))
        buttons.append(discord.ui.Button(
            label="Upgrade Premium", style=discord.ButtonStyle.link,
            url=f"https://discord.com/channels/{interaction.guild_id}", emoji="⬆️",
        ))

        view = discord.ui.View(timeout=None)
        for btn in buttons[:5]:
            view.add_item(btn)

        # ── Send DM cascade ────────────────────────────────────────────────────
        # Delay is configurable via /setgendelay (default keeps the original pacing).
        try:
            delay = max(0.0, min(30.0, float(db.get_config("gen_delay_seconds", 10))))
        except (ValueError, TypeError):
            delay = 10.0
        await asyncio.sleep(1.3)
        if delay > 0:
            await status_msg.edit(content="🔄 **Adding Account to API...** This may take a moment...")
            await asyncio.sleep(delay)
        await status_msg.edit(content="✅ **Account Ready!** Details below 👇")

        # ── Assemble payloads ──────────────────────────────────────────────────
        dm_payload: dict = {"embeds": [dm_embed], "view": view}
        channel_payload: dict = {"embeds": [channel_embed]}

        if banner_file:
            try:
                dm_file = discord.File(banner_file["path"], filename=banner_file["name"])
                ch_file = discord.File(banner_file["path"], filename=banner_file["name"])
                dm_payload["files"] = [dm_file]
                channel_payload["files"] = [ch_file]
            except Exception:
                pass

        # ── Deliver ────────────────────────────────────────────────────────────
        try:
            await interaction.user.send(**dm_payload)
            delivered = True
        except Exception:
            delivered = False

        if delivered:
            db.log_generate(str(interaction.user.id), category)
            await interaction.followup.send(**channel_payload)
        else:
            # Restore stock and refund cooldown
            db.restore_stock(category, raw)
            db.update_user(str(interaction.user.id), {
                f"last_gen_{cat_key}": last_gen,
                "last_gen": user.get("last_gen", 0),
            })
            await status_msg.edit(
                content="⚠️ Couldn't deliver your account (your DMs may have just closed). "
                        "It was returned to stock — please run `/generate` again."
            )
            fail_embed = discord.Embed(
                color=0xFEE75C, title="⚠️ Delivery Failed",
                description=f"<@{interaction.user.id}> we couldn't finish delivering your account, "
                            f"so it was returned to stock. Please try **/generate** again.",
            )
            await interaction.followup.send(embeds=[fail_embed])


class GenerateButtonHandler(commands.Cog):
    """Handles persistent button interactions from generate embeds."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        custom_id = interaction.data.get("custom_id", "")

        if custom_id == "copy_creds":
            embed = interaction.message.embeds[0] if interaction.message and interaction.message.embeds else None
            creds = ""
            if embed:
                for field in embed.fields:
                    if "Login Credentials" in (field.name or ""):
                        creds = (field.value or "").strip("`").strip()
                        break
            if not creds:
                return await interaction.response.send_message(
                    "❌ Could not find credentials on this message.", ephemeral=True
                )
            await interaction.response.send_message(
                f"📋 **Tap and hold (or triple-click) to copy:**\n```{creds}```",
                ephemeral=True,
            )

        elif custom_id == "how_to_link":
            embed = discord.Embed(
                color=0x5865F2,
                title="❓ How to Link Your Account",
                description="\n".join([
                    "**1.** Open the platform login page (Ubisoft Connect / console store).",
                    "**2.** Sign in with the **email** and **password** above.",
                    "**3.** Complete any 2FA prompts — check the account notes for 2FA status.",
                    "**4.** Tap **Copy Skin Link** to preview the account inventory.",
                    "",
                    "⚠️ Only change the password if the account notes confirm it is safe.",
                ]),
            ).set_footer(text="Generator")
            await interaction.response.send_message(embeds=[embed], ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Generate(bot))
    await bot.add_cog(GenerateButtonHandler(bot))
