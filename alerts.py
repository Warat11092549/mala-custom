# alerts.py - สรุปตัวเลขแจ้งเตือนหลังร้าน: สลิปรอตรวจ / ออเดอร์ที่เปิดอยู่ / สต็อกใกล้หมด
# อ่านอย่างเดียว ไม่แก้ orders.json หรือ products.json

import config
import orders
import storage

_EMPTY = {
    "pending_slips": 0, "slip_ids": [], "open_orders": [],
    "low_stock": [], "out_of_stock": [], "low_total": 0,
    "threshold": 20, "ok": False,
}


def _int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _order_id(order):
    return str(order.get("order_id") or order.get("id") or "")


def stock_alerts(products=None):
    """สินค้าที่ 'ยังเปิดขายอยู่' แต่สต็อกใกล้หมด/หมดแล้ว (สินค้าที่แอดมินปิดขายเองไม่เตือน)
    ตัวเลือกที่ตั้งสต็อกไว้สูงมาก (เช่น กรอง/ไม่กรองเม็ดหม่าล่า = 9999) ไม่เข้าเกณฑ์เองอยู่แล้ว"""
    if products is None:
        products = storage.load_products()
    threshold = _int(getattr(config, "LOW_STOCK_THRESHOLD", 20), 20)
    low, out = [], []
    for p in products:
        if not p.get("available", True):
            continue
        stock = _int(p.get("stock"), 0)
        row = {"id": str(p.get("id", "")), "name": p.get("name", "?"),
               "category": p.get("category", ""), "stock": stock}
        if stock <= 0:
            out.append(row)
        elif stock <= threshold:
            low.append(row)
    low.sort(key=lambda r: (r["stock"], r["name"]))
    out.sort(key=lambda r: r["name"])
    return low, out, threshold


def summary():
    """ตัวเลขทั้งหมดที่แถบเมนู/แดชบอร์ด/ตัวส่งเสียงใช้ ถ้าอ่านข้อมูลไม่ได้คืนค่าศูนย์ (ok=False) ไม่ให้หน้าล่ม"""
    result = dict(_EMPTY, slip_ids=[], open_orders=[], low_stock=[], out_of_stock=[])
    try:
        result["threshold"] = _int(getattr(config, "LOW_STOCK_THRESHOLD", 20), 20)
        for order in orders.load_orders():
            st = orders.get_status(order)
            if st not in (1, 2):
                continue
            oid = _order_id(order)
            if not oid:
                continue
            result["open_orders"].append({
                "id": oid, "status": st,
                "name": str(order.get("customer_name") or order.get("name") or "-"),
                "total": round(float(order.get("total") or order.get("grand_total") or 0), 2),
            })
            if st == 2:
                result["slip_ids"].append(oid)
        result["pending_slips"] = len(result["slip_ids"])
        result["ok"] = True
    except Exception:
        result["ok"] = False
    try:
        low, out, threshold = stock_alerts()
        result.update(low_stock=low, out_of_stock=out, threshold=threshold, low_total=len(low) + len(out))
    except Exception:
        result["ok"] = False
    return result
