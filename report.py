# report.py - สรุปรายได้ + วัตถุดิบที่ขายดี (อ่านอย่างเดียว ไม่แก้ไข orders.json)

from collections import defaultdict
from datetime import datetime, timedelta

import orders
import storage

# ออเดอร์ที่นับเป็นรายได้ (สถานะ 1-2 ยังไม่ผ่านตรวจสลิป และ 9 ยกเลิก จะไม่นับ)
BASIS = {
    "paid": {"statuses": (3, 4, 5), "label": "ชำระแล้ว (ตรวจสลิปผ่านแล้ว)"},
    "done": {"statuses": (5,), "label": "จัดส่งสำเร็จแล้วเท่านั้น"},
}


def _num(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _when(order):
    """วันเวลาที่สั่ง (รองรับทั้งคีย์ date และ created_at ของออเดอร์เก่า) ไม่มี/อ่านไม่ได้คืน None"""
    text = str(order.get("date") or order.get("created_at") or "").strip()
    for fmt, size in (("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(text[:size], fmt)
        except ValueError:
            continue
    return None


def _total(order):
    value = order.get("total")
    if value is None:
        value = order.get("grand_total")
    return _num(value)


def _fee(order):
    value = order.get("delivery_fee")
    if value is None:
        value = order.get("fee")
    return _num(value)


def _vat(order):
    """VAT ที่บวกเพิ่มในออเดอร์ (ระบบ VAT จำลอง) ออเดอร์เก่า/ปิด VAT = 0"""
    if not order.get("vat_enabled"):
        return 0.0
    return _num(order.get("vat_amount"))


def _sum(rows):
    total = sum(_total(o) for _, o in rows)
    fee = sum(_fee(o) for _, o in rows)
    vat = sum(_vat(o) for _, o in rows)
    return {
        "orders": len(rows),
        "total": round(total, 2),
        "fee": round(fee, 2),
        "vat": round(vat, 2),
        "food": round(total - fee - vat, 2),      # ค่าอาหารไม่รวม VAT (food + vat + fee = total)
    }


def _with_bars(items):
    biggest = max([i["total"] for i in items] or [0])
    for i in items:
        i["pct"] = round(i["total"] * 100 / biggest) if biggest else 0
    return items


def _group(rows, fmt):
    groups = defaultdict(list)
    for when, order in rows:
        groups[when.strftime(fmt)].append((when, order))
    return groups


def top_items(rows, days):
    """จัดอันดับวัตถุดิบ/ซุปที่ลูกค้าสั่ง days = จำนวนวันย้อนหลัง (0 = ทั้งหมด)"""
    since = datetime.now() - timedelta(days=days) if days else None
    products = {str(p["id"]): p for p in storage.load_products()}
    stats, soups, by_cat = {}, {}, defaultdict(int)
    order_count = 0

    for when, order in rows:
        if since and when < since:
            continue
        order_count += 1
        soup = order.get("soup")
        if isinstance(soup, dict) and soup.get("name"):
            soups[soup["name"]] = soups.get(soup["name"], 0) + 1
        for line in orders.order_lines(order):
            pid = str(line.get("id") or line.get("name") or "?")
            qty = int(_num(line.get("qty")))
            money = _num(line.get("subtotal")) or _num(line.get("price")) * qty
            prod = products.get(pid, {})
            row = stats.setdefault(pid, {
                "name": line.get("name") or prod.get("name") or pid,
                "category": prod.get("category", "-"),
                "stock": prod.get("stock"),
                "qty": 0, "money": 0.0, "orders": 0,
            })
            row["qty"] += qty
            row["money"] += money
            row["orders"] += 1
            by_cat[row["category"]] += qty

    ranked = sorted(stats.values(), key=lambda r: (-r["qty"], r["name"]))
    biggest = ranked[0]["qty"] if ranked else 0
    for r in ranked:
        r["money"] = round(r["money"], 2)
        r["pct"] = round(r["qty"] * 100 / biggest) if biggest else 0
    return {
        "order_count": order_count,
        "rows": ranked,
        "soups": sorted(soups.items(), key=lambda x: -x[1]),
        "categories": sorted(by_cat.items(), key=lambda x: -x[1]),
    }


def build_report(basis="paid", month="", days=30):
    """รวมข้อมูลทั้งหมดที่หน้ารายงานต้องใช้"""
    if basis not in BASIS:
        basis = "paid"
    now = datetime.now()
    try:
        month = datetime.strptime(month, "%Y-%m").strftime("%Y-%m")
    except ValueError:
        month = now.strftime("%Y-%m")

    statuses = BASIS[basis]["statuses"]
    rows = []
    for order in orders.load_orders():
        when = _when(order)
        if when is not None and orders.get_status(order) in statuses:
            rows.append((when, order))

    by_day = _group(rows, "%Y-%m-%d")
    by_month = _group(rows, "%Y-%m")
    today_key = now.strftime("%Y-%m-%d")

    daily = []
    for key in sorted(by_day, reverse=True):
        if key.startswith(month):
            daily.append(dict(_sum(by_day[key]), label=key))
    monthly = [dict(_sum(by_month[k]), label=k) for k in sorted(by_month, reverse=True)]

    month_options = sorted(set(by_month) | {now.strftime("%Y-%m")}, reverse=True)

    return {
        "basis": basis,
        "basis_label": BASIS[basis]["label"],
        "basis_options": {k: v["label"] for k, v in BASIS.items()},
        "month": month,
        "month_options": month_options,
        "days": days,
        "today": _sum(by_day.get(today_key, [])),
        "this_month": _sum(by_month.get(now.strftime("%Y-%m"), [])),
        "picked_month": _sum(by_month.get(month, [])),
        "all_time": _sum(rows),
        "daily": _with_bars(daily),
        "monthly": _with_bars(monthly),
        "top": top_items(rows, days),
    }
