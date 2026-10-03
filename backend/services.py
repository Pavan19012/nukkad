"""Core business logic: capture → match & route → settle → demand radar.
Process numbers match the Level-1 DFD in the pitch deck (1.0 – 4.0)."""
import json
import math
from datetime import timedelta

from . import db
from .normalizer import normalize

_catalog_cache = None


def catalog():
    global _catalog_cache
    if _catalog_cache is None:
        ps = db.rows("SELECT * FROM products ORDER BY id")
        for p in ps:
            p["aliases"] = json.loads(p["aliases"])
        _catalog_cache = ps
    return _catalog_cache


def product(pid):
    return next((p for p in catalog() if p["id"] == pid), None)


def shop(sid):
    return db.one("SELECT * FROM shops WHERE id=?", (sid,))


def shops_within(sid, radius_m):
    me = shop(sid)
    out = []
    for s in db.rows("SELECT * FROM shops"):
        d = db.haversine_m(me["lat"], me["lng"], s["lat"], s["lng"])
        if d <= radius_m:
            out.append({**s, "distance_m": round(d)})
    return sorted(out, key=lambda s: s["distance_m"])


def stocks(sid, pid):
    return db.one("SELECT 1 FROM inventory WHERE shop_id=? AND product_id=?", (sid, pid)) is not None


def expire_stale():
    """Requests nobody accepted within the TTL become 'unmet' (demand is still logged)."""
    db.execute("UPDATE asks SET status='unmet' WHERE status='searching' AND expires_at < ?", (db.iso(db.now()),))


def ask_view(a):
    if a is None:
        return None
    p = product(a["product_id"]) if a["product_id"] else None
    v = dict(a)
    v["product_name"] = p["name"] if p else None
    v["price"] = p["price"] if p else None
    v["est_value"] = round(p["price"] * a["qty"], 2) if p else None
    v["from_shop"] = shop(a["shop_id"])
    v["held_by_shop"] = shop(a["held_by"]) if a["held_by"] else None
    if a["held_by"]:
        f, h = v["from_shop"], v["held_by_shop"]
        v["held_distance_m"] = round(db.haversine_m(f["lat"], f["lng"], h["lat"], h["lng"]))
    return v


def get_ask(aid):
    return ask_view(db.one("SELECT * FROM asks WHERE id=?", (aid,)))


# ---------- 1.0 Capture & normalise ----------
def capture(shop_id, text, product_id=None, qty=None):
    norm = normalize(text, catalog())
    pid = product_id or norm["product_id"]
    q = qty or norm["qty"]
    t = db.now()
    aid = db.execute(
        "INSERT INTO asks (shop_id, raw_text, product_id, qty, confidence, status, created_at, expires_at) VALUES (?,?,?,?,?,?,?,?)",
        (shop_id, text, pid, q, 1.0 if product_id else norm["confidence"], "searching" if pid else "unmet",
         db.iso(t), db.iso(t + timedelta(minutes=db.REQUEST_TTL_MIN))))
    routed = route(aid) if pid else []
    return {"ask": get_ask(aid), "normalized": norm, "routed_to": routed}


def correct(aid, product_id):
    """Shopkeeper fixes a wrong match → re-route."""
    db.execute("DELETE FROM routes WHERE ask_id=?", (aid,))
    t = db.now()
    db.execute("UPDATE asks SET product_id=?, confidence=1.0, status='searching', held_by=NULL, created_at=?, expires_at=? WHERE id=?",
               (product_id, db.iso(t), db.iso(t + timedelta(minutes=db.REQUEST_TTL_MIN)), aid))
    return {"ask": get_ask(aid), "routed_to": route(aid)}


# ---------- 2.0 Match & route ----------
def route(aid):
    """Send the request to every other shop within the radius. Shops whose catalogue says
    they stock the item are flagged 'likely' and sorted first."""
    a = db.one("SELECT * FROM asks WHERE id=?", (aid,))
    targets = []
    for s in shops_within(a["shop_id"], db.ROUTE_RADIUS_M):
        if s["id"] == a["shop_id"]:
            continue
        likely = stocks(s["id"], a["product_id"])
        db.execute("INSERT OR REPLACE INTO routes (ask_id, shop_id, distance_m, response) VALUES (?,?,?,NULL)",
                   (aid, s["id"], s["distance_m"]))
        targets.append({"shop_id": s["id"], "name": s["name"], "distance_m": s["distance_m"], "likely_has": likely})
    targets.sort(key=lambda t: (not t["likely_has"], t["distance_m"]))
    if not targets:
        db.execute("UPDATE asks SET status='unmet' WHERE id=?", (aid,))
    return targets


def incoming(shop_id):
    expire_stale()
    rs = db.rows("""SELECT a.*, r.distance_m FROM routes r JOIN asks a ON a.id=r.ask_id
                    WHERE r.shop_id=? AND r.response IS NULL AND a.status='searching'
                    ORDER BY a.created_at DESC""", (shop_id,))
    out = []
    for r in rs:
        v = ask_view(r)
        v["distance_m"] = r["distance_m"]
        v["likely_has"] = stocks(shop_id, r["product_id"])
        out.append(v)
    return out


def respond(aid, shop_id, has_it):
    """First shop to say yes wins; the item is held for the customer."""
    expire_stale()
    a = db.one("SELECT * FROM asks WHERE id=?", (aid,))
    if not a:
        return {"ok": False, "error": "not found"}
    db.execute("UPDATE routes SET response=? WHERE ask_id=? AND shop_id=?", ("yes" if has_it else "no", aid, shop_id))
    if has_it:
        if a["status"] != "searching":
            return {"ok": False, "error": "already taken", "ask": get_ask(aid)}
        db.execute("UPDATE asks SET status='held', held_by=? WHERE id=?", (shop_id, aid))
        if not stocks(shop_id, a["product_id"]):  # learn: this shop does stock it
            db.execute("INSERT OR IGNORE INTO inventory VALUES (?,?)", (shop_id, a["product_id"]))
    else:
        pending = db.one("SELECT COUNT(*) n FROM routes WHERE ask_id=? AND response IS NULL", (aid,))["n"]
        if pending == 0 and a["status"] == "searching":
            db.execute("UPDATE asks SET status='unmet' WHERE id=?", (aid,))
    return {"ok": True, "ask": get_ask(aid)}


# ---------- 3.0 Confirm & settle referral ----------
def mark_sold(aid, shop_id, sale_amount=None, upi_ref=None):
    a = get_ask(aid)
    if not a or a["held_by"] != shop_id or a["status"] != "held":
        return {"ok": False, "error": "not held by this shop"}
    amount = float(sale_amount or a["est_value"] or 0)
    referral = round(amount * db.REFERRAL_RATE, 2)
    db.execute("UPDATE asks SET status='sold', sale_amount=? WHERE id=?", (amount, aid))
    lid = db.execute("INSERT INTO ledger (ask_id, payer_shop, payee_shop, sale_amount, referral, upi_ref, created_at) VALUES (?,?,?,?,?,?,?)",
                     (aid, shop_id, a["shop_id"], amount, referral, upi_ref or "", db.iso(db.now())))
    return {"ok": True, "ask": get_ask(aid), "ledger": db.one("SELECT * FROM ledger WHERE id=?", (lid,))}


def holding(shop_id):
    """Items this shop is holding for customers sent by other shops."""
    out = []
    for a in db.rows("SELECT * FROM asks WHERE held_by=? AND status='held' ORDER BY id DESC", (shop_id,)):
        v = ask_view(a)
        v["distance_m"] = v["held_distance_m"]
        out.append(v)
    return out


def outgoing(shop_id, limit=15):
    expire_stale()
    return [ask_view(a) for a in db.rows("SELECT * FROM asks WHERE shop_id=? ORDER BY id DESC LIMIT ?", (shop_id, limit))]


def summary(shop_id):
    expire_stale()
    start = db.iso(db.now().replace(hour=0, minute=0, second=0))
    asks = db.one("SELECT COUNT(*) n FROM asks WHERE shop_id=? AND created_at>=?", (shop_id, start))["n"]
    rec = db.one("SELECT COUNT(*) n FROM asks WHERE shop_id=? AND created_at>=? AND status='sold'", (shop_id, start))["n"]
    earned = db.one("SELECT COALESCE(SUM(referral),0) s FROM ledger WHERE payee_shop=? AND created_at>=?", (shop_id, start))["s"]
    got = db.one("SELECT COUNT(*) n FROM ledger WHERE payer_shop=? AND created_at>=?", (shop_id, start))["n"]
    return {"asks_today": asks, "recovered_today": rec, "referral_earned_today": round(earned, 2), "sales_received_today": got}


def wallet(shop_id):
    L = db.rows("SELECT * FROM ledger WHERE payer_shop=? OR payee_shop=? ORDER BY id DESC LIMIT 40", (shop_id, shop_id))
    names = {s["id"]: s for s in db.rows("SELECT * FROM shops")}
    entries = []
    for l in L:
        incoming_ = l["payee_shop"] == shop_id
        other = names[l["payer_shop"] if incoming_ else l["payee_shop"]]
        a = db.one("SELECT product_id, qty FROM asks WHERE id=?", (l["ask_id"],))
        entries.append({**l, "direction": "earned" if incoming_ else "owed", "other_shop": other["name"],
                        "other_upi": other["upi"], "product": product(a["product_id"])["name"] if a and a["product_id"] else None})
    unsettled = [e for e in entries if not e["settled"]]
    earned = sum(e["referral"] for e in unsettled if e["direction"] == "earned")
    owed = sum(e["referral"] for e in unsettled if e["direction"] == "owed")
    # what this shop owes, grouped per payee → one UPI payment each
    payouts = {}
    for e in unsettled:
        if e["direction"] == "owed":
            p = payouts.setdefault(e["payee_shop"], {"shop_id": e["payee_shop"], "name": e["other_shop"], "upi": e["other_upi"], "amount": 0})
            p["amount"] = round(p["amount"] + e["referral"], 2)
    tot_e = db.one("SELECT COALESCE(SUM(referral),0) s, COUNT(*) n FROM ledger WHERE payee_shop=?", (shop_id,))
    tot_s = db.one("SELECT COALESCE(SUM(sale_amount),0) s, COUNT(*) n FROM ledger WHERE payer_shop=?", (shop_id,))
    return {"unsettled_earned": round(earned, 2), "unsettled_owed": round(owed, 2), "net": round(earned - owed, 2),
            "lifetime_referrals_earned": round(tot_e["s"], 2), "customers_sent": tot_e["n"],
            "sales_from_network": round(tot_s["s"], 2), "customers_received": tot_s["n"],
            "payouts": list(payouts.values()), "entries": entries}


def settle(shop_id, payee_id, upi_ref=""):
    db.execute("UPDATE ledger SET settled=1, upi_ref=COALESCE(NULLIF(?,''), upi_ref) WHERE payer_shop=? AND payee_shop=? AND settled=0",
               (upi_ref, shop_id, payee_id))
    return wallet(shop_id)


# ---------- 4.0 Demand Radar ----------
def radar(shop_id, radius_m=1000, days=7):
    expire_stale()
    area = shops_within(shop_id, radius_m)
    ids = [s["id"] for s in area]
    t = db.now()
    since, prev = db.iso(t - timedelta(days=days)), db.iso(t - timedelta(days=2 * days))
    ph = ",".join("?" * len(ids))
    cur = db.rows(f"SELECT * FROM asks WHERE shop_id IN ({ph}) AND created_at>=?", (*ids, since))
    old = db.rows(f"SELECT product_id, COUNT(*) n FROM asks WHERE shop_id IN ({ph}) AND created_at>=? AND created_at<? GROUP BY product_id",
                  (*ids, prev, since))
    prev_n = {r["product_id"]: r["n"] for r in old}

    items = {}
    for a in cur:
        if not a["product_id"]:
            continue
        it = items.setdefault(a["product_id"], {"asks": 0, "unmet": 0, "recovered": 0, "units": 0})
        it["asks"] += 1
        it["units"] += a["qty"]
        if a["status"] == "sold":
            it["recovered"] += 1
        elif a["status"] in ("unmet", "expired"):
            it["unmet"] += 1
    out = []
    for pid, it in items.items():
        p = product(pid)
        stocking = sum(1 for sid in ids if stocks(sid, pid))
        prev_asks = prev_n.get(pid, 0)
        forecast = max(0, round(it["asks"] + 0.5 * (it["asks"] - prev_asks)))  # simple trend projection
        out.append({"product_id": pid, "name": p["name"], "category": p["category"], "price": p["price"],
                    "asks": it["asks"], "unmet": it["unmet"], "recovered": it["recovered"],
                    "shops_stocking": stocking, "you_stock": stocks(shop_id, pid),
                    "unmet_value": round(it["unmet"] * p["price"] * it["units"] / max(it["asks"], 1), 0),
                    "prev_asks": prev_asks, "forecast_next_week": forecast,
                    "trend_pct": round((it["asks"] - prev_asks) / prev_asks * 100) if prev_asks else None})
    out.sort(key=lambda x: (-x["asks"], -x["unmet_value"]))

    mine = [a for a in cur if a["shop_id"] == shop_id]
    mine_val = lambda arr: round(sum((product(a["product_id"])["price"] * a["qty"]) for a in arr if a["product_id"]), 0)
    missed = {"asks": len(mine), "value": mine_val(mine),
              "recovered": sum(1 for a in mine if a["status"] == "sold"),
              "lost": sum(1 for a in mine if a["status"] in ("unmet", "expired")),
              "lost_value": mine_val([a for a in mine if a["status"] in ("unmet", "expired")])}

    suggestions = []
    for it in out:
        if it["you_stock"]:
            continue
        # your fair share of the area's demand (+50% headroom), not the whole area's
        weekly_units = math.ceil(it["forecast_next_week"] / max(len(ids), 1) * 1.5)
        if weekly_units < 3:
            continue
        suggestions.append({"product_id": it["product_id"], "name": it["name"], "suggested_qty": weekly_units,
                            "est_weekly_revenue": round(weekly_units * it["price"]),
                            "reason": (f"{it['asks']} asks in {days} days, "
                                       + ("no shop nearby stocks it" if it["shops_stocking"] == 0
                                          else f"only {it['shops_stocking']} shop(s) within {radius_m} m stock it"))})
    suggestions.sort(key=lambda s: -s["est_weekly_revenue"])

    # daily series for the top item (sparkline)
    series = []
    if out:
        top = out[0]["product_id"]
        start = (t - timedelta(days=days)).date().isoformat()
        hist = db.rows(f"SELECT substr(created_at,1,10) day, COUNT(*) n FROM asks WHERE shop_id IN ({ph}) AND product_id=? "
                       "AND created_at>=? GROUP BY day", (*ids, top, start))
        per_day = {h["day"]: h["n"] for h in hist}
        for d in range(days, 0, -1):  # last N complete days
            day = (t - timedelta(days=d)).date().isoformat()
            series.append({"day": day, "asks": per_day.get(day, 0)})

    unknown = [a["raw_text"] for a in cur if not a["product_id"]][:10]
    return {"radius_m": radius_m, "days": days, "shops_in_area": len(ids), "missed": missed,
            "items": out[:10], "suggestions": suggestions[:3], "top_series": series, "uncatalogued": unknown}


def add_restock(shop_id, product_id, qty):
    db.execute("INSERT INTO restock (shop_id, product_id, qty, created_at) VALUES (?,?,?,?)", (shop_id, product_id, qty, db.iso(db.now())))
    return restock_list(shop_id)


def restock_list(shop_id):
    return [{**r, "name": product(r["product_id"])["name"]} for r in
            db.rows("SELECT * FROM restock WHERE shop_id=? ORDER BY id DESC", (shop_id,))]
