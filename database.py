"""
database.py — JSON-file-based persistence layer.
Mirrors the original database.js behaviour exactly.
"""

import json
import os
import re
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
STOCK_DIR = DATA_DIR / "stock"
STOCK_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR = Path(__file__).parent / "backups"
MAX_BACKUPS = 10


# ── helpers ───────────────────────────────────────────────────────────────────

def _atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` via a temp file + atomic rename so a crash
    or process restart mid-write never leaves a truncated/corrupt file."""
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _load(filename: str, default: Any) -> Any:
    p = DATA_DIR / filename
    if not p.exists():
        _atomic_write(p, json.dumps(default, indent=2))
        return default
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _save(filename: str, data: Any) -> None:
    _atomic_write(DATA_DIR / filename, json.dumps(data, indent=2))


def _repair_json_text(text: str) -> str:
    """Best-effort repair of near-valid JSON — strips trailing commas before
    closing brackets/braces, which is the most common corruption pattern
    (e.g. a stray blank line or ``\\n`` entry left dangling at the end of an
    array)."""
    return re.sub(r",\s*([\]}])", r"\1", text)


def _sanitize_stock_entries(items: list) -> tuple:
    """Strip null / empty / whitespace-only entries from a stock category
    array. Returns (cleaned_list, removed_count)."""
    cleaned = []
    removed = 0
    for item in items:
        if item is None:
            removed += 1
            continue
        if isinstance(item, str) and item.strip() == "":
            removed += 1
            continue
        cleaned.append(item)
    return cleaned, removed


def _load_stock(table: str) -> dict:
    p = DATA_DIR / f"{table}.json"
    if not p.exists():
        _atomic_write(p, "{}")
        return {}

    raw = p.read_text()
    try:
        data = json.loads(raw)
    except Exception:
        # Attempt a best-effort repair (e.g. trailing commas caused by stray
        # newline entries) before giving up entirely.
        try:
            data = json.loads(_repair_json_text(raw))
        except Exception:
            return {}

    if not isinstance(data, dict):
        return {}

    # Sanitize each category array in-memory (does not touch disk — use
    # validate_stock() to persist the cleaned data).
    cleaned = {}
    for category, items in data.items():
        if isinstance(items, list):
            cleaned[category], _ = _sanitize_stock_entries(items)
        else:
            cleaned[category] = items
    return cleaned


def _save_stock(table: str, data: dict) -> None:
    _atomic_write(DATA_DIR / f"{table}.json", json.dumps(data, indent=2))


def validate_stock(table: str = "stock") -> dict:
    """Checks stock.json (or the given stock table) for corruption and
    repairs it in place. Removes null/empty/whitespace-only entries from
    every category array and, if the file could not be parsed as valid
    JSON, attempts a best-effort repair before re-saving.

    Returns a report dict:
        {
            "was_corrupt": bool,
            "total_removed": int,
            "categories": {category: removed_count, ...},
        }
    """
    p = DATA_DIR / f"{table}.json"
    if not p.exists():
        return {"was_corrupt": False, "total_removed": 0, "categories": {}}

    raw = p.read_text()
    was_corrupt = False
    try:
        data = json.loads(raw)
    except Exception:
        was_corrupt = True
        try:
            data = json.loads(_repair_json_text(raw))
        except Exception:
            data = {}

    if not isinstance(data, dict):
        data = {}
        was_corrupt = True

    cleaned = {}
    categories_removed = {}
    total_removed = 0
    for category, items in data.items():
        if not isinstance(items, list):
            cleaned[category] = items
            continue
        valid, removed = _sanitize_stock_entries(items)
        cleaned[category] = valid
        if removed:
            categories_removed[category] = removed
            total_removed += removed

    if was_corrupt or total_removed > 0:
        _save_stock(table, cleaned)

    return {
        "was_corrupt": was_corrupt,
        "total_removed": total_removed,
        "categories": categories_removed,
    }


_DEFAULT_USER = dict(
    tokens=0, subscription="none", sub_expires=0,
    plus_time=0, joins=0, messages=0, last_gen=0, last_drop=0
)


# ── config ────────────────────────────────────────────────────────────────────

def get_config(key: str, default=None):
    return _load("config.json", {}).get(key, default)


def set_config(key: str, value) -> None:
    cfg = _load("config.json", {})
    cfg[key] = value
    _save("config.json", cfg)


# ── drop config ───────────────────────────────────────────────────────────────

def get_drop_config(key: str, default=None):
    return _load("drop_config.json", {}).get(key, default)


def set_drop_config(key: str, value) -> None:
    cfg = _load("drop_config.json", {})
    cfg[key] = value
    _save("drop_config.json", cfg)


# ── users ─────────────────────────────────────────────────────────────────────

def get_user(user_id: str) -> dict:
    users = _load("users.json", {})
    if user_id not in users:
        users[user_id] = {"id": user_id, **_DEFAULT_USER}
        _save("users.json", users)
    return users[user_id]


def update_user(user_id: str, fields: dict) -> None:
    users = _load("users.json", {})
    if user_id not in users:
        users[user_id] = {"id": user_id, **_DEFAULT_USER}
    users[user_id].update(fields)
    _save("users.json", users)


def increment_user_field(user_id: str, field: str, by: int = 1) -> None:
    users = _load("users.json", {})
    if user_id not in users:
        users[user_id] = {"id": user_id, **_DEFAULT_USER}
    users[user_id][field] = (users[user_id].get(field) or 0) + by
    _save("users.json", users)


def get_all_users() -> list:
    return list(_load("users.json", {}).values())


# ── stock ─────────────────────────────────────────────────────────────────────

def all_categories() -> list:
    stock = _load_stock("stock")
    return [k for k, v in stock.items() if v]


def stock_count(category: str) -> int:
    return len(_load_stock("stock").get(category, []))


def add_stock_bulk(category: str, lines: list, table: str = "stock") -> int:
    stock = _load_stock(table)
    stock.setdefault(category, []).extend(lines)
    _save_stock(table, stock)
    return len(lines)


def pop_stock(category: str):
    stock = _load_stock("stock")
    if not stock.get(category):
        return None
    item = stock[category].pop(0)
    _save_stock("stock", stock)
    return item


def restore_stock(category: str, item: str) -> None:
    stock = _load_stock("stock")
    stock.setdefault(category, []).insert(0, item)
    _save_stock("stock", stock)


def clear_stock(category: str = None) -> int:
    stock = _load_stock("stock")
    if category:
        count = len(stock.get(category, []))
        stock[category] = []
        _save_stock("stock", stock)
        return count
    count = sum(len(v) for v in stock.values())
    _save_stock("stock", {})
    return count


# ── drop stock ────────────────────────────────────────────────────────────────

def drop_categories() -> list:
    stock = _load_stock("drop_stock")
    return [k for k, v in stock.items() if v]


def drop_stock_count(category: str) -> int:
    return len(_load_stock("drop_stock").get(category, []))


def pop_drop_stock(category: str):
    stock = _load_stock("drop_stock")
    if not stock.get(category):
        return None
    item = stock[category].pop(0)
    _save_stock("drop_stock", stock)
    return item


def restore_drop_stock(category: str, item: str) -> None:
    """Return a previously-popped drop item back to the front of the pool (mirrors restore_stock)."""
    data = _load_stock("drop_stock")
    pool = data.get(category, [])
    pool.insert(0, item)
    data[category] = pool
    _save_stock("drop_stock", data)


def clear_drop_stock(category: str = None) -> int:
    stock = _load_stock("drop_stock")
    if category:
        count = len(stock.get(category, []))
        stock[category] = []
        _save_stock("drop_stock", stock)
        return count
    count = sum(len(v) for v in stock.values())
    _save_stock("drop_stock", {})
    return count


# ── invites ───────────────────────────────────────────────────────────────────

def add_invite_join(user_id: str, inviter_id: str, code: str) -> None:
    joins = _load("invite_joins.json", [])
    joins.append({"user_id": user_id, "inviter_id": inviter_id,
                  "code": code, "joined_at": int(time.time())})
    _save("invite_joins.json", joins)


def get_inviter_joins(user_id: str) -> int:
    return sum(1 for j in _load("invite_joins.json", []) if j["inviter_id"] == user_id)


def get_joins_by_inviter(user_id: str) -> list:
    """Return the full list of join records for a given inviter (for /viewjoins)."""
    return [j for j in _load("invite_joins.json", []) if j["inviter_id"] == user_id]


def get_inviter_leaderboard() -> list:
    counts: dict = {}
    for j in _load("invite_joins.json", []):
        counts[j["inviter_id"]] = counts.get(j["inviter_id"], 0) + 1
    return [{"inviter_id": uid, "count": c}
            for uid, c in sorted(counts.items(), key=lambda x: -x[1])[:10]]


def reset_inviter_joins(user_id: str) -> None:
    joins = [j for j in _load("invite_joins.json", []) if j["inviter_id"] != user_id]
    _save("invite_joins.json", joins)


def save_invite(code: str, inviter_id: str, max_uses: int) -> None:
    invites = _load("invites.json", {})
    invites[code] = {"code": code, "inviter_id": inviter_id,
                     "uses": 0, "max_uses": max_uses,
                     "created_at": int(time.time())}
    _save("invites.json", invites)


def get_invites_by_user(user_id: str) -> list:
    return [i for i in _load("invites.json", {}).values() if i["inviter_id"] == user_id]


# ── banner ────────────────────────────────────────────────────────────────────

def save_banner(data: bytes, ext: str) -> str:
    safe_ext = "".join(c for c in (ext or "png").lower() if c.isalnum()) or "png"
    for f in DATA_DIR.iterdir():
        if f.name.startswith("banner."):
            try:
                f.unlink()
            except Exception:
                pass
    filename = f"banner.{safe_ext}"
    (DATA_DIR / filename).write_bytes(data)
    return filename


def get_banner_file():
    try:
        for f in DATA_DIR.iterdir():
            if f.name.startswith("banner."):
                return {"name": f.name, "path": str(f)}
    except Exception:
        pass
    return None


def clear_banner() -> None:
    for f in DATA_DIR.iterdir():
        if f.name.startswith("banner."):
            try:
                f.unlink()
            except Exception:
                pass


# ── blacklist ─────────────────────────────────────────────────────────────────

def blacklist_add(user_id: str, reason: str = "No reason given") -> bool:
    """Returns True if newly added, False if already present."""
    bl = _load("blacklist.json", [])
    if any(e["user_id"] == user_id for e in bl):
        return False
    bl.append({"user_id": user_id, "reason": reason, "added_at": int(time.time())})
    _save("blacklist.json", bl)
    return True


def blacklist_remove(user_id: str) -> bool:
    """Returns True if removed, False if wasn't listed."""
    bl = _load("blacklist.json", [])
    filtered = [e for e in bl if e["user_id"] != user_id]
    if len(filtered) == len(bl):
        return False
    _save("blacklist.json", filtered)
    return True


def is_blacklisted(user_id: str) -> bool:
    return any(e["user_id"] == user_id for e in _load("blacklist.json", []))


def get_blacklist() -> list:
    return _load("blacklist.json", [])


# ── generate log ──────────────────────────────────────────────────────────────

def log_generate(user_id: str, category: str) -> None:
    """Append an entry to the rolling generate log (capped at 500)."""
    logs = _load("gen_log.json", [])
    logs.insert(0, {"user_id": user_id, "category": category, "timestamp": int(time.time())})
    _save("gen_log.json", logs[:500])


def get_generate_logs(limit: int = 20) -> list:
    return _load("gen_log.json", [])[:limit]


def get_generate_stats() -> dict:
    """Return total generate count and per-category breakdown."""
    logs = _load("gen_log.json", [])
    by_cat: dict = {}
    for entry in logs:
        cat = entry.get("category", "unknown")
        by_cat[cat] = by_cat.get(cat, 0) + 1
    return {"total": len(logs), "by_category": by_cat}


# ── stock alerts ──────────────────────────────────────────────────────────────

def get_stock_alerts() -> dict:
    """Returns {category: {threshold, channel_id, role_id, last_fired}} dict."""
    return _load("stock_alerts.json", {})


def set_stock_alert(category: str, threshold: int,
                    channel_id: str, role_id: str = None) -> None:
    alerts = _load("stock_alerts.json", {})
    alerts[category] = {
        "threshold": threshold,
        "channel_id": channel_id,
        "role_id": role_id,
        "last_fired": 0,
    }
    _save("stock_alerts.json", alerts)


def clear_stock_alert(category: str) -> bool:
    alerts = _load("stock_alerts.json", {})
    if category not in alerts:
        return False
    del alerts[category]
    _save("stock_alerts.json", alerts)
    return True


def update_stock_alert_fired(category: str) -> None:
    alerts = _load("stock_alerts.json", {})
    if category in alerts:
        alerts[category]["last_fired"] = int(time.time())
        _save("stock_alerts.json", alerts)


# ── backups ───────────────────────────────────────────────────────────────────

def create_backup() -> Path:
    """Zip every file under DATA_DIR into a timestamped archive in BACKUP_DIR,
    then prune old backups beyond MAX_BACKUPS. Returns the new archive path.

    Kept outside DATA_DIR so backups never get swept up into themselves, and
    so wiping `data/` for a fresh start doesn't also wipe recovery copies."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    archive_path = BACKUP_DIR / f"backup-{stamp}.zip"

    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in DATA_DIR.rglob("*"):
            if f.is_file():
                zf.write(f, arcname=f.relative_to(DATA_DIR))

    backups = sorted(BACKUP_DIR.glob("backup-*.zip"), key=lambda p: p.stat().st_mtime)
    for stale in backups[:-MAX_BACKUPS]:
        try:
            stale.unlink()
        except OSError:
            pass

    return archive_path


def list_backups() -> list:
    """Return backup archives sorted newest-first as {name, size_bytes, created_at}."""
    if not BACKUP_DIR.exists():
        return []
    entries = []
    for f in sorted(BACKUP_DIR.glob("backup-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = f.stat()
        entries.append({"name": f.name, "path": str(f), "size_bytes": stat.st_size, "created_at": int(stat.st_mtime)})
    return entries
