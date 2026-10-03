"""Nukkad API — FastAPI app serving REST endpoints, a WebSocket per shop for live
requests, and the web app in /frontend.

Run:  uvicorn backend.main:app --reload
"""
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, services

FRONTEND = os.path.join(os.path.dirname(__file__), "..", "frontend")


@asynccontextmanager
async def lifespan(_app):
    services._catalog_cache = None
    db.init_db(reset=os.environ.get("NUKKAD_RESET", "0") == "1")
    yield


app = FastAPI(title="Nukkad API", version="0.1.0", lifespan=lifespan,
              description="Turn every 'nahi hai' into a sale — HackSprint prototype by Cache Me Outside")


# ---------- live updates ----------
class Hub:
    def __init__(self):
        self.clients: dict[int, set[WebSocket]] = {}

    async def join(self, shop_id, ws):
        await ws.accept()
        self.clients.setdefault(shop_id, set()).add(ws)

    def leave(self, shop_id, ws):
        self.clients.get(shop_id, set()).discard(ws)

    async def send(self, shop_id, event, data):
        for ws in list(self.clients.get(shop_id, ())):
            try:
                await ws.send_json({"event": event, "data": data})
            except Exception:
                self.leave(shop_id, ws)


hub = Hub()


@app.websocket("/ws/{shop_id}")
async def ws_endpoint(ws: WebSocket, shop_id: int):
    await hub.join(shop_id, ws)
    try:
        while True:
            await ws.receive_text()  # keep-alive pings
    except WebSocketDisconnect:
        hub.leave(shop_id, ws)


# ---------- models ----------
class AskIn(BaseModel):
    shop_id: int
    text: str
    product_id: Optional[int] = None
    qty: Optional[int] = None


class CorrectIn(BaseModel):
    product_id: int


class RespondIn(BaseModel):
    shop_id: int
    has_it: bool


class SoldIn(BaseModel):
    shop_id: int
    sale_amount: Optional[float] = None
    upi_ref: Optional[str] = None


class RestockIn(BaseModel):
    product_id: int
    qty: int


class SettleIn(BaseModel):
    payee_id: int
    upi_ref: Optional[str] = ""


class TextIn(BaseModel):
    text: str


def _need_shop(sid):
    s = services.shop(sid)
    if not s:
        raise HTTPException(404, "shop not found")
    return s


async def _broadcast_new(result):
    ask = result["ask"]
    for t in result["routed_to"]:
        await hub.send(t["shop_id"], "incoming_request", {**ask, "distance_m": t["distance_m"], "likely_has": t["likely_has"]})
    await hub.send(ask["shop_id"], "ask_update", ask)


# ---------- REST ----------
@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/shops")
def list_shops():
    return db.rows("SELECT * FROM shops ORDER BY id")


@app.get("/api/shops/{sid}")
def get_shop(sid: int):
    s = _need_shop(sid)
    return {**s, "neighbours": services.shops_within(sid, 1000), "summary": services.summary(sid)}


@app.get("/api/catalog")
def get_catalog():
    return services.catalog()


@app.post("/api/normalize")
def normalize(body: TextIn):
    from .normalizer import normalize as n
    return n(body.text, services.catalog())


@app.post("/api/asks")
async def create_ask(body: AskIn):
    _need_shop(body.shop_id)
    if not body.text.strip() and not body.product_id:
        raise HTTPException(400, "empty ask")
    result = services.capture(body.shop_id, body.text.strip(), body.product_id, body.qty)
    await _broadcast_new(result)
    return result


@app.post("/api/asks/{aid}/correct")
async def correct_ask(aid: int, body: CorrectIn):
    result = services.correct(aid, body.product_id)
    await _broadcast_new(result)
    return result


@app.post("/api/asks/{aid}/respond")
async def respond(aid: int, body: RespondIn):
    before = services.get_ask(aid)
    if not before:
        raise HTTPException(404, "ask not found")
    res = services.respond(aid, body.shop_id, body.has_it)
    if res["ok"] and body.has_it:
        ask = res["ask"]
        await hub.send(ask["shop_id"], "ask_update", ask)
        for r in db.rows("SELECT shop_id FROM routes WHERE ask_id=?", (aid,)):
            if r["shop_id"] != body.shop_id:
                await hub.send(r["shop_id"], "request_closed", {"id": aid})
    elif res["ok"]:
        await hub.send(res["ask"]["shop_id"], "ask_update", res["ask"])
    return res


@app.post("/api/asks/{aid}/sold")
async def sold(aid: int, body: SoldIn):
    res = services.mark_sold(aid, body.shop_id, body.sale_amount, body.upi_ref)
    if not res["ok"]:
        raise HTTPException(400, res["error"])
    await hub.send(res["ask"]["shop_id"], "ask_update", res["ask"])
    await hub.send(res["ask"]["shop_id"], "ledger", res["ledger"])
    return res


@app.get("/api/shops/{sid}/asks")
def shop_asks(sid: int):
    _need_shop(sid)
    return services.outgoing(sid)


@app.get("/api/shops/{sid}/incoming")
def shop_incoming(sid: int):
    _need_shop(sid)
    return services.incoming(sid)


@app.get("/api/shops/{sid}/holding")
def shop_holding(sid: int):
    _need_shop(sid)
    return services.holding(sid)


@app.get("/api/shops/{sid}/summary")
def shop_summary(sid: int):
    _need_shop(sid)
    return services.summary(sid)


@app.get("/api/shops/{sid}/radar")
def shop_radar(sid: int, radius_m: int = 1000, days: int = 7):
    _need_shop(sid)
    return services.radar(sid, radius_m, days)


@app.get("/api/shops/{sid}/restock")
def get_restock(sid: int):
    return services.restock_list(sid)


@app.post("/api/shops/{sid}/restock")
def post_restock(sid: int, body: RestockIn):
    _need_shop(sid)
    return services.add_restock(sid, body.product_id, body.qty)


@app.get("/api/shops/{sid}/wallet")
def get_wallet(sid: int):
    _need_shop(sid)
    return services.wallet(sid)


@app.post("/api/shops/{sid}/settle")
def post_settle(sid: int, body: SettleIn):
    _need_shop(sid)
    return services.settle(sid, body.payee_id, body.upi_ref or "")


@app.post("/api/demo/reset")
def demo_reset():
    services._catalog_cache = None
    db.init_db(reset=True)
    return {"ok": True}


# ---------- web app ----------
@app.get("/")
def index():
    return FileResponse(os.path.join(FRONTEND, "index.html"))


app.mount("/", StaticFiles(directory=FRONTEND), name="static")
