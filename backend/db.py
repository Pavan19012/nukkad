"""SQLite storage. The production design uses PostgreSQL + PostGIS; SQLite keeps the
prototype zero-setup. Every call opens its own short-lived connection."""
import json
import math
import os
import random
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from . import seed_data

DB_PATH = os.environ.get("NUKKAD_DB", os.path.join(os.path.dirname(__file__), "..", "nukkad.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS shops (
    id INTEGER PRIMARY KEY, name TEXT, owner TEXT, lat REAL, lng REAL, upi TEXT
);
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY, name TEXT, price REAL, category TEXT, aliases TEXT
);
CREATE TABLE IF NOT EXISTS inventory (
    shop_id INTEGER, product_id INTEGER, PRIMARY KEY (shop_id, product_id)
);
CREATE TABLE IF NOT EXISTS asks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id INTEGER,            -- shop where the customer asked
    raw_text TEXT,              -- what the shopkeeper said
    product_id INTEGER,         -- normalised product (NULL if not recognised)
    qty INTEGER DEFAULT 1,
    confidence REAL,
    status TEXT,                -- searching | held | sold | unmet | expired
    held_by INTEGER,            -- shop that said "yes"
    sale_amount REAL,
    created_at TEXT,
    expires_at TEXT
);
CREATE TABLE IF NOT EXISTS routes (
    ask_id INTEGER, shop_id INTEGER, distance_m REAL,
    response TEXT,              -- NULL | yes | no
    PRIMARY KEY (ask_id, shop_id)
);
CREATE TABLE IF NOT EXISTS ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ask_id INTEGER, payer_shop INTEGER, payee_shop INTEGER,
    sale_amount REAL, referral REAL, upi_ref TEXT,
    settled INTEGER DEFAULT 0, created_at TEXT
);
CREATE TABLE IF NOT EXISTS restock (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id INTEGER, product_id INTEGER, qty INTEGER, created_at TEXT
);
"""

REFERRAL_RATE = 0.03
ROUTE_RADIUS_M = 500
REQUEST_TTL_MIN = 10


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def rows(sql, args=()):
    with conn() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def one(sql, args=()):
    r = rows(sql, args)
    return r[0] if r else None


def execute(sql, args=()):
    with conn() as c:
        cur = c.execute(sql, args)
        return cur.lastrowid


# Fixed IST offset (UTC+05:30): works on Windows, which has no tz database for zoneinfo
TZ = timezone(timedelta(hours=5, minutes=30), "IST")


def now():
    """Naive local time in the merchants' timezone (IST by default)."""
    return datetime.now(TZ).replace(microsecond=0, tzinfo=None)


def iso(dt):
    return dt.isoformat(sep=" ")


def haversine_m(lat1, lng1, lat2, lng2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def init_db(reset=False, seed_history=True):
    if reset and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    with conn() as c:
        c.executescript(SCHEMA)
        if c.execute("SELECT COUNT(*) FROM shops").fetchone()[0]:
            return
        c.executemany("INSERT INTO shops VALUES (?,?,?,?,?,?)", seed_data.SHOPS)
        c.executemany("INSERT INTO products VALUES (?,?,?,?,?)",
                      [(p[0], p[1], p[2], p[3], json.dumps(p[4], ensure_ascii=False)) for p in seed_data.PRODUCTS])
        for sid, pids in seed_data.INVENTORY.items():
            c.executemany("INSERT INTO inventory VALUES (?,?)", [(sid, pid) for pid in set(pids)])
    if seed_history:
        _seed_history()


def _seed_history(days=14):
    """Two weeks of synthetic missed asks so the Radar has something to show."""
    rng = random.Random(42)
    shops = {s[0]: s for s in seed_data.SHOPS}
    prices = {p[0]: p[2] for p in seed_data.PRODUCTS}
    names = {p[0]: p[1] for p in seed_data.PRODUCTS}
    stock = {sid: set(p) for sid, p in seed_data.INVENTORY.items()}
    pids = list(seed_data.DEMAND_WEIGHTS)
    weights = [seed_data.DEMAND_WEIGHTS[p] for p in pids]
    today = now().replace(hour=0, minute=0, second=0)
    with conn() as c:
        for d in range(days, 0, -1):
            day = today - timedelta(days=d)
            growth = 1 + (days - d) / days * 0.6  # demand rising over the fortnight
            for sid in shops:
                if sid == 6:
                    continue
                for _ in range(int(rng.randint(5, 11) * growth)):
                    pid = rng.choices(pids, weights)[0]
                    if pid in stock[sid]:
                        continue
                    ts = day + timedelta(hours=rng.randint(7, 21), minutes=rng.randint(0, 59))
                    qty = rng.choice([1, 1, 1, 2])
                    nearby = [o for o in shops if o != sid and pid in stock[o] and
                              haversine_m(shops[sid][3], shops[sid][4], shops[o][3], shops[o][4]) <= ROUTE_RADIUS_M]
                    if nearby and rng.random() < 0.7:
                        holder = rng.choice(nearby)
                        amount = prices[pid] * qty
                        cur = c.execute(
                            "INSERT INTO asks (shop_id, raw_text, product_id, qty, confidence, status, held_by, sale_amount, created_at, expires_at)"
                            " VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (sid, names[pid].lower(), pid, qty, 0.95, "sold", holder, amount, iso(ts), iso(ts + timedelta(minutes=10))))
                        c.execute("INSERT INTO ledger (ask_id, payer_shop, payee_shop, sale_amount, referral, upi_ref, settled, created_at)"
                                  " VALUES (?,?,?,?,?,?,?,?)",
                                  (cur.lastrowid, holder, sid, amount, round(amount * REFERRAL_RATE, 2),
                                   f"DEMO{rng.randint(10**9, 10**10)}", 1 if d > 7 else 0, iso(ts + timedelta(minutes=8))))
                    else:
                        c.execute(
                            "INSERT INTO asks (shop_id, raw_text, product_id, qty, confidence, status, created_at, expires_at)"
                            " VALUES (?,?,?,?,?,?,?,?)",
                            (sid, names[pid].lower(), pid, qty, 0.95, "unmet", iso(ts), iso(ts + timedelta(minutes=10))))
