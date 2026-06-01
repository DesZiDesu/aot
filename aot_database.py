"""Database migration — converts per-guild JSON files to SQLite.

Usage:
    python aot_database.py migrate <guild_id>   # migrate one guild
    python aot_database.py migrate-all          # migrate every guild found in data/
    python aot_database.py export <guild_id>    # export SQLite back to JSON (rollback)

The bot continues to use JSON by default.  Run this script offline to produce
a sqlite3 database at data/aot_<guild_id>.db for inspection or archival.
"""
import sys, os, json, sqlite3, re
from pathlib import Path

DATA_DIR = Path("data")

_TABLES = {
    "players": "CREATE TABLE IF NOT EXISTS players (user_id TEXT PRIMARY KEY, data TEXT)",
    "config":  "CREATE TABLE IF NOT EXISTS config  (key TEXT PRIMARY KEY, value TEXT)",
    "items":   "CREATE TABLE IF NOT EXISTS items   (id TEXT PRIMARY KEY, data TEXT)",
    "shops":   "CREATE TABLE IF NOT EXISTS shops   (id TEXT PRIMARY KEY, data TEXT)",
    "missions": "CREATE TABLE IF NOT EXISTS missions (id TEXT PRIMARY KEY, data TEXT)",
    "jobs":    "CREATE TABLE IF NOT EXISTS jobs    (id TEXT PRIMARY KEY, data TEXT)",
    "squads":  "CREATE TABLE IF NOT EXISTS squads  (id TEXT PRIMARY KEY, data TEXT)",
    "logs":    "CREATE TABLE IF NOT EXISTS logs    (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, category TEXT, text TEXT)",
}


def _open_db(guild_id: int) -> sqlite3.Connection:
    db = sqlite3.connect(DATA_DIR / f"aot_{guild_id}.db")
    for ddl in _TABLES.values():
        db.execute(ddl)
    db.commit()
    return db


def _load(path: Path):
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def migrate(guild_id: int):
    db = _open_db(guild_id)

    players = _load(DATA_DIR / f"players_{guild_id}.json") or {}
    for uid, data in players.items():
        db.execute("INSERT OR REPLACE INTO players VALUES (?,?)",
                   (uid, json.dumps(data, ensure_ascii=False)))

    cfg = _load(DATA_DIR / f"config_{guild_id}.json") or {}
    for k, v in cfg.items():
        db.execute("INSERT OR REPLACE INTO config VALUES (?,?)",
                   (k, json.dumps(v, ensure_ascii=False)))

    items = _load(DATA_DIR / f"items_{guild_id}.json") or {}
    db.execute("INSERT OR REPLACE INTO items VALUES (?,?)",
               ("__all__", json.dumps(items, ensure_ascii=False)))

    shops = _load(DATA_DIR / f"shops_{guild_id}.json") or {}
    for sid, s in shops.get("shops", {}).items():
        db.execute("INSERT OR REPLACE INTO shops VALUES (?,?)",
                   (sid, json.dumps(s, ensure_ascii=False)))

    missions = _load(DATA_DIR / f"missions_{guild_id}.json") or {}
    for mid, m in missions.get("missions", {}).items():
        db.execute("INSERT OR REPLACE INTO missions VALUES (?,?)",
                   (mid, json.dumps(m, ensure_ascii=False)))

    jobs = _load(DATA_DIR / f"jobs_{guild_id}.json") or {}
    for jid, j in jobs.get("jobs", {}).items():
        db.execute("INSERT OR REPLACE INTO jobs VALUES (?,?)",
                   (jid, json.dumps(j, ensure_ascii=False)))

    squads = _load(DATA_DIR / f"squads_{guild_id}.json") or {}
    for sid, s in squads.get("squads", {}).items():
        db.execute("INSERT OR REPLACE INTO squads VALUES (?,?)",
                   (sid, json.dumps(s, ensure_ascii=False)))

    logs = _load(DATA_DIR / f"logs_{guild_id}.json") or {}
    for entry in logs.get("entries", []):
        db.execute("INSERT INTO logs (ts, category, text) VALUES (?,?,?)",
                   (entry.get("ts", 0), entry.get("category", ""), entry.get("text", "")))

    db.commit()
    db.close()
    print(f"✅ Migrated guild {guild_id} to data/aot_{guild_id}.db")


def migrate_all():
    pattern = re.compile(r"players_(\d+)\.json")
    found   = False
    for fname in os.listdir(DATA_DIR):
        m = pattern.match(fname)
        if m:
            found = True
            migrate(int(m.group(1)))
    if not found:
        print("No guild data files found.")


def export(guild_id: int):
    db_path = DATA_DIR / f"aot_{guild_id}.db"
    if not db_path.exists():
        print(f"No database found: {db_path}"); return
    db = sqlite3.connect(db_path)

    players = {}
    for row in db.execute("SELECT user_id, data FROM players"):
        players[row[0]] = json.loads(row[1])
    with open(DATA_DIR / f"players_{guild_id}.json", "w", encoding="utf-8") as f:
        json.dump(players, f, indent=2, ensure_ascii=False)

    cfg = {}
    for row in db.execute("SELECT key, value FROM config"):
        cfg[row[0]] = json.loads(row[1])
    with open(DATA_DIR / f"config_{guild_id}.json", "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

    db.close()
    print(f"✅ Exported guild {guild_id} back to JSON files.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "migrate" and len(sys.argv) >= 3:
        migrate(int(sys.argv[2]))
    elif cmd == "migrate-all":
        migrate_all()
    elif cmd == "export" and len(sys.argv) >= 3:
        export(int(sys.argv[2]))
    else:
        print(__doc__)
