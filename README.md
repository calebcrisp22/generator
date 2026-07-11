# Generator Bot — Python

Python rewrite of the Discord account generator bot.

## Setup

1. **Set secrets** in Replit (Secrets tab) or copy `.env.example` → `.env`:
   - `BOT_TOKEN` — your Discord bot token
   - `OWNER_ID` — your Discord user ID (right-click yourself → Copy User ID)

2. **Enable Privileged Intents** in the [Discord Developer Portal](https://discord.com/developers/applications):
   - Server Members Intent ✅
   - Message Content Intent ✅

3. **Run** the bot (Replit workflow or `python main.py` from the `bot/` directory).

## Slash Commands

| Command | Access | Description |
|---|---|---|
| `/generate [category]` | Tier role / sub | Generate an account from stock |
| `/stock` | Everyone | Show stock levels |
| `/addstock` | Owner | Add accounts to stock |
| `/clearstock` | Owner | Clear stock |
| `/setcooldown` | Owner | Set per-category cooldown |
| `/subscribe` | Owner | Grant a subscription |
| `/unsubscribe` | Owner | Revoke a subscription |
| `/subscription` | Everyone | Check subscription status |
| `/vouch` | Everyone | Leave a vouch |
| `/vouches` | Everyone | Show recent vouches |
| `/deletevouch` | Owner | Delete a vouch |
| `/drop setup` | Owner | Configure drop channel |
| `/drop start` | Owner | Start auto-drops |
| `/drop stop` | Owner | Stop auto-drops |
| `/drop status` | Everyone | Show drop status |
| `/drop addstock` | Owner | Add drop stock |
| `/drop clearstock` | Owner | Clear drop stock |
| `/drop now` | Owner | Trigger an immediate drop |
| `/config setrole` | Owner | Assign a Discord role to a tier |
| `/config view` | Owner | View bot configuration |
| `/setstatus` | Owner | Set bot presence |
| `/setbanner` | Owner | Set thumbnail shown on generated accounts |
| `/clearbanner` | Owner | Remove the banner image |
| `/tokens add` | Owner | Add tokens to a user |
| `/tokens remove` | Owner | Remove tokens from a user |
| `/tokens balance` | Everyone | Check token balance |
| `/resetinvites` | Owner | Reset a user's invite count |
| `/profile` | Everyone | View user profile |
| `/invites` | Everyone | Check invite count |
| `/inviteleaderboard` | Everyone | Top inviters |

## Data Storage

All data is stored as JSON files in `bot/data/` (or `$DATA_DIR` if set):
- `config.json` — bot configuration
- `drop_config.json` — drop system config
- `users.json` — user records
- `stock.json` — generate stock
- `drop_stock.json` — drop-only stock
- `vouches.json` — vouches list
- `invite_joins.json` — invite tracking
- `invites.json` — invite metadata
