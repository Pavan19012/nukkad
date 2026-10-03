import os
import tempfile

os.environ["NUKKAD_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["NUKKAD_RESET"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.normalizer import normalize  # noqa: E402
from backend.seed_data import PRODUCTS  # noqa: E402

CAT = [{"id": p[0], "name": p[1], "aliases": p[4]} for p in PRODUCTS]


def test_normalizer_multilingual():
    cases = {
        "oats wala doodh ek litre nahi hai": ("Oat Milk 1L", 1),
        "मैगी मसाला दो": ("Maggi Masala-ae-Magic Sachet", 1),
        "ಗ್ರೀಕ್ ಮೊಸರು ಇಲ್ಲ": ("Greek Yogurt 400g", 1),
        "2 packet maggi": ("Maggi Masala Noodles 70g", 2),
        "ಹಾಲು ಎರಡು": ("Amul Taaza Milk 1L", 2),
        "protien bar": ("Protein Bar", 1),
    }
    for text, (name, qty) in cases.items():
        r = normalize(text, CAT)
        assert r.get("name") == name, (text, r)
        assert r["qty"] == qty, (text, r)


def test_unknown_item_still_logged():
    with TestClient(app) as c:
        r = c.post("/api/asks", json={"shop_id": 1, "text": "zxqv blorp"}).json()
        assert r["ask"]["product_id"] is None
        assert r["ask"]["status"] == "unmet"


def test_full_flow_capture_route_hold_sell_settle():
    with TestClient(app) as c:
        # Shop 1 (Sri Lakshmi) can't find brown bread; Sharma (2) is 200 m away and stocks it
        r = c.post("/api/asks", json={"shop_id": 1, "text": "brown bread do packet"}).json()
        ask = r["ask"]
        assert ask["product_name"] == "Brown Bread 400g" and ask["qty"] == 2
        targets = {t["shop_id"]: t for t in r["routed_to"]}
        assert 2 in targets and targets[2]["likely_has"]
        assert all(t["distance_m"] <= 500 for t in r["routed_to"])

        inc = c.get("/api/shops/2/incoming").json()
        assert any(i["id"] == ask["id"] for i in inc)

        # shop 4 says no, shop 2 says yes → held by 2
        c.post(f"/api/asks/{ask['id']}/respond", json={"shop_id": 4, "has_it": False})
        res = c.post(f"/api/asks/{ask['id']}/respond", json={"shop_id": 2, "has_it": True}).json()
        assert res["ask"]["status"] == "held" and res["ask"]["held_by"] == 2
        # a second yes loses
        late = c.post(f"/api/asks/{ask['id']}/respond", json={"shop_id": 3, "has_it": True}).json()
        assert late["ok"] is False

        sold = c.post(f"/api/asks/{ask['id']}/sold", json={"shop_id": 2, "sale_amount": 110, "upi_ref": "T123"}).json()
        assert sold["ledger"]["referral"] == 3.3
        assert sold["ledger"]["payee_shop"] == 1

        w2 = c.get("/api/shops/2/wallet").json()
        pay = next(p for p in w2["payouts"] if p["shop_id"] == 1)
        assert pay["amount"] >= 3.3
        w2 = c.post("/api/shops/2/settle", json={"payee_id": 1, "upi_ref": "UPI999"}).json()
        assert all(p["shop_id"] != 1 for p in w2["payouts"])


def test_radar_finds_unstocked_demand():
    with TestClient(app) as c:
        rd = c.get("/api/shops/1/radar").json()
        names = [i["name"] for i in rd["items"]]
        assert "Oat Milk 1L" in names
        greek = next(i for i in rd["items"] if i["name"] == "Greek Yogurt 400g")
        assert greek["shops_stocking"] == 0
        assert rd["suggestions"], "should suggest something to stock"
        assert len(rd["top_series"]) == 7
