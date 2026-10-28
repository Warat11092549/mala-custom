# receipts.py - ใบเสร็จรับเงิน / ใบกำกับภาษีอย่างย่อ (สร้างจากข้อมูลออเดอร์ ไม่เก็บไฟล์เพิ่ม)
#   - ออกให้ได้เมื่อร้านตรวจสลิปผ่านแล้ว (สถานะ 3 เตรียมอาหาร, 4 กำลังส่ง, 5 สำเร็จ)
#   - ร้านที่ "จด VAT" (ตั้งในหน้า แอดมิน > ตั้งค่า): ราคาในเมนูถือว่า "รวม VAT แล้ว" แล้วแยกยอดก่อนภาษี/VAT ให้ดู
#   - ออเดอร์ที่มี VAT จำลอง (order["vat_enabled"], ดู vat.py): VAT ถูกบวกเพิ่มแล้วและเก็บไว้กับออเดอร์ -> ใบเสร็จแสดงค่าที่เก็บไว้
#     ออกเป็น "ใบเสร็จรับเงิน (โหมดจำลอง VAT)" ไม่ใช่ใบกำกับภาษี และไม่แยกภาษีซ้ำ
#   - ร้านที่ไม่ได้จด VAT: ออกเป็น "ใบเสร็จรับเงิน" ธรรมดา ไม่แสดงภาษี
#   - เลขที่ใบเสร็จ = RC- + เลขออเดอร์ (ไม่ใช่เลขรันตามกฎหมาย ถ้าต้องใช้เป็นใบกำกับภาษีจริง ให้ปรึกษาสรรพากร/นักบัญชี)

import config
import settings

RECEIPT_STATUSES = (3, 4, 5)


def can_issue(order):
    try:
        return int(order.get("status", 1)) in RECEIPT_STATUSES
    except (TypeError, ValueError):
        return False


def _money(value):
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def build(order):
    """คืน dict พร้อมแสดงผล (order ต้องผ่าน normalize_order แล้ว)"""
    info = settings.receipt_info()
    soup = order.get("soup") if isinstance(order.get("soup"), dict) else {}
    soup_price = _money(soup.get("price"))
    ingredients = order.get("ingredient_items") or []
    sauces = order.get("sauce_items") or []
    seeds = order.get("seed_items") or []

    rows = []
    if soup.get("name"):
        rows.append({"name": f"น้ำซุป {soup.get('name')}", "qty": 1, "price": soup_price, "amount": soup_price})
    for item in list(ingredients) + list(sauces) + list(seeds):
        amount = _money(item.get("subtotal"))
        if amount <= 0:                         # ตัวเลือกฟรี (เช่น ไม่กรองเม็ด) ไม่ต้องขึ้นเป็นบรรทัดราคา 0
            continue
        rows.append({"name": item.get("name", "-"), "qty": item.get("qty", 1),
                     "price": _money(item.get("price")), "amount": amount})

    gross = round(sum(r["amount"] for r in rows), 2)
    food_total = _money(order.get("food_total"))
    fee = _money(order.get("delivery_fee"))
    total = _money(order.get("total"))

    discounts = []
    for label, key in (("ส่วนลดตามยอดสั่ง", "tier_discount"), ("ส่วนลดคูปอง", "coupon_discount"),
                       ("ส่วนลดโค้ดสมาชิก", "member_discount")):
        value = _money(order.get(key))
        if value > 0:
            discounts.append({"label": label, "amount": value})
    leftover = round(gross - food_total - sum(d["amount"] for d in discounts), 2)
    if leftover > 0.01:                          # ออเดอร์เก่าที่ไม่ได้เก็บแยกประเภทส่วนลด
        discounts.append({"label": "ส่วนลด", "amount": leftover})

    vat = None
    if order.get("vat_enabled") and order.get("vat_mode") == "included":
        # ออเดอร์ที่แยก VAT ตอนสั่งซื้อ (VAT รวมอยู่ในราคา): ใช้ค่าที่บันทึกไว้ ไม่คำนวณใหม่
        # และไม่แยกภาษีซ้ำจากการตั้งค่า "จด VAT" ในหน้าตั้งค่า (กันภาษีซ้ำซ้อน)
        vat = {"mode": "included", "stored": True, "rate": _money(order.get("vat_rate")),
               "base": _money(order.get("subtotal_ex_vat")), "amount": _money(order.get("vat_amount")),
               "food": food_total, "demo": bool(order.get("vat_demo"))}
    elif order.get("vat_enabled"):
        # ออเดอร์เก่าที่ "บวก VAT เพิ่ม" ไว้ใน total แล้ว (ไม่มี vat_mode): แสดงตามที่บันทึกไว้ ไม่แยกภาษีซ้ำ
        vat = {"mode": "added", "rate": _money(order.get("vat_rate")), "base": food_total,
               "amount": _money(order.get("vat_amount")), "demo": bool(order.get("vat_demo"))}
    elif info["vat_registered"]:
        rate = info["vat_rate"]
        base = round(total * 100 / (100 + rate), 2)
        vat = {"mode": "included", "rate": rate, "base": base, "amount": round(total - base, 2), "demo": False}

    if vat and (vat["mode"] == "added" or vat.get("stored")) and vat["demo"]:
        title = "ใบเสร็จรับเงิน (โหมดจำลอง VAT)"      # ไม่ใช่ใบกำกับภาษีตามกฎหมาย
    elif vat and vat["mode"] == "added":
        title = "ใบเสร็จรับเงิน"
    elif info["vat_registered"]:
        title = "ใบเสร็จรับเงิน / ใบกำกับภาษีอย่างย่อ"
    else:
        title = "ใบเสร็จรับเงิน"

    return {
        "no": "RC-" + str(order.get("order_id", "")),
        "title": title,
        "seller": info,
        "rows": rows, "gross": gross, "discounts": discounts,
        "fee": fee, "total": total, "vat": vat,
        "shop_phone": config.SHOP_PHONE,
    }
