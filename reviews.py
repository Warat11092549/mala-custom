# reviews.py - รีวิวหลังจัดส่งสำเร็จ (เก็บในออเดอร์ ให้แอดมินดูเท่านั้น ยังไม่โชว์สาธารณะ)
#
# เก็บที่ออเดอร์ (orders.json) 2 คีย์:
#   review          {"stars": 1-5, "comment": "...", "at": "YYYY-MM-DD HH:MM:SS"}   (ไม่มี = ยังไม่รีวิว)
#   review_skipped  True เมื่อลูกค้ากด "ข้าม"
# รีวิวได้ครั้งเดียวต่อออเดอร์ และเฉพาะเจ้าของออเดอร์ที่สถานะ 5 เท่านั้น (ตรวจฝั่งเซิร์ฟเวอร์ทุกครั้ง)

import datetime

import config
import orders


def parse_stars(value):
    """แปลงค่าที่ส่งมาเป็นดาว 1-5 ไม่ใช่เลขจำนวนเต็ม 1-5 คืน None"""
    text = str(value).strip()
    if text.isascii() and text.isdigit() and 1 <= int(text) <= 5:
        return int(text)
    return None


def clean_comment(text):
    """ตัดช่องว่างหัวท้าย/อักขระควบคุม และจำกัดความยาว (การป้องกัน XSS ทำที่ Jinja autoescape ตอนแสดงผล)"""
    text = "".join(ch for ch in str(text or "") if ch in "\n\t" or ch >= " ")
    return text.strip()[:config.REVIEW_COMMENT_MAX]


def _own(order, username):
    return bool(order) and str(order.get("username", "")).lower() == str(username or "").lower()


def has_review(order):
    return isinstance(order.get("review"), dict)


def can_review(order, username):
    """คืน (ได้ไหม, เหตุผลถ้าไม่ได้)"""
    if not _own(order, username):
        return False, "ไม่พบออเดอร์นี้"
    if orders.get_status(order) != 5:
        return False, "รีวิวได้หลังจัดส่งสำเร็จเท่านั้น"
    if has_review(order):
        return False, "ออเดอร์นี้รีวิวไปแล้ว ขอบคุณมากนะ"
    return True, ""


def submit(order_id, username, stars, comment=""):
    """บันทึกรีวิว คืน (สำเร็จไหม, ข้อความ)"""
    order = orders.find_order(order_id)             # อ่านจากไฟล์ล่าสุดเสมอ ไม่เชื่อข้อมูลจากฟอร์ม
    ok, why = can_review(order, username)
    if not ok:
        return False, why
    value = parse_stars(stars)
    if value is None:
        return False, "กรุณาเลือกดาว 1–5 ดวง"
    order["review"] = {
        "stars": value,
        "comment": clean_comment(comment),
        "at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    order["review_skipped"] = False
    orders.update_order(order)
    return True, "ขอบคุณสำหรับรีวิวนะ 🙏"


def skip(order_id, username):
    """ลูกค้ากด 'ข้าม' (ไม่บันทึกดาว) คืน (สำเร็จไหม, ข้อความ)"""
    order = orders.find_order(order_id)
    ok, why = can_review(order, username)
    if not ok:
        return False, why
    order["review_skipped"] = True
    orders.update_order(order)
    return True, "ข้ามการรีวิวแล้ว"


def _row(order):
    review = order["review"]
    return {
        "order_id": order.get("order_id", ""),
        "username": order.get("username", ""),
        "customer_name": order.get("customer_name") or order.get("name") or order.get("username", ""),
        "phone": order.get("phone", ""),
        "stars": int(review.get("stars", 0)),
        "comment": review.get("comment", ""),
        "at": review.get("at", ""),
        "total": order.get("total") if order.get("total") is not None else order.get("grand_total", 0),
    }


def summary(max_stars=None):
    """สรุปให้แอดมิน: จำนวน/ค่าเฉลี่ย/การกระจายดาว/ออเดอร์ดาวต่ำ/รีวิวล่าสุด
    max_stars = กรองรายการให้เหลือเฉพาะที่ได้ไม่เกินกี่ดาว"""
    all_orders = orders.load_orders()
    rows = [_row(o) for o in all_orders if has_review(o)]
    rows.sort(key=lambda r: r["at"], reverse=True)

    count = len(rows)
    average = round(sum(r["stars"] for r in rows) / count, 2) if count else 0
    distribution = {s: sum(1 for r in rows if r["stars"] == s) for s in (5, 4, 3, 2, 1)}
    delivered = sum(1 for o in all_orders if orders.get_status(o) == 5)
    low = [r for r in rows if r["stars"] <= config.LOW_STAR_THRESHOLD]

    shown = rows if max_stars is None else [r for r in rows if r["stars"] <= max_stars]
    return {
        "count": count,
        "average": average,
        "distribution": distribution,
        "delivered": delivered,
        "response_rate": round(count * 100 / delivered) if delivered else 0,
        "low": low,
        "rows": shown,
        "low_threshold": config.LOW_STAR_THRESHOLD,
    }
