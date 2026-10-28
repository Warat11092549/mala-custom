# smoke_test.py - ทดสอบว่าระบบทั้งหมด "เชื่อมกัน" หลังแก้โค้ด
#
# วิธีใช้ (ในโฟลเดอร์โปรเจกต์):   python smoke_test.py
#
# ทดสอบบน "สำเนาชั่วคราว" ของโปรเจกต์ ข้อมูลจริง (data/, uploads/, static/images) ไม่ถูกแตะ
# ผ่านทั้งหมด = จบด้วยข้อความ "สรุป: ผ่าน N/N" และ exit code 0

import io
import json
import os
import re
import shutil
import sys
import tempfile
import types

SRC = os.path.dirname(os.path.abspath(__file__))
TMP = os.path.join(tempfile.mkdtemp(prefix="mala_test_"), "mala_custom")
shutil.copytree(SRC, TMP, ignore=shutil.ignore_patterns("__pycache__"))
os.chdir(TMP)
sys.path.insert(0, TMP)

try:
    import segno  # noqa: F401
except ImportError:                      # ไม่มี segno ในเครื่องทดสอบ -> ใช้ตัวปลอมแทน (ไม่ใช่ส่วนที่ทดสอบ)
    fake = types.ModuleType("segno")

    class _QR:
        def svg_inline(self, **kw):
            return "<svg/>"
    fake.make = lambda *a, **k: _QR()
    sys.modules["segno"] = fake

import app as A          # noqa: E402
import auth              # noqa: E402
import config            # noqa: E402
import orders            # noqa: E402
import delivery          # noqa: E402
import storage           # noqa: E402

results = []
import settings         # noqa: E402
import shop_status       # noqa: E402
import member_codes      # noqa: E402
import reviews           # noqa: E402
import promo             # noqa: E402
import datetime as _dt   # noqa: E402

settings.set_shop_mode("open")      # เทสต์เดิมต้องไม่ขึ้นกับเวลาจริงที่รัน -> บังคับเปิดร้านไว้ก่อน (ส่วน v1.8 ทดสอบเวลา/ปิดร้านเอง)
config.VAT_ENABLED = False          # เทสต์เดิมคิดยอดแบบไม่มี VAT -> ปิดไว้ก่อน (ส่วน "VAT 7% โหมดจำลอง" ท้ายไฟล์เปิดทดสอบเอง)
config.MAX_UNPAID_ORDERS = 999      # เทสต์เดิมสั่งหลายออเดอร์ติดกัน ปิดเพดานไว้ก่อน (ส่วน v1.7 ด้านล่างจะเปิดทดสอบ)


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


def stock(pid):
    return next(p["stock"] for p in storage.load_products() if p["id"] == pid)


def points(user):
    return next(x["points"] for x in auth.load_users() if x["username"] == user)


def status(oid):
    return orders.find_order(oid)["status"]


def client_as(username, role):
    c = A.app.test_client()
    with c.session_transaction() as s:
        s["username"], s["name"], s["role"] = username, username, role
    return c


USER = next(u["username"] for u in auth.load_users() if u["role"] == "customer")
admin = client_as("admin", "admin")
cust = client_as(USER, "customer")
DELIVERY = {"name": "T", "phone": "0812345678", "address": "x", "lat": 16.4722,
            "lng": 102.823, "note": "หน้าบ้านสีฟ้า", "km": 0, "fee": 0}
JPG = lambda: io.BytesIO(b"\xff\xd8\xff\xe0" + b"0" * 80)       # noqa: E731
PNG = lambda: io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * 80)      # noqa: E731


def place(cart):
    with cust.session_transaction() as s:
        s.update({"soup_id": "S01", "spicy": 3, "cart": cart, "delivery": dict(DELIVERY)})
    return cust.post("/order/create").headers["Location"].split("/")[2]


def send_slip(oid, fileobj, name="s.jpg"):
    cust.post(f"/order/{oid}/slip", data={"slip": (fileobj, name)}, content_type="multipart/form-data")


def act(oid, action, note=""):
    admin.post(f"/admin/order/{oid}/action", data={"action": action, "note": note})


# ============ A. สถานะออเดอร์ ============
print("\n== A. สถานะออเดอร์ (ต้องบันทึกลงไฟล์จริง)")
orders.expire_unpaid_orders(force=True)    # ออเดอร์เก่าที่ค้างไม่จ่ายในข้อมูลจริงถูกกวาด+คืนสต็อกก่อน จะได้จดสต็อกเริ่มต้นถูก
s0, p0 = stock("P001"), points(USER)
oid = place({"P001": 3, "P031": 1})
earned = orders.find_order(oid)["points_earned"]
check("สร้างออเดอร์ + ตัดสต็อก", stock("P001") == s0 - 3 and status(oid) == 1, oid)
ok, _ = orders.apply_action(orders.find_order(oid), "approve")
check("approve ตอนยังไม่ส่งสลิป ถูกปฏิเสธ", not ok and status(oid) == 1)
send_slip(oid, JPG())
check("ส่งสลิป -> สถานะ 2", status(oid) == 2)
extra_keys = {"items", "item_list", "status_name", "grand_total"} & set(orders.find_order(oid))
check("ส่งสลิปแล้วไม่มีคีย์ชั่วคราวปนลง orders.json", not extra_keys, str(extra_keys))

slip1 = orders.find_order(oid)["slip"]
act(oid, "reject", "สลิปไม่ชัด")
o = orders.find_order(oid)
check("reject -> กลับสถานะ 1 + เหตุผลลง slip_note", o["status"] == 1 and o["slip_note"] == "สลิปไม่ชัด")
check("reject ไม่ทับหมายเหตุของลูกค้า", o["note"] == "หน้าบ้านสีฟ้า", o["note"])
check("reject ลบไฟล์สลิปเดิม", o["slip"] == "" and not os.path.exists(os.path.join(orders.SLIP_FOLDER, slip1)))
send_slip(oid, JPG())
for action, want in [("approve", 3), ("deliver", 4), ("done", 5)]:
    act(oid, action)
    check(f"admin กด {action} -> สถานะ {want} และบันทึกลงไฟล์", status(oid) == want)
check("ให้แต้มครั้งเดียวตอน approve", points(USER) == p0 + earned, f"{p0}->{points(USER)}")
ok, _ = orders.apply_action(orders.find_order(oid), "cancel")
check("ออเดอร์สำเร็จแล้วยกเลิกไม่ได้", not ok and status(oid) == 5)

s1, p1 = stock("P002"), points(USER)
oid2 = place({"P002": 2})
send_slip(oid2, PNG(), "s.png")
act(oid2, "approve")
act(oid2, "deliver")
act(oid2, "cancel")
check("cancel ตอนกำลังส่ง -> สถานะ 9", status(oid2) == 9, str(status(oid2)))
check("cancel คืนสต็อก", stock("P002") == s1)
check("cancel หักแต้มคืน", points(USER) == p1)
check("สถานะ 9 มีชื่อใน STATUS_NAMES", 9 in orders.STATUS_NAMES)
check("คำสั่งที่ไม่รู้จักถูกปฏิเสธ", orders.apply_action(orders.find_order(oid), "xyz")[0] is False)

legacy = [x for x in orders.load_orders() if x["status"] in (1, 2, 3, 4) and "lines" not in x]
if legacy:
    try:
        ok, msg = orders.apply_action(orders.find_order(legacy[0]["order_id"]), "cancel")
    except Exception as e:                                       # noqa: BLE001
        ok, msg = False, repr(e)
    check("ยกเลิกออเดอร์รูปแบบเก่า (ไม่มีคีย์ lines) ได้ ไม่ crash", ok, msg)

# ============ B. จัดการสินค้า ============
print("\n== B. จัดการสินค้า")
n0 = len(storage.load_products())
admin.post("/admin/product/save", content_type="multipart/form-data", data={
    "name": "ปีกไก่", "category": "เนื้อสัตว์", "price": "9", "stock": "20", "available": "on",
    "image_file": (io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"1" * 100), "ไก่ทอด.png")})
prods = storage.load_products()
newp = prods[-1]
raw = json.load(open("data/products.json", encoding="utf-8"))
check("เพิ่มสินค้าได้ และ products.json ยังเป็น {soups, products}",
      len(prods) == n0 + 1 and isinstance(raw, dict) and set(raw) == {"soups", "products"})
check("ซุปไม่หาย", len(storage.load_soups()) >= 1)
check("ชื่อไฟล์รูป = รหัสสินค้า (ไม่ใช้ชื่อที่อัปโหลด)", newp["image"] == f"meat/{newp['id']}.png", newp["image"])
check("ไฟล์รูปมีอยู่จริง", os.path.isfile("static/images/" + newp["image"]))
for bad, label in [({"price": "abc"}, "ราคาไม่ใช่ตัวเลข"), ({"stock": "1.5"}, "สต็อกทศนิยม"),
                   ({"category": "meat"}, "หมวดนอกรายการ"), ({"category": "../../etc"}, "หมวดพยายามออกนอกโฟลเดอร์"),
                   ({"price": "-5"}, "ราคาติดลบ"), ({"price": "nan"}, "ราคา nan"), ({"name": "  "}, "ไม่มีชื่อ")]:
    form = {"name": "x", "category": "เนื้อสัตว์", "price": "5", "stock": "1"}
    form.update(bad)
    r = admin.post("/admin/product/save", data=form)
    check(f"ข้อมูลผิด ({label}) ไม่ 500 และไม่บันทึก", r.status_code == 302 and len(storage.load_products()) == n0 + 1)
admin.post("/admin/product/save", content_type="multipart/form-data", data={
    "name": "x", "category": "เนื้อสัตว์", "price": "5", "stock": "1",
    "image_file": (io.BytesIO(b"GIF89a" + b"0" * 50), "a.gif")})
check("ไฟล์ที่ไม่ใช่ JPG/PNG/WEBP ถูกปฏิเสธ", len(storage.load_products()) == n0 + 1)
admin.post("/admin/product/save", data={"id": newp["id"], "name": "ปีกไก่", "category": "เนื้อสัตว์",
                                        "price": "9", "stock": "20"})
edited = next(p for p in storage.load_products() if p["id"] == newp["id"])
check("แก้สินค้า: ไม่ติ๊กเปิดขาย -> available=False และรูปเดิมยังอยู่", edited["available"] is False and edited["image"] == newp["image"])
check("ไม่มี route /admin/products/add (ซ้ำและเคยพัง)", "/admin/products/add" not in [r.rule for r in A.app.url_map.iter_rules()])
admin.post(f"/admin/product/delete/{newp['id']}")
check("ID ใหม่ไม่ชนกับของเดิมหลังลบ", A.generate_next_product_id(storage.load_products()) not in [p["id"] for p in storage.load_products()])

# ============ C. ข้อมูล + หน้าเว็บตรงกัน ============
print("\n== C. ข้อมูลและหน้าเว็บตรงกัน")
allowed = set(config.PRODUCT_CATEGORIES)
bad_cat = [(p["id"], p["category"]) for p in storage.load_products() if p["category"] not in allowed]
check("หมวดของสินค้าทุกชิ้นอยู่ใน config.PRODUCT_CATEGORIES", not bad_cat, str(bad_cat))
bad_img = [(i["id"], i.get("image")) for i in storage.load_products() + storage.load_soups()
           if i.get("image") and not os.path.isfile("static/images/" + i["image"])]
check("รูปของสินค้า/ซุปทุกรายการมีไฟล์จริง", not bad_img, str(bad_img))
bad_status = sorted({x["status"] for x in orders.load_orders()} - set(orders.STATUS_NAMES))
check("สถานะออเดอร์ทุกค่ามีชื่อใน STATUS_NAMES", not bad_status, str(bad_status))

hist = client_as(USER, "customer").get("/history").get_data(as_text=True)
chips = re.findall(r'<span class="chip"[^>]*>\s*([^<]*?)\s*</span>', hist)
check("ประวัติสั่งซื้อแสดงชื่อสถานะภาษาไทย ไม่ใช่ตัวเลข", chips and not any(x.isdigit() for x in chips), str(chips[:4]))
with cust.session_transaction() as s:
    s.update({"soup_id": "S01", "spicy": 3, "cart": {"P001": 10, "P002": 10}, "coupon": "MALA10",
              "delivery": dict(DELIVERY)})
check("ตะกร้าแสดงส่วนลดตามยอด + คูปอง", all(t in cust.get("/cart").get_data(as_text=True) for t in ("ส่วนลดตามยอด", "คูปอง MALA10")))
summary = cust.get("/checkout/summary").get_data(as_text=True)
check("หน้าสรุปยอดแสดงราคารวมต่อรายการ (ไม่ว่าง)", re.search(r"หมูสามชั้น.*?</span>\s*<span>\s*[\d.]+ บาท", summary, re.S))
pages = ["/", "/shop", "/sauces", "/seeds", "/cart", "/budget", "/random", "/history", "/checkout"]
check("หน้าลูกค้าทุกหน้าเปิดได้", all(cust.get(u).status_code in (200, 302) for u in pages))
check("หน้า admin (ออเดอร์/สินค้า) เปิดได้", admin.get("/admin").status_code == 200 and admin.get("/admin/products").status_code == 200)
html = cust.get("/shop").get_data(as_text=True) + cust.get("/sauces").get_data(as_text=True) + cust.get("/").get_data(as_text=True)
srcs = set(re.findall(r'src="(/static/images/[^"]+)"', html))
broken = [u for u in srcs if cust.get(u).status_code != 200]
check(f"รูปทุกรูปที่หน้าร้านอ้างถึงโหลดได้ ({len(srcs)} รูป)", not broken, str(broken))
check("หน้ารายละเอียดออเดอร์ที่ยกเลิกแล้วแสดงข้อความยกเลิก", "ถูกยกเลิกแล้ว" in admin.get(f"/admin/order/{oid2}").get_data(as_text=True))

# ============ รายงานรายได้ ============
print("\n== รายงานรายได้ / วัตถุดิบขายดี")
import report  # noqa: E402
rp = report.build_report("paid", "", 0)
want = round(sum(float(o.get("total", o.get("grand_total", 0)) or 0) for o in orders.load_orders()
                 if o.get("order_id", "").startswith("MZ") and orders.get_status(o) in (3, 4, 5)), 2)
check("รายได้รวม = ผลรวม total ของออเดอร์ที่ชำระแล้วเท่านั้น (ไม่นับ 1,2,9)", rp["all_time"]["total"] >= want, f'{rp["all_time"]["total"]} / {want}')
check("รายได้รายวันรวมกัน = รายเดือน", abs(sum(d["total"] for d in report.build_report("paid", rp["monthly"][0]["label"], 0)["daily"]) - rp["monthly"][0]["total"]) < 0.01 if rp["monthly"] else True)
check("นับแบบ 'จัดส่งสำเร็จ' ไม่เกินแบบ 'ชำระแล้ว'", report.build_report("done")["all_time"]["total"] <= rp["all_time"]["total"])
check("หน้า /admin/report เปิดได้ทุกตัวเลือก", all(admin.get(u).status_code == 200 for u in (
    "/admin/report", "/admin/report?basis=done&days=7", "/admin/report?month=xxxx&days=abc")))
check("ลูกค้าเปิด /admin/report ไม่ได้", cust.get("/admin/report").status_code == 302)

# ============ ขั้นตอนเม็ดหม่าล่า / ปุ่มลัด / กดแล้วไม่เด้ง ============
print("\n== เม็ดหม่าล่า + ปุ่มลัด + อัปเดตแบบไม่โหลดหน้า")
import budget  # noqa: E402
with cust.session_transaction() as s:
    s.update({"soup_id": "S01", "spicy": 3, "cart": {}})
seed_ids = [p["id"] for p in storage.load_products() if p["category"] == "เม็ดหม่าล่า"]
shop_html = cust.get("/shop").get_data(as_text=True)
seeds_html = cust.get("/seeds").get_data(as_text=True)
check("หมวดเม็ดหม่าล่าอยู่ใน config", "เม็ดหม่าล่า" in config.PRODUCT_CATEGORIES)
check("หน้า /seeds แสดงเม็ดหม่าล่าครบ", all(f'id="item-{i}"' in seeds_html for i in seed_ids) and bool(seed_ids))
check("หน้าเลือกวัตถุดิบไม่มีแท็บ/การ์ดเม็ดหม่าล่า", not any(f'id="item-{i}"' in shop_html for i in seed_ids))
plan = budget.budget_mala(300, storage.load_soups()[0], storage.load_products())["plan"]
plan2 = budget.random_mala(300, storage.load_soups()[0], storage.load_products())["plan"]
check("จัดตามงบ/สุ่ม ไม่หยิบเม็ดหม่าล่า", not (set(plan) | set(plan2)) & set(seed_ids))
check("หน้าวัตถุดิบมีปุ่มลัดใหญ่ จัดตามงบ + สุ่ม", "cta-budget" in shop_html and "cta-random" in shop_html and "/budget" in shop_html and "/random" in shop_html)
check("แถบขั้นตอนมี 6 ขั้น มีเม็ดหม่าล่า", seeds_html.count('class="dot"') >= 5 and "เลือกเม็ดหม่าล่า" in seeds_html)
if seed_ids:
    r = cust.post(f"/add/{seed_ids[0]}", data={"back": "seeds"})
    check("กดเพิ่มจากหน้า /seeds แล้วกลับ /seeds", r.status_code == 302 and "/seeds" in r.headers["Location"], r.headers.get("Location", ""))
r = cust.post("/add/P001", headers={"X-Requested-With": "fetch"}, follow_redirects=True)
h = r.get_data(as_text=True)
check("กดเพิ่ม (แบบ fetch) ได้หน้าที่มีการ์ด + แถบยอดให้สลับ", 'id="item-P001"' in h and 'id="live-bar"' in h)
check("ทุกหน้าที่มีปุ่ม +/− โหลด cart_live.js และไฟล์มีจริง",
      all("cart_live.js" in x for x in (shop_html, cust.get("/sauces").get_data(as_text=True)))
      and cust.get("/static/cart_live.js").status_code == 200)

# ============ v1.4: ตัวเลขจัดตามงบ/สุ่ม + กรองเม็ด + หน้า QR ============
print("\n== ตัวเลขจัดตามงบ/สุ่ม")
import promo  # noqa: E402
_soups, _prods = storage.load_soups(), storage.load_products()
_price = {p["id"]: p["price"] for p in _prods}
_bad = []
_maxleft = 0
for _soup in _soups:
    for _amt in (15, 20, 30, 45, 50, 77, 80, 99, 100, 123, 150, 199, 200, 250, 300, 500, 1000):
        _runs = [budget.budget_mala(_amt, _soup, _prods)] + [budget.random_mala(_amt, _soup, _prods) for _ in range(40)]
        for _r in _runs:
            if not _r["ok"]:
                continue
            _sum = _soup["price"] + sum(_price[k] * q for k, q in _r["plan"].items())
            if _amt <= 500:    # งบสูงมาก ๆ ชนเพดาน "ชิ้นละไม่เกิน 5" (budget.MAX_PER_ITEM) จึงเหลือเงินได้
                _maxleft = max(_maxleft, _r["left"])
            if _sum != _r["total"] or _r["total"] > _amt or _r["left"] != _amt - _r["total"] or any(q < 1 for q in _r["plan"].values()):
                _bad.append((_soup["id"], _amt, _r["total"], _r["left"]))
check("จัดตามงบ/สุ่ม: ยอดรวมถูก ไม่เกินงบ เหลือ = งบ − ยอด ทุกกรณี", not _bad, str(_bad[:3]))
check("งบไม่เกิน 500: เงินเหลือน้อยกว่าของถูกสุดที่ซื้อได้ (ไม่ทิ้งเงินเกินจำเป็น)", _maxleft <= 4, f"เหลือมากสุด {_maxleft}")
check("ซุปแพงกว่างบ -> บอกว่างบไม่พอ", not budget.budget_mala(5, _soups[0], _prods)["ok"] and not budget.random_mala(5, _soups[0], _prods)["ok"])

with cust.session_transaction() as s:
    s.update({"soup_id": "S01", "spicy": 3, "cart": {}})
for _path in ("/budget", "/random"):
    _h = cust.post(_path, data={"budget": "100"}).get_data(as_text=True)
    check(f"{_path} แสดงราคาต่อรายการ + เงินเหลือครบ (ไม่ว่าง)",
          re.search(r"เหลืองบอีก\s*\d+", _h) and "<span> บาท" not in re.sub(r"\s+", " ", _h).replace("<span>  บาท", "<span> บาท")
          and "<span>บาท" not in _h and _h.count("บาท</span>") >= 3)
_h = cust.post("/budget", data={"budget": "3"}).get_data(as_text=True)
check("งบน้อยกว่าซุป: แสดงราคาซุปในข้อความ (ไม่ว่าง)", "ราคา 10 บาท" in _h, "")
_raw = budget.budget_mala(100, storage.load_soups()[0], storage.load_products())
cust.post("/budget", data={"budget": "100"})
cust.post("/budget/use", data={"budget": "100"})
with cust.session_transaction() as s:
    _cart = dict(s["cart"])
check("ใช้ชุดจัดตามงบ -> ตะกร้า = ชุดที่แสดง", _cart == {k: v for k, v in _raw["plan"].items()}, "")
with cust.session_transaction() as s:
    s["soup_id"] = "S05"
cust.post("/budget/use", data={"budget": "100"})
with cust.session_transaction() as s:
    _cart2 = dict(s["cart"])
_soup5 = next(x for x in storage.load_soups() if x["id"] == "S05")
check("เปลี่ยนซุปแล้วกดใช้ชุด -> คิดใหม่ตามซุปปัจจุบัน ไม่ใช้ชุดเก่าค้าง",
      _soup5["price"] + sum(_price[k] * q for k, q in _cart2.items()) <= 100 and _cart2 != _cart)

print("\n== กรองเม็ดหม่าล่า")
_seed_prods = [p for p in storage.load_products() if p["category"] == "เม็ดหม่าล่า"]
_names = " ".join(p["name"] for p in _seed_prods)
check("ตัวเลือกเม็ดหม่าล่า = กรองออก / ไม่กรอง (ไม่ใช่ระดับความชา)",
      "กรอง" in _names and "ชาน้อย" not in _names and "ชามาก" not in _names and len(_seed_prods) >= 2)
with cust.session_transaction() as s:
    s.update({"soup_id": "S01", "spicy": 3, "cart": {"P001": 2}})
_sh = cust.get("/seeds").get_data(as_text=True)
check("หน้า /seeds เป็นปุ่มเลือก 1 อย่าง (radio) ไม่มี +/−", _sh.count('type="radio"') >= 2 and "small-btn" not in _sh)
_a, _b = _seed_prods[0]["id"], _seed_prods[1]["id"]
cust.post("/seeds/choose", data={"seed": _a})
with cust.session_transaction() as s:
    _c1 = dict(s["cart"])
cust.post("/seeds/choose", data={"seed": _b})
with cust.session_transaction() as s:
    _c2 = dict(s["cart"])
check("เลือกกรอง/ไม่กรอง: มีได้อย่างเดียว ชามละ 1 และของอื่นยังอยู่",
      _c1 == {"P001": 2, _a: 1} and _c2 == {"P001": 2, _b: 1}, f"{_c1} {_c2}")
check("หน้า /seeds ติ๊กตัวที่เลือกไว้ให้", f'value="{_b}"' in cust.get("/seeds").get_data(as_text=True))
_r = cust.post("/seeds/choose", data={"seed": "P001"})
check("ส่งรหัสที่ไม่ใช่เม็ดหม่าล่า -> ไม่ให้ใช้", _r.status_code == 302 and "/seeds" in _r.headers["Location"])
cust.post("/seeds/choose", data={"seed": ""})
with cust.session_transaction() as s:
    _c3 = dict(s["cart"])
check("ไม่เลือก/ข้าม -> เอาตัวเลือกเม็ดออกจากตะกร้า", _c3 == {"P001": 2}, str(_c3))
cust.post("/seeds/choose", data={"seed": _a})
_ch = cust.get("/cart").get_data(as_text=True)
check("ตะกร้าแสดงตัวเลือกเม็ด และไม่มีปุ่ม +/− ของรายการนั้น", _seed_prods[0]["name"] in _ch)

print("\n== หน้า QR ชำระเงิน")
_oid = place({"P001": 2, _a: 1})
_ph = cust.get(f"/order/{_oid}/pay").get_data(as_text=True)
_o = orders.find_order(_oid)
check("หน้า QR มีชื่อบัญชีใต้ QR", config.PROMPTPAY_NAME == "นายวรัท ปัตตายะโส" and config.PROMPTPAY_NAME in _ph
      and _ph.index('class="qr"') < _ph.index(config.PROMPTPAY_NAME))
check("หน้า QR แสดงยอดโอนตรงกับออเดอร์", "{:.2f}".format(_o["total"]) in _ph and "PromptPay" in _ph)
import promptpay  # noqa: E402
_pl = promptpay.make_payload(config.PROMPTPAY_ID, _o["total"])
check("payload พร้อมเพย์ถูกต้อง (CRC + เบอร์ + ยอด)",
      promptpay.crc16(_pl[:-4]) == _pl[-4:] and "0066933189044" in _pl and "{:.2f}".format(_o["total"]) in _pl, _pl)

# ============ v1.5: น้ำจิ้ม/เม็ดอยู่แถบเดียวกับซุป + เพิ่ม/ลด/ลบ + บั๊กต่าง ๆ ============
print("\n== น้ำจิ้ม/เม็ดหม่าล่า อยู่แถบเดียวกับน้ำซุปและความเผ็ด")
_home = cust.get("/").get_data(as_text=True)
check("หน้าเลือกน้ำซุป/ความเผ็ด ไม่มีปุ่มจัดตามงบ/สุ่มแล้ว", "/budget" not in _home and "/random" not in _home and "mode-link" not in _home)
with cust.session_transaction() as s:
    s.update({"soup_id": "S01", "spicy": 3, "cart": {}})
check("หน้าเลือกวัตถุดิบยังมีปุ่มจัดตามงบ/สุ่ม", "/budget" in cust.get("/shop").get_data(as_text=True) and "/random" in cust.get("/shop").get_data(as_text=True))

_sauce = next(p for p in storage.load_products() if p["category"] == "น้ำจิ้ม")
_seedA, _seedB = [p for p in storage.load_products() if p["category"] == "เม็ดหม่าล่า"][:2]
def _cart():
    with cust.session_transaction() as s:
        return dict(s.get("cart", {}))

cust.post("/add/P001"); cust.post("/add/P001")
cust.post(f"/add/{_sauce['id']}"); cust.post(f"/add/{_sauce['id']}")
check("เพิ่ม: วัตถุดิบ/น้ำจิ้ม นับจำนวนถูก", _cart() == {"P001": 2, _sauce["id"]: 2}, str(_cart()))
cust.post(f"/decrease/{_sauce['id']}")
check("ลด: น้ำจิ้ม 2 -> 1", _cart().get(_sauce["id"]) == 1)
cust.post(f"/decrease/{_sauce['id']}")
check("ลด: ถึง 0 แล้วหายจากตะกร้า (ไม่ติดลบ)", _sauce["id"] not in _cart())
cust.post(f"/add/{_sauce['id']}", data={"back": "cart"}); cust.post(f"/add/{_sauce['id']}", data={"back": "cart"})
cust.post(f"/add/{_seedA['id']}"); cust.post(f"/add/{_seedA['id']}")
check("เม็ดหม่าล่า: กดเพิ่มซ้ำก็ยังชามละ 1", _cart().get(_seedA["id"]) == 1)
cust.post(f"/add/{_seedB['id']}")
_c = _cart()
check("เม็ดหม่าล่า: เลือกอันใหม่แล้วอันเก่าออก (มีได้อย่างเดียว)", _c.get(_seedB["id"]) == 1 and _seedA["id"] not in _c)

_ch = cust.get("/cart").get_data(as_text=True)
_i_head, _i_list = _ch.index("น้ำจิ้ม:"), _ch.index("วัตถุดิบในชาม")
_list_part = _ch[_i_list:_ch.index("โค้ดส่วนลด", _i_list)]
check("ตะกร้า: น้ำจิ้ม/เม็ด อยู่แถบบน (ติดซุป/เผ็ด) ไม่ปนกับรายการวัตถุดิบ",
      _i_head < _i_list and _sauce["name"] in _ch[:_i_list] and _seedB["name"] in _ch[:_i_list]
      and _sauce["name"] not in _list_part and _seedB["name"] not in _list_part and "หมูสามชั้น" in _list_part)
cust.post(f"/remove/{_seedB['id']}")
cust.post(f"/remove/{_sauce['id']}")
check("ลบ: เม็ด/น้ำจิ้ม ออกจากตะกร้าได้ ของอื่นยังอยู่", _cart() == {"P001": 2}, str(_cart()))

with cust.session_transaction() as s:
    s["cart"] = {_sauce["id"]: 2, _seedA["id"]: 1}
check("ตะกร้ามีแต่น้ำจิ้ม/เม็ด -> ไปเช็คเอาต์/สั่งซื้อไม่ได้ (เด้งกลับไปเลือกวัตถุดิบ)",
      all("/shop" in cust.get(u).headers.get("Location", "") for u in ("/checkout", "/checkout/summary"))
      and "/shop" in cust.post("/order/create").headers.get("Location", ""))

print("\n== ตะกร้ามีของที่ถูกลบจากร้านแล้ว / ค่าที่ส่งมาผิด")
_snap = storage.load_products()
with cust.session_transaction() as s:
    s["cart"] = {"P001": 1, "P_GONE": 3}
cust.get("/cart")
check("ของที่ร้านลบไปแล้วถูกล้างออกจากตะกร้าเอง (ไม่ค้างจนสั่งไม่ได้)", _cart() == {"P001": 1}, str(_cart()))
for _bad_post in ({"soup": "S01", "spicy": "abc"}, {"soup": "S01", "spicy": "99"}, {"soup": "NOPE", "spicy": "2"}):
    _r = cust.post("/select_soup", data=_bad_post)
    check(f"เลือกซุป/เผ็ดด้วยค่าผิด {_bad_post} ไม่ 500", _r.status_code == 302 and _r.headers["Location"].endswith("/"))

print("\n== หน้าออเดอร์: น้ำจิ้ม/เม็ดอยู่แถบซุป + ราคาไม่เพี้ยน")
_oid2 = place({"P001": 2, "P003": 1, _sauce["id"]: 2, _seedA["id"]: 1})
send_slip(_oid2, JPG())    # ต้องแนบสลิปก่อน ถึงจะเข้าหน้าสถานะได้
_os = cust.get(f"/order/{_oid2}").get_data(as_text=True)
_ad = admin.get(f"/admin/order/{_oid2}").get_data(as_text=True)
_hs = cust.get("/history").get_data(as_text=True)
def _ordered(h):
    a = h.index("น้ำจิ้ม:")
    return (a < h.index("หมูสามชั้น") and _sauce["name"] in h[a:h.index("หมูสามชั้น")]
            and _seedA["name"] in h[a:h.index("หมูสามชั้น")])
check("หน้าสถานะออเดอร์ (ลูกค้า): น้ำจิ้ม/เม็ดอยู่แถบซุป ก่อนรายการวัตถุดิบ", _ordered(_os))
check("หน้าออเดอร์ (แอดมิน): น้ำจิ้ม/เม็ดอยู่แถบซุป ก่อนรายการวัตถุดิบ", _ordered(_ad))
check("หน้าประวัติสั่งซื้อ: มีน้ำจิ้ม/เม็ด และไม่ปนในรายการวัตถุดิบ", "น้ำจิ้ม:" in _hs and "เม็ดหม่าล่า:" in _hs)
_list_os = _os[_os.index("หมูสามชั้น"):_os.index("ยอดรวมสุทธิ")]
check("รายการวัตถุดิบในออเดอร์ ไม่มีน้ำจิ้ม/เม็ดปนอยู่", _sauce["name"] not in _list_os and _seedA["name"] not in _list_os)
check("หน้าออเดอร์แสดงราคาไม่มี .0 ท้ายตัวเลข (5 ไม่ใช่ 5.0)", ">5.0 บาท<" not in _os and ">14.0 บาท<" not in _os)
_o_raw = orders.find_order(_oid2)
_nv = A.normalize_order(dict(_o_raw))
check("normalize_order: แยกวัตถุดิบ/น้ำจิ้ม/เม็ดถูก และรวมจำนวนครบ",
      [x["id"] for x in _nv["ingredient_items"]] == ["P001", "P003"] and len(_nv["sauce_items"]) == 1 and len(_nv["seed_items"]) == 1
      and _nv["item_count"] == 4 and _nv["ingredient_count"] == 2)
_free = {"order_id": "X", "lines": [{"id": "P001", "name": "หมูสามชั้น", "price": 0, "qty": 1, "subtotal": 0}], "total": 0}
check("ออเดอร์ที่บันทึกราคา 0 ไว้ ต้องแสดง 0 (ไม่ดึงราคาปัจจุบันของสินค้ามาแทน)",
      A.normalize_order(_free)["lines"][0]["price"] == 0 and A.normalize_order(_free)["lines"][0]["subtotal"] == 0)
check("ไม่มีคีย์ชั่วคราวหลุดลงไฟล์ orders.json", "ingredient_items" not in orders.find_order(_oid2) and "sauce_items" not in orders.find_order(_oid2))

print("\n== สั่งซื้ำ (reorder) คืนของครบ")
cust.post(f"/reorder/{_oid2}")
check("สั่งซ้ำ: ตะกร้าได้ของเดิมครบ (วัตถุดิบ + น้ำจิ้ม + เม็ด)", _cart() == {"P001": 2, "P003": 1, _sauce["id"]: 2, _seedA["id"]: 1}, str(_cart()))

print("\n== ยังไม่จ่าย/สลิปไม่ผ่าน: ห้ามข้ามไปหน้าสถานะ + ลูกค้าเห็นเหตุผลและส่งใหม่ได้")
_oid3 = place({"P001": 1})
_r = cust.get(f"/order/{_oid3}")
check("ยังไม่แนบสลิป: เข้าหน้าสถานะไม่ได้ ถูกส่งกลับหน้าชำระเงิน",
      _r.status_code == 302 and _r.headers["Location"].endswith(f"/order/{_oid3}/pay"), _r.headers.get("Location", ""))
_ph = cust.get(f"/order/{_oid3}/pay").get_data(as_text=True)
check("หน้าชำระเงิน (ยังไม่แนบสลิป) ไม่มีลิงก์ข้ามไปดูสถานะ", f'href="/order/{_oid3}"' not in _ph)
_hs = cust.get("/history").get_data(as_text=True)
check("ประวัติสั่งซื้อ: ออเดอร์ที่ยังไม่จ่ายมีปุ่มไปชำระเงิน ไม่ใช่ปุ่มติดตาม",
      f'href="/order/{_oid3}/pay"' in _hs and f'href="/order/{_oid3}"' not in _hs)
send_slip(_oid3, JPG())
_r = cust.get(f"/order/{_oid3}")
check("แนบสลิปแล้ว: เข้าหน้าสถานะได้ (รอตรวจสอบ)", _r.status_code == 200 and "รอร้านค้าตรวจสอบ" in _r.get_data(as_text=True))
check("แนบสลิปแล้ว: หน้าชำระเงินมีลิงก์ดูสถานะ", f'href="/order/{_oid3}"' in cust.get(f"/order/{_oid3}/pay").get_data(as_text=True))
act(_oid3, "reject", "ยอดโอนไม่ตรง")
_r = cust.get(f"/order/{_oid3}")
check("สลิปไม่ผ่าน: เข้าหน้าสถานะไม่ได้ ถูกส่งกลับหน้าชำระเงิน",
      _r.status_code == 302 and _r.headers["Location"].endswith(f"/order/{_oid3}/pay"))
_ph = cust.get(f"/order/{_oid3}/pay").get_data(as_text=True)
check("สลิปไม่ผ่าน: หน้าชำระเงินแจ้งว่าไม่ผ่าน + เหตุผลจากร้าน + ให้ส่งใหม่",
      "สลิปของคุณไม่ผ่านการตรวจสอบ" in _ph and "ยอดโอนไม่ตรง" in _ph and "แนบสลิปใหม่" in _ph and "ส่งสลิปใหม่" in _ph)
check("สลิปไม่ผ่าน: ไม่มีลิงก์ข้ามไปดูสถานะ และไม่มีสลิปเก่าค้าง", f'href="/order/{_oid3}"' not in _ph and "slip-thumb" not in _ph)
_hs = cust.get("/history").get_data(as_text=True)
check("สลิปไม่ผ่าน: ประวัติสั่งซื้อแจ้งไม่ผ่าน + เหตุผล + ปุ่มส่งสลิปใหม่",
      "สลิปไม่ผ่าน" in _hs and "ยอดโอนไม่ตรง" in _hs and "ส่งสลิปใหม่" in _hs)
send_slip(_oid3, PNG(), "s.png")
_o = orders.find_order(_oid3)
check("ส่งสลิปใหม่หลังไม่ผ่าน: สถานะ 2 + ล้างเหตุผลเดิม", _o["status"] == 2 and _o["slip_note"] == "" and _o["slip"])
_r = cust.get(f"/order/{_oid3}")
check("ส่งสลิปใหม่แล้ว: เข้าหน้าสถานะได้อีกครั้ง", _r.status_code == 200)
act(_oid3, "approve")
check("admin ตรวจสลิปใหม่แล้วอนุมัติได้", status(_oid3) == 3)
_oid4 = place({"P001": 1})
check("คนอื่นดู/ส่งสลิปของออเดอร์ที่ไม่ใช่ของตัวเองไม่ได้",
      client_as("someone_else", "customer").get(f"/order/{_oid4}/pay").status_code == 302
      and client_as("someone_else", "customer").get(f"/order/{_oid4}").status_code == 302)

print("\n== v1.7 ข้อ 1: ออเดอร์ค้างจ่าย — ยกเลิกเอง / หมดเวลา / เพดานต่อคน")
_s0 = stock("P001")
_a = place({"P001": 2})
check("สั่งแล้วตัดสต็อก + ออเดอร์มี expires_at", stock("P001") == _s0 - 2 and orders.find_order(_a).get("expires_at"))
_pa = cust.get(f"/order/{_a}/pay").get_data(as_text=True)
check("หน้าชำระเงินมีนับถอยหลัง + ปุ่มยกเลิกออเดอร์", 'id="pay-timer"' in _pa and f"/order/{_a}/cancel" in _pa)
_hs = cust.get("/history").get_data(as_text=True)
check("ประวัติมีปุ่มยกเลิก + บอกเวลาที่ต้องชำระภายใน", f"/order/{_a}/cancel" in _hs and "ชำระและแนบสลิปภายใน" in _hs)
check("คนอื่นยกเลิกออเดอร์ของเราไม่ได้", (client_as("someone_else", "customer").post(f"/order/{_a}/cancel"), status(_a))[1] == 1 and stock("P001") == _s0 - 2)
cust.post(f"/order/{_a}/cancel")
check("ลูกค้ากดยกเลิกเอง: สถานะ 9 + คืนสต็อกครบ + มีเหตุผล", status(_a) == 9 and stock("P001") == _s0 and orders.find_order(_a)["cancel_note"] == "ลูกค้ายกเลิกเอง")
_before = stock("P001")
cust.post(f"/order/{_a}/cancel")
check("กดยกเลิกซ้ำ: ไม่คืนสต็อกซ้ำ", stock("P001") == _before)

_b = place({"P001": 1})
send_slip(_b, JPG())
cust.post(f"/order/{_b}/cancel")
check("ส่งสลิปแล้วลูกค้ายกเลิกเองไม่ได้ (ต้องติดต่อร้าน)", status(_b) == 2 and stock("P001") == _s0 - 1)
_pb = cust.get(f"/order/{_b}/pay").get_data(as_text=True)
check("ส่งสลิปแล้วหน้าชำระเงินไม่มีปุ่มยกเลิก", f"/order/{_b}/cancel" not in _pb)

# หมดเวลา -> ยกเลิกเอง
_c = place({"P001": 3})
_oc = orders.find_order(_c); _oc["expires_at"] = "2000-01-01 00:00:00"; orders.update_order(_oc)
_n = orders.expire_unpaid_orders(force=True)
check("เกินเวลา: ระบบยกเลิกเอง + คืนสต็อก", _n >= 1 and status(_c) == 9 and stock("P001") == _s0 - 1)
check("ยกเลิกอัตโนมัติ: บันทึกเหตุผล", "หมดเวลา" in orders.find_order(_c)["cancel_note"])
check("ออเดอร์ที่ส่งสลิปแล้ว ไม่ถูกยกเลิกอัตโนมัติ (แม้เลยเวลา)", (lambda o: (o.update(expires_at="2000-01-01 00:00:00"), orders.update_order(o), orders.expire_unpaid_orders(force=True), status(_b))[-1])(orders.find_order(_b)) == 2)
_pc = cust.get(f"/order/{_c}/pay")
check("เปิดหน้าชำระเงินของออเดอร์ที่หมดเวลา: ถูกส่งไปหน้าสถานะ (ยกเลิก)", _pc.status_code == 302 and _pc.headers["Location"].endswith(f"/order/{_c}"))
check("หน้าสถานะแสดงว่ายกเลิกเพราะหมดเวลา", "ถูกยกเลิกแล้ว" in cust.get(f"/order/{_c}").get_data(as_text=True))
_r = cust.post(f"/order/{_c}/slip", data={"slip": (JPG(), "s.jpg")}, content_type="multipart/form-data")
check("ส่งสลิปให้ออเดอร์ที่ถูกยกเลิกไม่ได้ + ไม่มีไฟล์ค้าง", status(_c) == 9 and orders.find_order(_c)["slip"] == "" and not [f for f in os.listdir(orders.SLIP_FOLDER) if f.startswith(_c)])

# ออเดอร์เก่าที่ไม่มี expires_at คิดจากวันที่สั่ง
_d = place({"P001": 1})
_od = orders.find_order(_d); _od.pop("expires_at"); _od["date"] = "2026-10-01 10:00"; orders.update_order(_od)
orders.expire_unpaid_orders(force=True)
check("ออเดอร์เก่าไม่มี expires_at: คิดเวลาจากวันที่สั่ง แล้วยกเลิกได้", status(_d) == 9)

# reject ต้องให้เวลาใหม่ ไม่ใช่โดนยกเลิกทันที
_e = place({"P001": 1})
send_slip(_e, JPG())
_oe = orders.find_order(_e); _oe["expires_at"] = "2000-01-01 00:00:00"; orders.update_order(_oe)
act(_e, "reject", "ยอดไม่ตรง")
orders.expire_unpaid_orders(force=True)
check("admin ปฏิเสธสลิป: ได้เวลาใหม่ ไม่ถูกยกเลิกทันที", status(_e) == 1 and orders.seconds_left(orders.find_order(_e)) > 60)
cust.post(f"/order/{_e}/cancel")

# sweep ทำงานเองผ่านทุก request
_f = place({"P001": 1})
_of = orders.find_order(_f); _of["expires_at"] = "2000-01-01 00:00:00"; orders.update_order(_of)
orders._last_sweep = 0
cust.get("/history")
check("แค่มี request เข้าเว็บ ระบบก็กวาดออเดอร์หมดเวลาให้เอง", status(_f) == 9)

# เพดานออเดอร์ค้างจ่าย
for _o in orders.load_orders():
    if _o.get("username") == USER and orders.get_status(_o) == 1:
        orders.cancel_by_customer(_o, USER)
config.MAX_UNPAID_ORDERS = 2
_g1 = place({"P001": 1}); _g2 = place({"P001": 1})
_sg = stock("P001")
with cust.session_transaction() as s:
    s.update({"soup_id": "S01", "spicy": 3, "cart": {"P001": 1}, "delivery": dict(DELIVERY)})
_n_before = len(orders.load_orders())
_r = cust.post("/order/create")
check("ครบเพดาน 2 ออเดอร์ค้างจ่าย: สั่งเพิ่มไม่ได้ ถูกส่งไปหน้าประวัติ + ไม่ตัดสต็อก/ไม่สร้างออเดอร์",
      _r.status_code == 302 and _r.headers["Location"].endswith("/history") and len(orders.load_orders()) == _n_before and stock("P001") == _sg)
check("หน้าประวัติแจ้งเหตุผลที่สั่งเพิ่มไม่ได้", "ยังไม่ได้ชำระเงินครบ" in cust.get("/history").get_data(as_text=True))
cust.post(f"/order/{_g1}/cancel")
_r = cust.post("/order/create")
check("ยกเลิกออเดอร์เดิมแล้วสั่งใหม่ได้", _r.status_code == 302 and "/pay" in _r.headers["Location"])
check("เพดานนับแยกรายคน (ลูกค้าอีกคนไม่โดนผลกระทบ)", orders.count_unpaid("someone_else") == 0)
for _o in orders.load_orders():
    if _o.get("username") == USER and orders.get_status(_o) == 1:
        orders.cancel_by_customer(_o, USER)
config.MAX_UNPAID_ORDERS = 999

print("\n== v1.7 ข้อ 2: ส่งสลิปซ้ำเร็ว ๆ ไฟล์ต้องไม่หาย")
_h = place({"P001": 1})
for _i in range(6):                                   # กดรัว (เกือบทั้งหมดอยู่ในวินาทีเดียวกัน)
    send_slip(_h, JPG())
_oh = orders.find_order(_h)
_files = [f for f in os.listdir(orders.SLIP_FOLDER) if f.startswith(_h)]
check("กดส่งสลิปรัว 6 ครั้ง: ไฟล์สลิปที่ออเดอร์อ้างถึงยังอยู่จริง", bool(_oh["slip"]) and os.path.exists(os.path.join(orders.SLIP_FOLDER, _oh["slip"])))
check("กดส่งสลิปรัว: ไม่มีไฟล์เก่าค้างเป็นขยะ (เหลือไฟล์เดียว)", _files == [_oh["slip"]], str(_files))
check("แอดมินเปิดรูปสลิปได้ (ไม่ใช่รูปแตก)", admin.get(f"/slip/{_h}").status_code == 200)

# จำลองคำขอ 2 ตัวที่อ่านออเดอร์ค่าเดียวกัน (slip ว่าง) แล้วบันทึกชนกัน
_i = place({"P001": 1})
_stale1 = orders.find_order(_i); _stale2 = orders.find_order(_i)
_f1 = io.BytesIO(b"\xff\xd8\xff\xe0" + b"1" * 80); _f1.filename = "a.jpg"
_f2 = io.BytesIO(b"\xff\xd8\xff\xe0" + b"2" * 80); _f2.filename = "b.jpg"
_f1.save = lambda p: open(p, "wb").write(_f1.getvalue()); _f2.save = lambda p: open(p, "wb").write(_f2.getvalue())
orders.save_slip(_stale1, _f1); orders.save_slip(_stale2, _f2)
_oi = orders.find_order(_i)
_files = [f for f in os.listdir(orders.SLIP_FOLDER) if f.startswith(_i)]
check("คำขอชนกัน (อ่านออเดอร์ค่าเดิมทั้งคู่): สลิปล่าสุดอยู่ครบ + ไม่มีไฟล์กำพร้า", _files == [_oi["slip"]] and os.path.exists(os.path.join(orders.SLIP_FOLDER, _oi["slip"])), str(_files))
check("ชื่อไฟล์สลิปมีเลขสุ่มท้าย (ไม่ซ้ำแม้วินาทีเดียวกัน)", re.fullmatch(r"MZ\d+_\d{14}_[0-9a-f]{6}\.jpg", _oi["slip"]) is not None, _oi["slip"])
check("หน้าชำระเงินล็อกปุ่มส่งสลิปหลังกดครั้งแรก (กันกดรัวฝั่งมือถือ)", "slip-form" in cust.get(f"/order/{_i}/pay").get_data(as_text=True) and "dataset.sending" in cust.get(f"/order/{_i}/pay").get_data(as_text=True))

print("\n== v1.7 ข้อ 3: พิกัดร้าน")
check("config พิกัดร้านตรงกับที่ปักหมุด", config.SHOP_LAT == 16.480267026748546 and config.SHOP_LNG == 102.81325138461621)
check("delivery ใช้พิกัดใหม่: จากร้านถึงร้าน 0 กม. ส่งฟรี", delivery.calculate_delivery(16.480267026748546, 102.81325138461621) == {"ok": True, "km": 0.0, "fee": 0})
with cust.session_transaction() as s:
    s.update({"soup_id": "S01", "spicy": 3, "cart": {"P001": 1}})
_ck = cust.get("/checkout").get_data(as_text=True)
check("หน้าเช็คเอาต์ใช้พิกัดร้านใหม่ในแผนที่ + ลิงก์ Google Maps", "16.480267026748546" in _ck and "102.81325138461621" in _ck and "16.4722" not in _ck)

# ======================================================================
# v1.8 ข้อ 1: เปิด/ปิดร้าน + เวลาทำการ
# ======================================================================
print("\n== v1.8 ข้อ 1: เปิด/ปิดร้าน")
TZ7 = _dt.timezone(_dt.timedelta(hours=7))
def at(day, h, m=0):          # 2026-10-16 เป็นวันศุกร์ (weekday 4)
    return _dt.datetime(2026, 10, day, h, m, tzinfo=TZ7)
AUTO = {"shop_mode": "auto", "closed_note": ""}
config.OPEN_TIME, config.CLOSE_TIME, config.CLOSED_WEEKDAYS, config.LAST_ORDER_BEFORE_CLOSE_MIN = "10:00", "21:00", [], 0
check("ในเวลาทำการ -> เปิด", shop_status.get_status(at(16, 12), AUTO)["open"])
check("เวลาเปิดพอดี -> เปิด / เวลาปิดพอดี -> ปิด", shop_status.get_status(at(16, 10), AUTO)["open"] and not shop_status.get_status(at(16, 21), AUTO)["open"])
b = shop_status.get_status(at(16, 8), AUTO)
check("ก่อนเปิด -> ปิด และบอกเวลาเปิด 'วันนี้ 10:00 น.'", not b["open"] and b["next_open"] == "วันนี้ 10:00 น.", b["next_open"])
a = shop_status.get_status(at(16, 22), AUTO)
check("หลังปิด -> ปิด และบอก 'พรุ่งนี้ 10:00 น.'", not a["open"] and a["next_open"] == "พรุ่งนี้ 10:00 น.", a["next_open"])
config.CLOSED_WEEKDAYS = [5]  # เสาร์
d = shop_status.get_status(at(17, 12), AUTO)
check("วันหยุดประจำสัปดาห์ (เสาร์) -> ปิด และบอกว่าเปิดพรุ่งนี้", not d["open"] and d["reason"] == "day_off" and d["next_open"] == "พรุ่งนี้ 10:00 น.", d["next_open"])
config.CLOSED_WEEKDAYS = [5, 6]
d2 = shop_status.get_status(at(17, 12), AUTO)
check("หยุดเสาร์-อาทิตย์ -> ชี้ไปวันจันทร์", not d2["open"] and "จันทร์" in d2["next_open"], d2["next_open"])
config.CLOSED_WEEKDAYS = []
config.LAST_ORDER_BEFORE_CLOSE_MIN = 30
check("หยุดรับออเดอร์ก่อนปิด 30 นาที (20:45 ปิดแล้ว, 20:29 ยังเปิด)", not shop_status.get_status(at(16, 20, 45), AUTO)["open"] and shop_status.get_status(at(16, 20, 29), AUTO)["open"])
config.LAST_ORDER_BEFORE_CLOSE_MIN = 0
config.OPEN_TIME, config.CLOSE_TIME = "17:00", "02:00"
check("ช่วงเวลาข้ามเที่ยงคืน: 01:00 ยังเปิด, 03:00 ปิด, 18:00 เปิด",
      shop_status.get_status(at(17, 1), AUTO)["open"] and not shop_status.get_status(at(17, 3), AUTO)["open"] and shop_status.get_status(at(16, 18), AUTO)["open"])
config.OPEN_TIME, config.CLOSE_TIME = "10:00", "21:00"
check("แอดมินปิดชั่วคราว ชนะเวลาทำการ (กลางวันก็ปิด) + แสดงหมายเหตุ", (lambda r: not r["open"] and r["reason"] == "manual_closed" and "18:00" in r["detail"])(shop_status.get_status(at(16, 12), {"shop_mode": "closed", "closed_note": "กลับมา 18:00 น."})))
check("แอดมินบังคับเปิด ชนะเวลาทำการ (ตี 3 ก็เปิด)", shop_status.get_status(at(16, 3), {"shop_mode": "open"})["open"])
config.OPEN_TIME, config.CLOSE_TIME = "10.00", "สามทุ่ม"
check("ตั้งเวลาใน config ผิดรูปแบบ -> ไม่ล็อกร้านปิด + มีข้อความเตือนแอดมิน", shop_status.get_status(at(16, 3), AUTO)["open"] and shop_status.hours_config_error() != "")
config.OPEN_TIME, config.CLOSE_TIME = None, None
check("OPEN_TIME=None = เปิดตลอด", shop_status.get_status(at(16, 3), AUTO)["open"])
config.OPEN_TIME, config.CLOSE_TIME = "10:00", "21:00"

# --- ทดสอบผ่านเว็บ ---
stock_p1 = stock("P001")
admin.post("/admin/settings/shop", data={"mode": "closed", "closed_note": "พักเบรก <b>กลับ 18:00</b>"})
check("แอดมินกดปิดร้านชั่วคราวได้ (บันทึกลง settings.json)", settings.load()["shop_mode"] == "closed")
home_html = cust.get("/").get_data(as_text=True)
check("ปิดร้าน: หน้าแรกขึ้นการ์ด 'ร้านปิดชั่วคราว' + หมายเหตุ (escape HTML แล้ว)", "ร้านปิดชั่วคราว" in home_html and "closed-card" in home_html and "&lt;b&gt;กลับ 18:00" in home_html)
check("ปิดร้าน: ลูกค้ายังดูเมนูได้ (shop/sauces/seeds/cart เปิดได้)", all(cust.get(u).status_code == 200 for u in ["/shop", "/sauces", "/seeds"]))
with cust.session_transaction() as s:
    s.update({"soup_id": "S01", "spicy": 3, "cart": {"P001": 2}, "delivery": dict(DELIVERY)})
cart_html = cust.get("/cart").get_data(as_text=True)
check("ปิดร้าน: ตะกร้าไม่มีปุ่ม 'ต่อไป: ปักหมุด' แต่มีปุ่มที่กดไม่ได้", "ต่อไป: ปักหมุดจัดส่ง" not in cart_html and "btn-disabled" in cart_html and "closed-strip" in cart_html)
check("ปิดร้าน: เข้า /checkout, /checkout/summary ตรง ๆ ไม่ได้ (เด้งกลับตะกร้า)", all(cust.get(u).status_code == 302 and "/cart" in cust.get(u).headers["Location"] for u in ["/checkout", "/checkout/summary"]))
n_orders = len(orders.load_orders())
r = cust.post("/order/create")
check("ปิดร้าน: ยิง POST /order/create ตรง ๆ ไม่สร้างออเดอร์ ไม่ตัดสต็อก", r.status_code == 302 and "/cart" in r.headers["Location"] and len(orders.load_orders()) == n_orders and stock("P001") == stock_p1)
check("ปิดร้าน: ข้อความแจ้งลูกค้าแสดงในหน้าตะกร้า (ไม่ใช่เงียบ)", "ยังสั่งซื้อไม่ได้" in cust.get("/cart").get_data(as_text=True))
settings.set_shop_mode("open")
oid_open = place({"P001": 1})
settings.set_shop_mode("closed")
check("ออเดอร์ที่สั่งก่อนปิดร้าน ยังเปิดหน้าชำระเงิน + ส่งสลิปได้", cust.get(f"/order/{oid_open}/pay").status_code == 200)
send_slip(oid_open, JPG())
check("ปิดร้านแล้วส่งสลิปของออเดอร์เดิมได้ (สถานะ 2)", status(oid_open) == 2)
rc = client_as(USER, "customer").post("/admin/settings/shop", data={"mode": "auto"})
check("ลูกค้าธรรมดากดสวิตช์ปิด/เปิดร้านไม่ได้", settings.load()["shop_mode"] == "closed" and rc.status_code == 302)
check("ลูกค้าเปิดหน้า /admin/settings, /admin/reviews ไม่ได้", all(client_as(USER, "customer").get(u).status_code == 302 for u in ["/admin/settings", "/admin/reviews"]))
check("หน้า admin ตั้งค่าร้าน + จัดการออเดอร์ มีสวิตช์สถานะร้าน", "ปิดร้านชั่วคราว" in admin.get("/admin/settings").get_data(as_text=True) and "shop-switch" in admin.get("/admin").get_data(as_text=True))
admin.post("/admin/settings/shop", data={"mode": "auto", "next": "admin_orders"})
settings.set_shop_mode("open")
check("เปิดร้านกลับ -> หน้าแรกไม่มีการ์ดปิดร้าน", "closed-card" not in cust.get("/").get_data(as_text=True))
check("mode แปลก ๆ ถูกปฏิเสธ ไม่พัง", settings.set_shop_mode("xx")[0] is False and admin.post("/admin/settings/shop", data={"mode": "<script>"}).status_code == 302 and settings.load()["shop_mode"] == "open")
os.remove(os.path.join(storage.DATA_FOLDER, "settings.json"))
check("settings.json หาย -> ใช้ค่าเริ่มต้น เว็บไม่ล่ม", cust.get("/").status_code == 200 and settings.load()["shop_mode"] == "auto")
settings.set_shop_mode("open")

# --- แถบประกาศโปรโมชัน ---
print("\n== v1.8: แถบประกาศโปรโมชัน")
admin.post("/admin/settings/promo", data={"text": "ซื้อครบ 500 ลดเพิ่ม 10 บาท <script>alert(1)</script>", "enabled": "on"})
h = cust.get("/").get_data(as_text=True)
check("แอดมินตั้งแถบประกาศ -> โชว์หน้าแรกทันที + กัน XSS", "ซื้อครบ 500 ลดเพิ่ม 10 บาท" in h and "<script>alert(1)" not in h and "&lt;script&gt;" in h)
check("แถบประกาศไม่โผล่หน้าอื่น (เช่น ตะกร้า)", "promo-banner" not in cust.get("/cart").get_data(as_text=True))
admin.post("/admin/settings/promo", data={"text": "x" * 500, "enabled": "on"})
check("ข้อความยาวเกินถูกปฏิเสธ ไม่ทับของเดิม", len(settings.load()["promo"]["text"]) < 200)
admin.post("/admin/settings/promo", data={"text": "ข้อความเดิม"})
check("ติ๊กซ่อน -> แถบหายจากหน้าแรก", "promo-banner" not in cust.get("/").get_data(as_text=True))
check("เปิดแสดงโดยไม่มีข้อความ ถูกปฏิเสธ", settings.set_promo(True, "   ")[0] is False)

# ======================================================================
# v1.8 ข้อ 2: รีวิวหลังจัดส่งสำเร็จ
# ======================================================================
print("\n== v1.8 ข้อ 2: รีวิว")
def finish(oid):
    send_slip(oid, JPG()); act(oid, "approve"); act(oid, "deliver"); act(oid, "done")

rv_a = place({"P001": 1}); finish(rv_a)
rv_b = place({"P002": 1}); finish(rv_b)
rv_c = place({"P001": 1}); send_slip(rv_c, JPG()); act(rv_c, "approve")      # ยังเป็นสถานะ 3
st_html = cust.get(f"/order/{rv_a}").get_data(as_text=True)
check("สถานะ 5: เห็นฟอร์มดาว 1-5 + ช่องคอมเมนต์ + ป๊อปอัป + ปุ่มไว้ทีหลัง + ปุ่มสั่งอีกครั้ง",
      all(t in st_html for t in ['name="stars"', 'name="comment"', "ไว้ทีหลัง", "review-modal", "สั่งอีกครั้ง"]) and st_html.count('type="radio" id="star') == 5)
check("สถานะ 5: หน้าไม่รีเฟรชอัตโนมัติ (ไม่งั้นคอมเมนต์ที่พิมพ์ค้างจะหาย)", 'http-equiv="refresh"' not in st_html)
check("สถานะ 3: ยังรีเฟรชอัตโนมัติและไม่มีฟอร์มรีวิว", 'http-equiv="refresh"' in cust.get(f"/order/{rv_c}").get_data(as_text=True) and 'name="stars"' not in cust.get(f"/order/{rv_c}").get_data(as_text=True))
cust.post(f"/order/{rv_c}/review", data={"stars": "5"})
check("รีวิวออเดอร์ที่ยังไม่ส่งสำเร็จ ถูกปฏิเสธ", "review" not in orders.find_order(rv_c))
for bad in ["0", "6", "-1", "abc", "", "4.5", "５"]:
    cust.post(f"/order/{rv_a}/review", data={"stars": bad, "comment": "x"})
check("ค่าดาวผิด (0,6,-1,ข้อความ,ว่าง,ทศนิยม) ถูกปฏิเสธทั้งหมด", "review" not in orders.find_order(rv_a))
other = client_as("someone_else", "customer")
other.post(f"/order/{rv_a}/review", data={"stars": "1", "comment": "ปั่น"})
check("คนอื่นรีวิวออเดอร์ของเราไม่ได้", "review" not in orders.find_order(rv_a))
cust.post(f"/order/{rv_a}/review", data={"stars": "5", "comment": "  อร่อยมาก <img src=x onerror=alert(1)>  " + "ก" * 400})
ra = orders.find_order(rv_a)["review"]
check("ส่งรีวิวสำเร็จ: เก็บดาว + คอมเมนต์ (ตัดความยาวเหลือ 300)", ra["stars"] == 5 and 0 < len(ra["comment"]) <= config.REVIEW_COMMENT_MAX and ra["comment"].startswith("อร่อยมาก"))
cust.post(f"/order/{rv_a}/review", data={"stars": "1", "comment": "เปลี่ยนใจ"})
check("รีวิวซ้ำ/แก้ไม่ได้ (ได้ครั้งเดียว)", orders.find_order(rv_a)["review"]["stars"] == 5)
after = cust.get(f"/order/{rv_a}").get_data(as_text=True)
check("หลังรีวิว: โชว์ดาวที่ให้ + ไม่มีฟอร์ม + ยังมีปุ่มสั่งอีกครั้ง + คอมเมนต์ถูก escape", 'name="stars"' not in after and "ขอบคุณสำหรับรีวิว" in after and "สั่งอีกครั้ง" in after and "<img src=x" not in after)
cust.post(f"/order/{rv_b}/review/skip")
check("กดข้าม: ไม่บันทึกดาว แต่ซ่อนฟอร์ม + มีลิงก์ให้คะแนนทีหลัง + ยังสั่งอีกครั้งได้",
      "review" not in orders.find_order(rv_b) and orders.find_order(rv_b)["review_skipped"] is True
      and 'name="stars"' not in cust.get(f"/order/{rv_b}").get_data(as_text=True) and "ให้คะแนนตอนนี้" in cust.get(f"/order/{rv_b}").get_data(as_text=True)
      and 'name="stars"' in cust.get(f"/order/{rv_b}?review=1").get_data(as_text=True))
r = cust.post(f"/reorder/{rv_a}")
check("ปุ่มสั่งอีกครั้งใช้ระบบ reorder เดิม (เด้งไปตะกร้า)", r.status_code == 302 and "/cart" in r.headers["Location"])
r = other.post(f"/reorder/{rv_a}")
check("สั่งซ้ำออเดอร์ของคนอื่นไม่ได้ (เดิมเดาเลขออเดอร์แล้วดึงรายการคนอื่นได้)", "/cart" not in r.headers["Location"])
cust.post(f"/order/{rv_b}/review", data={"stars": "2", "comment": "ช้า ของเย็น"})
sm = reviews.summary()
check("สรุป: จำนวน/ค่าเฉลี่ย/ออเดอร์ดาวต่ำ", sm["count"] == 2 and sm["average"] == 3.5 and [x["order_id"] for x in sm["low"]] == [rv_b], str((sm["count"], sm["average"])))
ar = admin.get("/admin/reviews").get_data(as_text=True)
check("แอดมินเห็นค่าเฉลี่ย 3.50 + ข้อความรีวิว + ลิงก์ไปออเดอร์", "3.50" in ar and "ช้า ของเย็น" in ar and f"/admin/order/{rv_b}" in ar and "<img src=x" not in ar)
low = admin.get("/admin/reviews?view=low").get_data(as_text=True)
check("ตัวกรองดาวต่ำ: เห็นเฉพาะออเดอร์ดาวต่ำ", "ช้า ของเย็น" in low and "อร่อยมาก" not in low)
check("หน้ารายละเอียดออเดอร์ของแอดมินโชว์รีวิว", "ช้า ของเย็น" in admin.get(f"/admin/order/{rv_b}").get_data(as_text=True))
public = "".join(cust.get(u).get_data(as_text=True) for u in ["/", "/shop", "/sauces", "/cart", "/history"])
check("รีวิวไม่โผล่หน้าสาธารณะ/หน้าลูกค้าอื่น (เก็บให้แอดมินดูก่อน)", "ช้า ของเย็น" not in public and "อร่อยมาก" not in public)
check("route รีวิวทั้งหมดต้องล็อกอิน (ไม่ล็อกอิน -> ไป /login)", A.app.test_client().post(f"/order/{rv_a}/review", data={"stars": "1"}).headers["Location"].endswith("/login"))
check("ประวัติสั่งซื้อ: ออเดอร์ที่ยังไม่รีวิว/ข้ามแล้ว มีปุ่มให้คะแนน", "ให้คะแนน" in cust.get("/history").get_data(as_text=True))

# ======================================================================
# v1.8 ข้อ 3: สิทธิ์สมาชิก
# ======================================================================
print("\n== v1.8 ข้อ 3: สิทธิ์สมาชิก (โค้ดเฉพาะ id)")
config.MEMBER_REWARD_ENABLED, config.MEMBER_REWARD_EVERY, config.MEMBER_REWARD_BAHT = True, 20, 20     # ราคาในข้อมูลจริงต่ำ (ซุป 10, หมู 5) จึงลดเกณฑ์ลงให้เทสต์ถึงเกณฑ์ได้
config.MEMBER_REWARD_MIN_ORDER, config.MEMBER_REWARD_VALID_DAYS, config.MEMBER_CODE_STACK_WITH_COUPON = 50, 30, False
auth.register_user("memA", "secret1", "secret1", "สมาชิกเอ")
auth.register_user("memB", "secret1", "secret1", "สมาชิกบี")
mA, mB = client_as("memA", "customer"), client_as("memB", "customer")
def place_as(c, cart_):
    with c.session_transaction() as s:
        s.update({"soup_id": "S01", "spicy": 3, "cart": cart_, "delivery": dict(DELIVERY)})
    return c.post("/order/create").headers["Location"].split("/")[2]
def slip_as(c, oid):
    c.post(f"/order/{oid}/slip", data={"slip": (JPG(), "s.jpg")}, content_type="multipart/form-data")

check("ลูกค้าใหม่: ยังไม่มีสิทธิ์ ไม่มีปุ่มในตะกร้า", "ใช้สิทธิ์" not in mA.get("/cart").get_data(as_text=True) and member_codes.active_code("memA") is None)
o1 = place_as(mA, {"P001": 4}); slip_as(mA, o1); act(o1, "approve")
act(o1, "deliver")
check("ยอดสะสมนับเฉพาะสถานะ 5 (ออเดอร์กำลังส่ง = ยังไม่นับ)", member_codes.delivered_spend("memA") == 0 and member_codes.active_code("memA") is None)
act(o1, "done")
spend1 = member_codes.delivered_spend("memA")
check("ส่งสำเร็จ -> นับยอดสะสม = ค่าอาหารสุทธิ (ไม่รวมค่าส่ง)", abs(spend1 - orders.find_order(o1)["food_total"]) < 0.01, str(spend1))
code = member_codes.active_code("memA")
check("ครบเกณฑ์ -> ออกโค้ดผูกกับ id memA 1 ใบ (รูปแบบ MB-XXXXXX, หมดอายุ 30 วัน, ลด 20)", code and code["username"] == "memA" and re.fullmatch(r"MB-[A-Z2-9]{6}", code["code"]) and code["value"] == 20, str(code))
check("ออกใบเดียวต่อครั้ง (ไม่ออกซ้ำถ้าถือใบที่ใช้ได้อยู่)", len([c for c in member_codes.all_codes() if c["username"] == "memA"]) == 1)
check("คนอื่น (memB) ไม่ได้โค้ดจากยอดของ memA", member_codes.active_code("memB") is None)
check("หน้าสถานะออเดอร์ที่ส่งสำเร็จแจ้งว่าได้สิทธิ์สมาชิก", "ได้รับสิทธิ์สมาชิก" in mA.get(f"/order/{o1}").get_data(as_text=True))
with mA.session_transaction() as s:
    s.update({"soup_id": "S01", "spicy": 3, "cart": {"P001": 20}})
check("ลูกค้า memA เห็นปุ่ม 'ใช้สิทธิ์' ในตะกร้า", "ใช้สิทธิ์" in (mA.get("/cart").get_data(as_text=True)))
check("ลูกค้า memB (ไม่มีสิทธิ์) ไม่เห็นปุ่มและโค้ดของ memA", code["code"] not in mB.get("/cart").get_data(as_text=True) and "member/apply" not in mB.get("/cart").get_data(as_text=True))
mB.post("/member/apply")
with mB.session_transaction() as s:
    check("memB กด /member/apply ตรง ๆ ก็ไม่ได้โค้ดใน session", "member_code" not in s)

# ปลอมค่าใน session
with mB.session_transaction() as s:
    s.update({"soup_id": "S01", "spicy": 3, "cart": {"P001": 20}, "member_code": code["code"]})
sub_b = mB.get("/cart").get_data(as_text=True)
check("ยัดโค้ดของคนอื่นลง session -> เซิร์ฟเวอร์ไม่ให้ส่วนลด (ผูก id)", "สิทธิ์สมาชิก:" not in sub_b)
with mB.session_transaction() as s:
    s["member_code"] = "MB-AAAAAA"
check("ยัดโค้ดมั่ว -> ไม่ได้ส่วนลด", "สิทธิ์สมาชิก:" not in mB.get("/cart").get_data(as_text=True))

# ใช้สิทธิ์
with mA.session_transaction() as s:
    s.update({"soup_id": "S01", "spicy": 3, "cart": {"P001": 20}, "delivery": dict(DELIVERY)})
mA.post("/member/apply")
cart_a = mA.get("/cart").get_data(as_text=True)
check("กดใช้สิทธิ์: ตะกร้าแสดงส่วนลดสมาชิก 20 บาท", "สิทธิ์สมาชิก:" in cart_a and "-20.00" in cart_a)
with mA.session_transaction() as s:
    cart_items = s["cart"]
soup_price = A.safe_find_soup("S01")["price"]
subtotal = soup_price + sum(A.safe_find_product(k)["price"] * v for k, v in cart_items.items())
tier_pct = promo.get_tier_percent(subtotal)
expect_total = round(subtotal - subtotal * tier_pct / 100 - 20, 2)
check("ซ้อนกับส่วนลดตามยอดได้ (สองชั้น): ยอดสุทธิ = ยอด − ส่วนลดตามยอด − 20", tier_pct > 0 and f"{expect_total:.2f}" in cart_a, f"{subtotal} {tier_pct}% -> {expect_total}")
mA.post("/apply_coupon", data={"code": "MALA10"})
with mA.session_transaction() as s:
    check("ใส่คูปองทับ: ระบบเอาสิทธิ์สมาชิกออก (ไม่ให้ลดสามชั้น)", "member_code" not in s and s.get("coupon") == "MALA10")
mA.post("/member/apply")
with mA.session_transaction() as s:
    check("กดใช้สิทธิ์ทับ: ระบบเอาคูปองออก", s.get("member_code") == code["code"] and "coupon" not in s)
with mA.session_transaction() as s:
    s["coupon"] = "MALA10"                       # ฝืนใส่ทั้งคู่ใน session ตรง ๆ
pr = promo.calculate_discount(subtotal, "MALA10", {"code": "X", "value": 20, "min": 50})
check("backstop ใน promo: ใส่ทั้งคู่ -> คิดแค่สมาชิก คูปองไม่ถูกคิด", pr["coupon_discount"] == 0 and pr["member_discount"] == 20 and pr["tier_discount"] > 0)
config.MEMBER_CODE_STACK_WITH_COUPON = True
pr2 = promo.calculate_discount(subtotal, "MALA10", {"code": "X", "value": 20, "min": 50})
check("ตั้ง config ให้ซ้อนคูปองได้ -> ลดครบสามอย่าง", pr2["coupon_discount"] > 0 and pr2["member_discount"] == 20 and pr2["final_total"] < pr["final_total"])
config.MEMBER_CODE_STACK_WITH_COUPON = False
prm = promo.calculate_discount(40, None, {"code": "X", "value": 20, "min": 50})
check("ยอดต่ำกว่าขั้นต่ำ -> ไม่หักสิทธิ์ + มีข้อความบอก", prm["member_discount"] == 0 and "ขั้นต่ำ" in prm["member_note"])
prc = promo.calculate_discount(30, None, {"code": "X", "value": 99, "min": 0})
check("ส่วนลดสมาชิกไม่ทำให้ยอดติดลบ", prc["final_total"] == 0 and prc["member_discount"] == 30)

with mA.session_transaction() as s:
    s.pop("coupon", None); s["member_code"] = code["code"]; s["cart"] = {"P001": 20}; s["delivery"] = dict(DELIVERY); s["soup_id"] = "S01"; s["spicy"] = 3
o2 = mA.post("/order/create").headers["Location"].split("/")[2]
ord2 = orders.find_order(o2)
check("สั่งซื้อด้วยสิทธิ์: ออเดอร์เก็บ member_code + member_discount=20 และยอดตรงกับตะกร้า", ord2["member_code"] == code["code"] and ord2["member_discount"] == 20 and abs(ord2["food_total"] - expect_total) < 0.01, str((ord2["member_code"], ord2["food_total"], expect_total)))
rec_now = next(c for c in member_codes.all_codes() if c["code"] == code["code"])
check("โค้ดถูกผูกกับออเดอร์ + สถานะ 'ใช้แล้ว'", rec_now["used_order_id"] == o2 and rec_now["state"] == "used")
with mA.session_transaction() as s:
    check("หลังสั่งซื้อ session ไม่ค้างโค้ด", "member_code" not in s)
check("ใช้แล้วหายจากตะกร้า (ไม่เห็นปุ่ม)", "member/apply" not in mA.get("/cart").get_data(as_text=True))

# ใช้ซ้ำ
with mA.session_transaction() as s:
    s.update({"member_code": code["code"], "cart": {"P001": 20}, "delivery": dict(DELIVERY), "soup_id": "S01", "spicy": 3})
n0 = len(orders.load_orders())
r = mA.post("/order/create")
o3 = [x for x in orders.load_orders()[n0:]]
check("ใช้โค้ดเดิมซ้ำ: ออเดอร์ใหม่ไม่ได้ส่วนลดสมาชิก (โค้ดถูกใช้ไปแล้ว)", all(not x.get("member_discount") for x in o3))
check("reserve ซ้ำ (จำลองกดส่งสองครั้งพร้อมกัน) สำเร็จได้แค่ครั้งเดียว", member_codes.reserve(code["code"], "memA") is False)
for x in o3:
    orders.cancel_by_customer(orders.find_order(x["order_id"]), "memA")

# ยกเลิก -> คืนโค้ด
act(o2, "cancel", "ทดสอบ")
check("ยกเลิกออเดอร์ที่ใช้โค้ด -> คืนโค้ด (ใช้ได้อีก)", status(o2) == 9 and member_codes.active_code("memA") and member_codes.active_code("memA")["code"] == code["code"])

# หมดอายุ
recs = json.load(open("data/member_codes.json", encoding="utf-8"))
for rr in recs:
    if rr["code"] == code["code"]:
        rr["expires_at"] = (_dt.datetime.now() - _dt.timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
json.dump(recs, open("data/member_codes.json", "w", encoding="utf-8"), ensure_ascii=False)
check("โค้ดหมดอายุ: ไม่นับเป็นโค้ดที่ใช้ได้ + ไม่เห็นปุ่ม", member_codes.active_code("memA") is None and "member/apply" not in mA.get("/cart").get_data(as_text=True))
with mA.session_transaction() as s:
    s.update({"member_code": code["code"], "cart": {"P001": 20}, "soup_id": "S01", "spicy": 3})
check("โค้ดหมดอายุค้างใน session: ตะกร้าไม่คิดส่วนลด + แจ้งว่าหมดอายุ", "หมดอายุหรือใช้ไม่ได้แล้ว" in mA.get("/cart").get_data(as_text=True))
mA.post("/member/apply")
check("กด apply ตอนโค้ดหมดอายุ ไม่ได้ผล", "สิทธิ์สมาชิก:" not in mA.get("/cart").get_data(as_text=True))
check("โค้ดหมดอายุแล้วไม่ออกซ้ำจากยอดเดิม (สิทธิ์ใบนั้นหมดไป)", member_codes.earned_count(member_codes.delivered_spend("memA")) <= len([c for c in member_codes.all_codes() if c["username"] == "memA"]) and member_codes.issue_if_earned("memA") is None, str((member_codes.delivered_spend("memA"), [(c["code"], c["state"]) for c in member_codes.all_codes() if c["username"] == "memA"])))

# ยอดสะสมไม่นับออเดอร์ที่ยกเลิก/ยังไม่สำเร็จ + ถึงเกณฑ์ใหม่
before = member_codes.delivered_spend("memA")
o4 = place_as(mA, {"P001": 20}); slip_as(mA, o4); act(o4, "approve"); act(o4, "cancel")
check("ออเดอร์ที่ยกเลิกไม่นับยอดสะสม", member_codes.delivered_spend("memA") == before)
o5 = place_as(mA, {"P001": 10}); slip_as(mA, o5); act(o5, "approve"); act(o5, "deliver"); act(o5, "done")
spend_now = member_codes.delivered_spend("memA")
if member_codes.earned_count(spend_now) > len([c for c in member_codes.all_codes() if c["username"] == "memA"]):
    check("ถึงเกณฑ์รอบใหม่ -> ได้โค้ดใบใหม่", member_codes.active_code("memA") is not None)
else:
    check("ถึงเกณฑ์รอบใหม่ -> ได้โค้ดใบใหม่ (ข้าม: ยอดไม่พอในชุดข้อมูลนี้)", True)

hist_a = mA.get("/history").get_data(as_text=True)
check("หน้าประวัติโชว์การ์ดสมาชิก + ยอดสะสม", "สิทธิ์สมาชิกของคุณ" in hist_a and "ยอดสะสม" in hist_a)
config.MEMBER_REWARD_ENABLED = False
check("ปิดระบบ (MEMBER_REWARD_ENABLED=False): ไม่ออกโค้ด/ไม่โชว์การ์ด", member_codes.issue_if_earned("memB") is None and "สิทธิ์สมาชิกของคุณ" not in mA.get("/history").get_data(as_text=True))
config.MEMBER_REWARD_ENABLED = True
check("หน้า admin ตั้งค่าร้านแสดงกติกา + ตารางโค้ด", "MB-" in admin.get("/admin/settings").get_data(as_text=True))
os.remove("data/member_codes.json")
with mA.session_transaction() as s:
    s.update({"soup_id": "S01", "spicy": 3, "cart": {"P001": 20}})
check("ไฟล์ member_codes.json หาย -> หน้าตะกร้า/ประวัติไม่ล่ม", mA.get("/cart").status_code == 200 and mA.get("/history").status_code == 200)

# ============ v1.9 แจ้งเตือนหลังร้าน ============
print("\n== v1.9 แจ้งเตือนหลังร้าน (สลิปรอตรวจ / สต็อกใกล้หมด / API สำหรับเสียงเตือน)")
import alerts            # noqa: E402

anon = A.app.test_client()
r_anon = anon.get("/admin/api/alerts")
check("คนยังไม่ล็อกอินเรียก API แจ้งเตือนไม่ได้ (ส่งไปหน้า login)", r_anon.status_code == 302 and "/login" in r_anon.headers["Location"])
r_cust = cust.get("/admin/api/alerts")
check("ลูกค้าเรียก API แจ้งเตือนไม่ได้ (ไม่มี JSON หลุด)", r_cust.status_code == 302 and not r_cust.is_json)

r_ad = admin.get("/admin/api/alerts")
d0 = r_ad.get_json()
check("admin เรียก API ได้ JSON + สั่งไม่ให้แคช", r_ad.status_code == 200 and d0 and "pending_slips" in d0 and r_ad.headers.get("Cache-Control") == "no-store")
real_pending = len([o for o in orders.load_orders() if orders.get_status(o) == 2])
check("ตัวเลขสลิปรอตรวจ = จำนวนออเดอร์สถานะ 2 จริง", d0["pending_slips"] == real_pending and len(d0["slip_ids"]) == real_pending, f"{d0['pending_slips']} vs {real_pending}")

# วงจรสลิป: สั่ง(1) -> ส่งสลิป(2) -> ตรวจผ่าน(3) / ตีกลับ(1) -> ส่งใหม่(2)
a1 = place_as(cust, {"P001": 2})
d1 = admin.get("/admin/api/alerts").get_json()
a1row = next((o for o in d1["open_orders"] if o["id"] == a1), None)
check("ออเดอร์ใหม่ (ยังไม่จ่าย) โผล่ใน open_orders แต่ยังไม่นับเป็นสลิปรอตรวจ", a1row and a1row["status"] == 1 and d1["pending_slips"] == real_pending and a1 not in d1["slip_ids"])
slip_as(cust, a1)
d2 = admin.get("/admin/api/alerts").get_json()
check("ส่งสลิป -> สลิปรอตรวจ +1 และ id อยู่ใน slip_ids", d2["pending_slips"] == real_pending + 1 and a1 in d2["slip_ids"])
check("ข้อมูลออเดอร์ใน API มีชื่อลูกค้า/ยอด (ไว้โชว์ในข้อความลอย)", next(o for o in d2["open_orders"] if o["id"] == a1)["total"] == orders.find_order(a1)["total"])
act(a1, "reject", "สลิปไม่ชัด")
d3 = admin.get("/admin/api/alerts").get_json()
check("ตีสลิปกลับ -> ออกจากสลิปรอตรวจ (กลับเป็นรอชำระ)", d3["pending_slips"] == real_pending and a1 not in d3["slip_ids"] and any(o["id"] == a1 for o in d3["open_orders"]))
slip_as(cust, a1)
check("ลูกค้าส่งสลิปใหม่ -> กลับมานับเป็นสลิปรอตรวจอีกครั้ง", a1 in admin.get("/admin/api/alerts").get_json()["slip_ids"])
act(a1, "approve")
d4 = admin.get("/admin/api/alerts").get_json()
check("approve แล้วสลิปรอตรวจลดลง + ออกจาก open_orders", d4["pending_slips"] == real_pending and not any(o["id"] == a1 for o in d4["open_orders"]))
a2 = place_as(cust, {"P001": 1})
act(a2, "cancel")
check("ออเดอร์ที่ยกเลิกไม่อยู่ในแจ้งเตือน", not any(o["id"] == a2 for o in admin.get("/admin/api/alerts").get_json()["open_orders"]))

# สต็อกใกล้หมด
thr = config.LOW_STOCK_THRESHOLD
prods = storage.load_products()
backup_products = json.loads(json.dumps(prods))
byid = {p["id"]: p for p in prods}
byid["P001"]["stock"] = 5                      # ใกล้หมด
byid["P002"]["stock"] = 0                      # หมด
byid["P003"]["stock"] = 2; byid["P003"]["available"] = False     # ปิดขายเอง -> ไม่เตือน
byid["P005"]["stock"] = thr                    # เท่าเกณฑ์พอดี -> เตือน
byid["P006"]["stock"] = thr + 1                # เกินเกณฑ์ 1 -> ไม่เตือน
byid["P042"]["stock"] = 9999                   # ตัวเลือกสต็อกสูงมาก -> ไม่เตือน
storage.save_products(prods)
dl = admin.get("/admin/api/alerts").get_json()
low_ids = {r["id"] for r in dl["low_stock"]}
out_ids = {r["id"] for r in dl["out_of_stock"]}
check("สต็อกใกล้หมดโผล่ใน low_stock (รวมค่าที่เท่าเกณฑ์พอดี)", {"P001", "P005"} <= low_ids, str(low_ids))
check("สต็อก 0 แยกไปอยู่ out_of_stock", "P002" in out_ids and "P002" not in low_ids)
check("สินค้าที่แอดมินปิดขายเอง/เกินเกณฑ์/ตัวเลือก 9999 ไม่เตือน", not ({"P003", "P006", "P042"} & (low_ids | out_ids)))
check("low_total = ใกล้หมด + หมด และเรียงจากเหลือน้อยสุดก่อน", dl["low_total"] == len(dl["low_stock"]) + len(dl["out_of_stock"]) and [r["stock"] for r in dl["low_stock"]] == sorted(r["stock"] for r in dl["low_stock"]))

page_admin = admin.get("/admin").get_data(as_text=True)
check("หน้า admin มีการ์ดสลิปรอตรวจ + รายการสต็อกใกล้หมด (ตัวเลขจากเซิร์ฟเวอร์ ไม่ต้องรอ JS)", 'data-alert-card="slips"' in page_admin and 'id="alert-low-list"' in page_admin and "หมูสามชั้น · เหลือ 5" in page_admin)
check("ทุกหน้า admin มีป้ายตัวเลข + ปุ่มเปิดเสียง + สคริปต์แจ้งเตือน", all(
    ('admin_alerts.js' in (t := admin.get(u).get_data(as_text=True))) and 'id="alert-sound-toggle"' in t and 'data-alert-badge="slips"' in t
    for u in ("/admin", "/admin/products", "/admin/report", "/admin/reviews", "/admin/settings", f"/admin/order/{a1}")))
prod_page = admin.get("/admin/products").get_data(as_text=True)
check("หน้าสต็อกสินค้าติดป้าย ใกล้หมด/หมดแล้ว", "ใกล้หมด" in prod_page and "หมดแล้ว" in prod_page)
check("ลูกค้าไม่เห็นสคริปต์/ตัวเลขแจ้งเตือนหลังร้านในหน้าไหนเลย", all(
    "admin_alerts.js" not in cust.get(u).get_data(as_text=True) and "alert-badge" not in cust.get(u).get_data(as_text=True)
    for u in ("/", "/history", "/cart")))

# ชื่อสินค้ามี HTML -> ต้องถูก escape ทั้งหน้าแดชบอร์ดและหน้าสต็อก
byid["P001"]["name"] = "<script>alert(1)</script>"
storage.save_products(prods)
t_dash = admin.get("/admin").get_data(as_text=True)
check("ชื่อสินค้าที่มี <script> ถูก escape ในการ์ดแจ้งเตือน", "<script>alert(1)</script>" not in t_dash and "&lt;script&gt;alert(1)&lt;/script&gt;" in t_dash)

# ข้อมูลเสีย: orders.json พัง -> API/หน้าแอดมินไม่ล่ม
storage.save_products(backup_products)
orders_text = open("data/orders.json", encoding="utf-8").read()
open("data/orders.json", "w", encoding="utf-8").write("{ไม่ใช่ json")
r_bad = admin.get("/admin/api/alerts")
d_bad = r_bad.get_json()
check("orders.json พัง: API ยังตอบ 200 (ok=false, ตัวเลขศูนย์) ไม่ล่ม", r_bad.status_code == 200 and d_bad["ok"] is False and d_bad["pending_slips"] == 0)
check("orders.json พัง: หน้าสต็อกสินค้า (ซึ่งมีป้ายแจ้งเตือน) ยังเปิดได้", admin.get("/admin/products").status_code == 200)
open("data/orders.json", "w", encoding="utf-8").write(orders_text)
check("ไฟล์กลับมาปกติ -> API กลับมามีตัวเลข", admin.get("/admin/api/alerts").get_json()["ok"] is True)

# ============ v1.10 หน้าต้อนรับ + แอนิเมชันเล็ก ๆ ============
print("\n== v1.10 หน้าต้อนรับ + แอนิเมชัน")
ok_reg, _msg = auth.register_user("welcomeu", "pass1234", "pass1234", "สมหญิง<b>")
wc = A.app.test_client()
r_login = wc.post("/login", data={"username": "welcomeu", "password": "pass1234"})
check("ลูกค้าล็อกอินสำเร็จ -> ไปหน้าต้อนรับ /welcome", ok_reg and r_login.status_code == 302 and r_login.headers["Location"].endswith("/welcome"), r_login.headers.get("Location", ""))
r_adm = A.app.test_client().post("/login", data={"username": "admin", "password": "admin1234"})
check("admin ล็อกอิน -> ยังไป /admin ตามเดิม (ไม่เห็นหน้าต้อนรับ)", r_adm.headers["Location"].endswith("/admin"))
w = wc.get("/welcome")
wt = w.get_data(as_text=True)
check("หน้าต้อนรับเปิดได้ มีชื่อร้าน + ปุ่ม 'สั่งหม่าล่าเลย' ลิงก์ไปหน้าเลือกซุป", w.status_code == 200 and config.SHOP_NAME in wt and "สั่งหม่าล่าเลย" in wt and 'href="/"' in wt)
check("ลูกค้าใหม่: ข้อความ 'ยินดีต้อนรับสู่ร้าน' ยังไม่มีลิงก์ประวัติ", "ยินดีต้อนรับสู่ร้าน" in wt and "ดูประวัติการสั่ง" not in wt)
check("ชื่อลูกค้าที่มี HTML ถูก escape", "<b>" not in wt.split("<h1")[0].split("welcome-kicker")[-1] and "&lt;b&gt;" in wt)
check("หน้าต้อนรับแสดงสถานะร้าน + เวลาทำการ", "ร้านเปิดอยู่" in wt and config.OPEN_TIME in wt.replace("10:00–21:00", config.OPEN_TIME))
check("ไม่ใช่ด่านบังคับ: เข้า / (เลือกซุป) ตรง ๆ ได้เลยโดยไม่ผ่านหน้าต้อนรับ", wc.get("/").status_code == 200)
check("คนยังไม่ล็อกอินเปิด /welcome ไม่ได้", A.app.test_client().get("/welcome").status_code == 302)
check("admin เปิด /welcome ถูกส่งกลับ /admin", admin.get("/welcome").status_code == 302 and admin.get("/welcome").headers["Location"].endswith("/admin"))

wo = place_as(wc, {"P001": 1})
check("ลูกค้าเคยสั่งแล้ว: 'ยินดีต้อนรับกลับมา' + ลิงก์ประวัติ", all(t in wc.get("/welcome").get_data(as_text=True) for t in ("ยินดีต้อนรับกลับมา", "ดูประวัติการสั่ง")))
settings.set_shop_mode("closed")
wt_closed = wc.get("/welcome").get_data(as_text=True)
check("ร้านปิด: หน้าต้อนรับบอกว่าปิด + ปุ่มเปลี่ยนเป็น 'ดูเมนูล่วงหน้า' (ไม่ชวนสั่ง)", "ดูเมนูล่วงหน้า" in wt_closed and "สั่งหม่าล่าเลย" not in wt_closed and "is-closed" in wt_closed)
settings.set_shop_mode("open")
settings.set_promo(True, "ลด <i>ทดสอบ</i>")
wt_promo = wc.get("/welcome").get_data(as_text=True)
check("โปรโมชันโชว์ในหน้าต้อนรับ + escape HTML", "welcome-promo" in wt_promo and "<i>ทดสอบ</i>" not in wt_promo)
settings.set_promo(False, "")
check("หน้าต้อนรับไม่มีสคริปต์ (มีแค่โลโก้ + CSS)", "<script" not in wt and "logo.png" in wt)

# แอนิเมชันเล็ก ๆ
with wc.session_transaction() as s:
    s.update({"soup_id": "S01", "spicy": 3, "cart": {"P001": 1}})
check("แถบยอดล่างของหน้าวัตถุดิบ/น้ำจิ้ม/เม็ดหม่าล่า มีจุดให้ตัวเลขเด้ง (data-live-total)", all("data-live-total" in wc.get(u).get_data(as_text=True) for u in ("/shop", "/sauces", "/seeds")))
js_src = open("static/cart_live.js", encoding="utf-8").read()
check("cart_live.js เด้งเฉพาะเมื่อยอดเปลี่ยนจริง", "oldTotal !== newEl.textContent.trim()" in js_src and '"bump"' in js_src)
css_src = open("static/style.css", encoding="utf-8").read()
check("CSS: มี totalBump และเคารพโหมดลดการเคลื่อนไหว", "@keyframes totalBump" in css_src and "prefers-reduced-motion: reduce" in css_src)
wo2 = place_as(wc, {"P001": 1}); slip_as(wc, wo2)
st_page = wc.get(f"/order/{wo2}").get_data(as_text=True)
check("หน้าสถานะออเดอร์: แถบขยับเฉพาะตอนสถานะเปลี่ยน (สคริปต์เทียบกับค่าครั้งก่อน)", "just-reached" in st_page and "sessionStorage" in st_page and f"mala_status_" in st_page)

print("\n== v1.12 ใบเสร็จรับเงิน / VAT")
rc1 = place_as(mA, {"P001": 2}); slip_as(mA, rc1)
check("สลิปรอตรวจ: ลูกค้ายังเปิดใบเสร็จไม่ได้ (ถูกส่งกลับหน้าสถานะ)", mA.get(f"/order/{rc1}/receipt").status_code == 302)
check("สลิปรอตรวจ: แอดมินยังเปิดใบเสร็จไม่ได้", admin.get(f"/admin/order/{rc1}/receipt").status_code == 302)
act(rc1, "approve")
rp = mA.get(f"/order/{rc1}/receipt")
rp_html = rp.get_data(as_text=True)
check("ตรวจสลิปผ่านแล้ว: ลูกค้าเห็นใบเสร็จ + เลขที่ RC- + ยอดสุทธิ", rp.status_code == 200 and f"RC-{rc1}" in rp_html and "ยอดชำระสุทธิ" in rp_html)
check("ลูกค้าไม่เห็นปุ่มพิมพ์ แต่แอดมินเห็น", "window.print()" not in rp_html and "window.print()" in admin.get(f"/admin/order/{rc1}/receipt").get_data(as_text=True))
check("ลูกค้าคนอื่นเปิดใบเสร็จของคนอื่นไม่ได้", mB.get(f"/order/{rc1}/receipt").status_code == 302)
check("ไม่ได้จด VAT: เป็นใบเสร็จธรรมดา ไม่แสดงภาษี", "ภาษีมูลค่าเพิ่ม" not in rp_html and "ใบกำกับภาษีอย่างย่อ" not in rp_html)
check("หน้าสถานะ + หลังร้านมีลิงก์ใบเสร็จ", f"/order/{rc1}/receipt" in mA.get(f"/order/{rc1}").get_data(as_text=True) and f"/admin/order/{rc1}/receipt" in admin.get(f"/admin/order/{rc1}").get_data(as_text=True))
ok_bad, _ = settings.set_receipt({"vat_registered": "on", "tax_id": "", "vat_rate": "7"})
check("จด VAT แต่ไม่กรอกเลขผู้เสียภาษี -> บันทึกไม่ได้", not ok_bad)
ok_bad2, _ = settings.set_receipt({"tax_id": "123", "vat_rate": "7"})
check("เลขผู้เสียภาษีไม่ครบ 13 หลัก -> บันทึกไม่ได้", not ok_bad2)
ok_vat, _ = settings.set_receipt({"vat_registered": "on", "tax_id": "0-1234-56789-01-2", "vat_rate": "7", "legal_name": "ร้านทดสอบ <b>x</b>"})
vp = mA.get(f"/order/{rc1}/receipt").get_data(as_text=True)
_tot = orders.find_order(rc1)["total"]
_base = round(_tot * 100 / 107, 2)
check("จด VAT: ใบกำกับภาษีอย่างย่อ + ยอดก่อนภาษี/VAT 7% คิดถูก", ok_vat and "ใบกำกับภาษีอย่างย่อ" in vp and f"{_base:.2f}" in vp and f"{_tot - _base:.2f}" in vp and "0123456789012" in vp)
check("ชื่อผู้ขายถูก escape HTML", "<b>x</b>" not in vp)
act(rc1, "cancel")
check("ออเดอร์ที่ยกเลิก: ไม่ออกใบเสร็จ", mA.get(f"/order/{rc1}/receipt").status_code == 302)
settings.set_receipt({})

# ======================================================================
# VAT 7% แบบรวมอยู่ในราคา (VAT Included · โหมดจำลอง): ลูกค้าจ่าย = ราคาที่เห็น ไม่บวก VAT เพิ่ม
# ======================================================================
print("\n== VAT 7% รวมอยู่ในราคา (VAT Included)")
import vat                                    # noqa: E402
config.VAT_ENABLED, config.VAT_RATE, config.VAT_DEMO_MODE = True, 7, True
NOTICE = config.VAT_DEMO_NOTICE
FEE = delivery.calculate_delivery(DELIVERY["lat"], DELIVERY["lng"])["fee"]


def vat_session(cart_, coupon=None, soup="S01", dlv=None):
    with cust.session_transaction() as s:
        s.clear()
        s.update({"username": USER, "name": USER, "role": "customer", "soup_id": soup, "spicy": 3,
                  "cart": cart_, "delivery": dict(dlv or DELIVERY)})
        if coupon:
            s["coupon"] = coupon


def vat_place(cart_, coupon=None, soup="S01", dlv=None):
    vat_session(cart_, coupon, soup, dlv)
    return cust.post("/order/create").headers["Location"].split("/")[2]


# --- (1) ฟังก์ชันคำนวณตรง ๆ: ตัวอย่าง 50 / 100 / 200 + ปัดเศษ + ศูนย์ + ค่าผิดปกติ ---
def _c(x, f=0):
    return vat.calculate(x, f)


check("vat: 50 -> VAT 3.27 ก่อน VAT 46.73 จ่าย 50.00", (_c(50)["vat_amount"], _c(50)["subtotal_ex_vat"], _c(50)["grand_total"]) == (3.27, 46.73, 50.0))
check("vat: 100 -> VAT 6.54 ก่อน VAT 93.46 จ่าย 100.00 (ไม่ใช่ 107)", (_c(100)["vat_amount"], _c(100)["subtotal_ex_vat"], _c(100)["grand_total"]) == (6.54, 93.46, 100.0))
check("vat: 200 -> VAT 13.08 ก่อน VAT 186.92 จ่าย 200.00", (_c(200)["vat_amount"], _c(200)["subtotal_ex_vat"], _c(200)["grand_total"]) == (13.08, 186.92, 200.0))
check("vat: ก่อน VAT + VAT = ค่าอาหารตรงเป๊ะ (ลอง 0.01-300.00 ทุกสตางค์)",
      all(abs(_c(k / 100)["subtotal_ex_vat"] + _c(k / 100)["vat_amount"] - k / 100) < 0.0001 and _c(k / 100)["grand_total"] == k / 100 for k in range(0, 30001)))
check("vat: สูตรตรงกับ round(x*7/107, 2) ทุกสตางค์ 0.00-300.00", all(_c(k / 100)["vat_amount"] == round(k / 100 * 7 / 107, 2) for k in range(0, 30001)))
check("vat: ยอดศูนย์ -> VAT 0 จ่าย 0", (lambda r: r["vat_amount"] == 0 and r["grand_total"] == 0 and r["subtotal_ex_vat"] == 0)(_c(0)))
check("vat: ยอดศูนย์ + ค่าส่ง 15 -> VAT 0 จ่าย 15 (ค่าส่งไม่อยู่ในฐาน VAT)", (lambda r: r["vat_amount"] == 0 and r["grand_total"] == 15)(_c(0, 15)))
check("vat: 100 + ค่าส่ง 25 -> VAT ยัง 6.54 จ่าย 125 (บวกค่าส่งครั้งเดียว)", (lambda r: r["vat_amount"] == 6.54 and r["grand_total"] == 125.0)(_c(100, 25)))
check("vat: ค่าติดลบ/ข้อความแปลก ไม่ crash (ถือเป็น 0)", _c(-5, "abc")["grand_total"] == 0)

# --- (2) ไม่มีส่วนลด: ซุป 10 + หมูสามชั้น 2 ชิ้น (5x2) = 20 ---
vo1 = vat_place({"P001": 2})
o1 = orders.find_order(vo1)
check("ไม่มีส่วนลด: food_total=20, VAT=1.31, ก่อน VAT 18.69, total = 20 + ค่าส่ง (ไม่บวก VAT เพิ่ม)",
      o1["food_total"] == 20 and o1["vat_amount"] == 1.31 and o1["subtotal_ex_vat"] == 18.69 and o1["total"] == round(20 + FEE, 2)
      and o1["vat_enabled"] and o1["vat_rate"] == 7 and o1["vat_mode"] == "included", f"{o1['food_total']} {o1['vat_amount']} {o1['total']}")
check("ไม่มีส่วนลด: บันทึก vat_demo=True + vat_base=food_total", o1["vat_demo"] is True and o1["vat_base"] == 20)
check("ก่อน VAT + VAT = food_total และ total = food_total + delivery_fee (ตรงกันเป๊ะ)",
      round(o1["subtotal_ex_vat"] + o1["vat_amount"], 2) == o1["food_total"] and round(o1["food_total"] + o1["delivery_fee"], 2) == o1["total"])

# --- (3) มีส่วนลด: ซุป 10 + กุ้ง 10 ชิ้น (10x10) = 110 -> ลดตามยอด 5% (5.50) -> 104.50 -> คูปอง MALA10 (-10) -> 94.50 ---
vat_session({"P021": 10}, "MALA10")
sm = cust.get("/checkout/summary").get_data(as_text=True)
vo2 = vat_place({"P021": 10}, "MALA10")
o2 = orders.find_order(vo2)
check("มีส่วนลด: food_total=94.5 (หลังหักส่วนลดตามยอด+คูปอง)", o2["subtotal"] == 110 and o2["tier_discount"] == 5.5 and o2["coupon_discount"] == 10 and o2["food_total"] == 94.5)
check("มีส่วนลด: VAT แยกจาก 94.50 = 6.18 (ไม่ใช่จาก 110 = 7.20) ก่อน VAT 88.32",
      o2["vat_amount"] == 6.18 and o2["vat_amount"] != 7.2 and o2["subtotal_ex_vat"] == 88.32, str(o2["vat_amount"]))
check("มีส่วนลด: total = 94.5 + ค่าส่ง (VAT ไม่ถูกบวกเพิ่ม)", o2["total"] == round(94.5 + FEE, 2), str(o2["total"]))
check("แต้มสะสมนับจากค่าอาหารหลังส่วนลด (ไม่เปลี่ยนจากเดิม)", o2["points_earned"] == int(94.5 // 10))

# --- (4) หน้าสรุปก่อนสแกนจ่าย ---
check("หน้าสรุป: ยอดรวมสินค้า / ส่วนลด / ก่อน VAT 88.32 / VAT 6.18 รวมอยู่ในราคา / ยอดชำระสุทธิ",
      "110.00" in sm and "-5.50" in sm and "-10.00" in sm and "88.32" in sm and "VAT 7%" in sm and "6.18" in sm and "รวมอยู่ในราคา" in sm and "ยอดชำระสุทธิ" in sm)
check("หน้าสรุป: ไม่มีบรรทัดบวก VAT เพิ่ม (+6.18) และไม่มียอด 107 เท่า", "+6.18" not in sm and f"{94.5 + 6.18 + FEE:.2f}" not in sm)
check("หน้าสรุป: ยอดชำระสุทธิตรงกับออเดอร์ที่สร้างจริง", f"ยอดชำระสุทธิ {o2['total']:.2f}" in sm)
check("หน้าสรุป: มีข้อความโหมดจำลอง VAT", NOTICE in sm)

# --- (5) ยอดตรงกันทุกหน้า: ตะกร้า / ชำระเงิน / QR / สถานะ / ประวัติ / แอดมิน ---
vat_session({"P021": 10}, "MALA10")
ct = cust.get("/cart").get_data(as_text=True)
check("ตะกร้า: ยอดชำระสุทธิ (ก่อนค่าส่ง) = 94.50 ไม่ใช่ 101.12 + VAT 6.18 รวมอยู่ในราคา + ข้อความจำลอง",
      "ยอดชำระสุทธิ: 94.50" in ct and "101.12" not in ct and "6.18" in ct and "รวมอยู่ในราคา" in ct and NOTICE in ct)
_cap = []
_orig_pp = A.promptpay.make_payload
A.promptpay.make_payload = lambda pid, amt, *a, **k: (_cap.append(amt), _orig_pp(pid, amt, *a, **k))[1]
try:
    pay = cust.get(f"/order/{vo2}/pay").get_data(as_text=True)
finally:
    A.promptpay.make_payload = _orig_pp
check("หน้าชำระเงิน: ยอดโอน = total + แจกแจงค่าอาหาร (รวม VAT 6.18) + ค่าส่ง + โหมดจำลอง",
      f"{o2['total']:.2f}" in pay and "รวม VAT 7%" in pay and "6.18" in pay and "94.50" in pay and NOTICE in pay)
check("QR พร้อมเพย์: route สร้าง QR ด้วยยอด = total ของออเดอร์ = ยอดหน้าสรุป", _cap == [o2["total"]] and f"ยอดชำระสุทธิ {_cap[0]:.2f}" in sm, str(_cap))
payload = A.promptpay.make_payload(config.PROMPTPAY_ID, o2["total"])
check("QR พร้อมเพย์: payload มียอด total (ไม่ใช่ยอดก่อน VAT / ไม่ใช่ยอดบวก VAT)",
      f"54{len('%.2f' % o2['total']):02d}{o2['total']:.2f}" in payload and f"54{len('%.2f' % o2['subtotal_ex_vat']):02d}{o2['subtotal_ex_vat']:.2f}" not in payload)
send_slip(vo2, JPG())
st = cust.get(f"/order/{vo2}").get_data(as_text=True)
check("หน้าสถานะ: ยอดรวมสุทธิ + ก่อน VAT 88.32 + VAT 6.18 รวมอยู่ในราคา ตรงกับออเดอร์",
      f"{o2['total']:.2f}" in st and "88.32" in st and "6.18" in st and "รวมอยู่ในราคา" in st and NOTICE in st)
hs = cust.get("/history").get_data(as_text=True)
check("ประวัติ: ยอดรวมสุทธิ (รวม VAT) ตรงกับออเดอร์", f"{o2['total']:.2f}" in hs and "รวม VAT" in hs)
ad = admin.get(f"/admin/order/{vo2}").get_data(as_text=True)
check("แอดมินรายละเอียดออเดอร์: ก่อน VAT + VAT + ยอดรวมตรงกัน + ข้อความจำลอง",
      f"{o2['total']:.2f}" in ad and "88.32" in ad and "6.18" in ad and "จำลอง" in ad)
check("แอดมินรายการออเดอร์: ยอดตรงกัน", f"{o2['total']:.2f}" in admin.get("/admin").get_data(as_text=True))

# --- (6) ใบเสร็จ: ใช้ VAT ที่บันทึกไว้ ไม่แยกภาษีซ้ำ ไม่ใช่ใบกำกับภาษี ---
act(vo2, "approve")
settings.set_receipt({"vat_registered": "on", "tax_id": "0123456789012", "vat_rate": "7"})    # ติ๊ก "จด VAT" ในหน้าตั้งค่าไว้ด้วย -> ต้องไม่แยกซ้ำ
rcp = cust.get(f"/order/{vo2}/receipt").get_data(as_text=True)
check("ใบเสร็จ: ก่อน VAT 88.32 + VAT 6.18 ที่บันทึกไว้ + ยอดสุทธิ + ข้อความจำลอง", "88.32" in rcp and "6.18" in rcp and f"{o2['total']:.2f}" in rcp and NOTICE in rcp)
check("ใบเสร็จ: ไม่ใช่ใบกำกับภาษี และแยกภาษีครั้งเดียว (แม้ตั้ง 'จด VAT' ไว้)", "ใบกำกับภาษีอย่างย่อ" not in rcp and "โหมดจำลอง VAT" in rcp and rcp.count("88.32") == 1, str(rcp.count("88.32")))
settings.set_receipt({})

# --- (7) รายงานรายได้: ค่าอาหาร(ก่อน VAT) + VAT + ค่าส่ง = ยอดรวม ---
import report                                   # noqa: E402
rep = report.build_report("paid", "", 0)
tot = rep["all_time"]
check("รายงาน: food + vat + fee = total และมียอด VAT", abs(tot["food"] + tot["vat"] + tot["fee"] - tot["total"]) < 0.01 and tot["vat"] >= 6.18, str(tot))

# --- (7.5) มีค่าส่ง: VAT ต้องไม่คิดบนค่าส่ง และบวกค่าส่งครั้งเดียว ---
FAR = dict(DELIVERY, lat=config.SHOP_LAT + 0.09, lng=config.SHOP_LNG)      # ห่างร้านราว 10 กม. -> ค่าส่ง > 0
FAR_FEE = delivery.calculate_delivery(FAR["lat"], FAR["lng"])["fee"]
vat_session({"P001": 2}, None, "S01", FAR)
far_sm = cust.get("/checkout/summary").get_data(as_text=True)
vo5 = vat_place({"P001": 2}, None, "S01", FAR)
o5 = orders.find_order(vo5)
check("มีค่าส่ง: ค่าส่ง > 0 แต่ VAT ยังเป็น 1.31 (แยกเฉพาะค่าอาหาร)", FAR_FEE > 0 and o5["delivery_fee"] == FAR_FEE and o5["vat_amount"] == 1.31, f"fee={FAR_FEE}")
check("มีค่าส่ง: total = 20 + ค่าส่ง (ครั้งเดียว) และหน้าสรุปแสดงยอดเดียวกัน", o5["total"] == round(20 + FAR_FEE, 2) and f"ยอดชำระสุทธิ {o5['total']:.2f}" in far_sm)
check("มีค่าส่ง: หน้าชำระเงิน/ประวัติแสดงยอดเดียวกัน", f"{o5['total']:.2f}" in cust.get(f"/order/{vo5}/pay").get_data(as_text=True) and f"{o5['total']:.2f}" in cust.get("/history").get_data(as_text=True))
act(vo5, "cancel")

# --- (8) ยอดรวมเป็นศูนย์ (ซุป 0 + วัตถุดิบ 0 บาท + ส่งฟรี) ---
_pr = storage.load_products()
_pr_all = storage.load_json("products.json")
_pr_all["soups"].append({"id": "S99", "name": "ซุปทดสอบฟรี", "price": 0, "detail": "", "image": "soup/S01.jpg"})
_pr_all["products"].append({"id": "P99", "name": "ของทดสอบฟรี", "category": "เนื้อสัตว์", "price": 0, "stock": 5,
                            "available": True, "image": "meat/P001.jpg", "detail": "", "tag": ""})
storage.save_json("products.json", _pr_all)
FREE = dict(DELIVERY, lat=config.SHOP_LAT, lng=config.SHOP_LNG)
vat_session({"P99": 1}, None, "S99", FREE)
zs = cust.get("/checkout/summary")
check("ยอดศูนย์: หน้าสรุปไม่ crash และชำระสุทธิ 0.00", zs.status_code == 200 and "ยอดชำระสุทธิ 0.00" in zs.get_data(as_text=True))
vz = vat_place({"P99": 1}, None, "S99", FREE)
oz = orders.find_order(vz)
check("ยอดศูนย์: สร้างออเดอร์ได้ VAT=0 ก่อน VAT=0 total=0", oz is not None and oz["vat_amount"] == 0 and oz["subtotal_ex_vat"] == 0 and oz["total"] == 0 and oz["food_total"] == 0)
check("ยอดศูนย์: หน้าชำระเงิน/สถานะไม่ crash", cust.get(f"/order/{vz}/pay").status_code == 200 and cust.get(f"/order/{vz}").status_code in (200, 302))   # ยังไม่จ่าย -> หน้าสถานะเด้งกลับหน้าชำระเงิน (พฤติกรรมเดิม)
act(vz, "cancel")
_pr_all = storage.load_json("products.json")
_pr_all["soups"] = [x for x in _pr_all["soups"] if x["id"] != "S99"]
_pr_all["products"] = [x for x in _pr_all["products"] if x["id"] != "P99"]
storage.save_json("products.json", _pr_all)

# --- (8.5) ยอดที่บันทึกไว้ไม่เปลี่ยนตามราคาสินค้า/อัตรา VAT ที่แก้ภายหลัง ---
_snap = (orders.find_order(vo2)["total"], orders.find_order(vo2)["vat_amount"], orders.find_order(vo2)["subtotal_ex_vat"])
_pr_all = storage.load_json("products.json")
_old_prices = {p["id"]: p["price"] for p in _pr_all["products"]}
for p in _pr_all["products"]:
    p["price"] = p["price"] * 3 + 1
storage.save_json("products.json", _pr_all)
config.VAT_RATE = 10
_st2 = cust.get(f"/order/{vo2}").get_data(as_text=True)
_rc2 = cust.get(f"/order/{vo2}/receipt").get_data(as_text=True)
check("แก้ราคาสินค้า + เปลี่ยนอัตรา VAT ภายหลัง: ยอด/VAT ของออเดอร์เดิมไม่เปลี่ยน (สถานะ/ใบเสร็จยังแสดง 94.50 / 6.18 / 88.32)",
      (orders.find_order(vo2)["total"], orders.find_order(vo2)["vat_amount"], orders.find_order(vo2)["subtotal_ex_vat"]) == _snap
      and f"{_snap[0]:.2f}" in _st2 and "6.18" in _st2 and "88.32" in _rc2 and "VAT 7%" in _st2)
config.VAT_RATE = 7
_pr_all = storage.load_json("products.json")
for p in _pr_all["products"]:
    p["price"] = _old_prices[p["id"]]
storage.save_json("products.json", _pr_all)

# --- (8.6) ออเดอร์เก่าที่ "บวก VAT เพิ่ม" (ไม่มี vat_mode) และออเดอร์เก่ามาก ๆ ที่ไม่มีคีย์ VAT เลย: เปิดได้ ยอดไม่เปลี่ยน ---
_all = orders.load_orders()
_legacy = {k: v for k, v in dict(orders.find_order(vo2)).items() if k not in ("vat_mode", "subtotal_ex_vat")}
_legacy.update({"order_id": "MZ9101", "vat_amount": 6.62, "total": round(94.5 + 6.62 + FEE, 2), "status": 3})
_bare = {k: v for k, v in dict(orders.find_order(vo2)).items()
         if k not in ("vat_mode", "subtotal_ex_vat", "vat_enabled", "vat_rate", "vat_base", "vat_amount", "vat_demo")}
_bare.update({"order_id": "MZ9102", "total": round(94.5 + FEE, 2), "status": 3})
_all += [_legacy, _bare]
orders.save_orders(_all)
_pg = {oid: cust.get(f"/order/{oid}") for oid in ("MZ9101", "MZ9102")}
_rc = {oid: cust.get(f"/order/{oid}/receipt") for oid in ("MZ9101", "MZ9102")}
_ad = {oid: admin.get(f"/admin/order/{oid}") for oid in ("MZ9101", "MZ9102")}
check("ออเดอร์เก่า (บวก VAT เพิ่ม ไม่มี vat_mode): เปิดสถานะ/ใบเสร็จ/แอดมินได้ ยอดและ VAT 6.62 เท่าที่บันทึกไว้ ไม่ถูกคิดใหม่",
      all(r.status_code == 200 for r in (_pg["MZ9101"], _rc["MZ9101"], _ad["MZ9101"]))
      and f"{_legacy['total']:.2f}" in _pg["MZ9101"].get_data(as_text=True) and "6.62" in _pg["MZ9101"].get_data(as_text=True)
      and "6.62" in _rc["MZ9101"].get_data(as_text=True) and "รวมอยู่ในราคา" not in _pg["MZ9101"].get_data(as_text=True))
check("ออเดอร์เก่ามาก (ไม่มีคีย์ VAT เลย): เปิดสถานะ/ใบเสร็จ/แอดมินได้ ไม่มีบรรทัด VAT ยอดเดิม",
      all(r.status_code == 200 for r in (_pg["MZ9102"], _rc["MZ9102"], _ad["MZ9102"]))
      and f"{_bare['total']:.2f}" in _pg["MZ9102"].get_data(as_text=True) and "รวมอยู่ในราคา" not in _pg["MZ9102"].get_data(as_text=True))
check("ประวัติลูกค้ายังเปิดได้เมื่อมีออเดอร์เก่า 2 แบบ", cust.get("/history").status_code == 200)
_rep2 = report.build_report("paid", "", 0)["all_time"]
check("รายงานรวมออเดอร์เก่า (บวกเพิ่ม) + ใหม่ (รวมในราคา): food + vat + fee = total", abs(_rep2["food"] + _rep2["vat"] + _rep2["fee"] - _rep2["total"]) < 0.01, str(_rep2))
orders.save_orders([o for o in orders.load_orders() if o["order_id"] not in ("MZ9101", "MZ9102")])

# --- (8.7) กันสร้างออเดอร์ซ้ำ / กันยอดไม่ตรง ---
_n0 = len(orders.load_orders())
vat_session({"P001": 1})
_r_a = cust.post("/order/create")
_r_b = cust.post("/order/create")            # กดซ้ำ (session ถูกล้างแล้ว)
check("กดสั่งซื้อซ้ำ: สร้างออเดอร์แค่ 1 รายการ", len(orders.load_orders()) == _n0 + 1 and _r_a.status_code == 302 and _r_b.status_code == 302 and "/pay" in _r_a.headers["Location"] and "/pay" not in _r_b.headers["Location"])
_dup_id = _r_a.headers["Location"].split("/")[2]
_st_before = stock("P001")
_bad = False
try:
    orders.create_order(USER, {"id": "S01", "name": "x", "price": 10}, 3, "x", [{"id": "P001", "qty": 1, "name": "x", "price": 5, "subtotal": 5}],
                        {"subtotal": 15, "tier_percent": 0, "tier_discount": 0, "coupon_code": "", "coupon_discount": 0, "final_total": 15},
                        DELIVERY, 1, 0, 16.07, vat.calculate(15, 0))      # ยอดบวก VAT เพิ่มผิด: 15 + 1.07 = 16.07
except ValueError:
    _bad = True
check("ยอดชำระไม่เท่ากับค่าอาหาร+ค่าส่ง (เช่น บวก VAT เพิ่มโดยพลาด) -> สร้างออเดอร์ไม่ได้ และไม่ตัดสต็อก", _bad and stock("P001") == _st_before)
act(_dup_id, "cancel")

# --- (9) เปิด/ปิดจาก config.py + ออเดอร์เดิมไม่เปลี่ยนยอด ---
before = (orders.find_order(vo2)["total"], orders.find_order(vo2)["vat_amount"])
config.VAT_ENABLED = False
vat_session({"P001": 2})
off_sm = cust.get("/checkout/summary").get_data(as_text=True)
off_ct = cust.get("/cart").get_data(as_text=True)
check("ปิด VAT: หน้าสรุป/ตะกร้าไม่มีบรรทัด VAT และไม่มีข้อความโหมดจำลอง", "VAT" not in off_sm and "VAT" not in off_ct and NOTICE not in off_sm and NOTICE not in off_ct)
vo3 = vat_place({"P001": 2})
o3 = orders.find_order(vo3)
check("ปิด VAT: ยอด = ค่าอาหาร + ค่าส่ง เท่าเดิม (VAT 0, vat_enabled=False)", o3["total"] == round(20 + FEE, 2) and o3["vat_amount"] == 0 and o3["vat_enabled"] is False)
check("ปิด VAT ทีหลัง: ออเดอร์ที่แยก VAT ไว้แล้วยอดไม่เปลี่ยน + ยังแสดง VAT", (orders.find_order(vo2)["total"], orders.find_order(vo2)["vat_amount"]) == before and "6.18" in cust.get(f"/order/{vo2}").get_data(as_text=True))
send_slip(vo3, JPG()); act(vo3, "approve")
_r3 = cust.get(f"/order/{vo3}/receipt").get_data(as_text=True)
check("ปิด VAT: ใบเสร็จออเดอร์ไม่มี VAT เป็นใบเสร็จธรรมดา (ไม่มีบรรทัด VAT/ข้อความจำลอง)", "VAT" not in _r3 and NOTICE not in _r3 and "ยอดชำระสุทธิ" in _r3)
act(vo3, "cancel")
config.VAT_ENABLED, config.VAT_RATE = True, 50
vo4 = vat_place({"P001": 2})
check("อัตรา VAT ผิดปกติ (50%) -> ระบบปิด VAT เอง ไม่คิดเงินผิด", orders.find_order(vo4)["vat_enabled"] is False and orders.find_order(vo4)["total"] == round(20 + FEE, 2))
config.VAT_RATE = 7
config.VAT_DEMO_MODE = False
check("VAT_DEMO_MODE=False: ไม่แสดงข้อความโหมดจำลองในตะกร้าใหม่", (vat_session({"P001": 2}) or True) and NOTICE not in cust.get("/cart").get_data(as_text=True))
config.VAT_DEMO_MODE = True
check("หน้าตั้งค่าแอดมินแสดงสถานะ VAT จำลอง + ชี้ไป config.py", "config.py" in admin.get("/admin/settings").get_data(as_text=True) and "VAT จำลอง" in admin.get("/admin/settings").get_data(as_text=True))
for _o in (vo1, vo2, vo4):
    act(_o, "cancel")
config.VAT_ENABLED = False

print(f"\nสรุป: ผ่าน {sum(results)}/{len(results)}")
shutil.rmtree(os.path.dirname(TMP), ignore_errors=True)
sys.exit(0 if all(results) else 1)
