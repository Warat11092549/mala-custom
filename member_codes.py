# member_codes.py - โค้ดสมาชิกเฉพาะ id (ผูกกับชื่อผู้ใช้ ใช้ได้ครั้งเดียว มีวันหมดอายุ ตรวจฝั่งเซิร์ฟเวอร์ทุกครั้ง)
#
# กติกา
#   * ยอดสะสม = ผลรวมค่าอาหารสุทธิ (food_total ไม่รวมค่าส่ง) ของออเดอร์ที่ "จัดส่งสำเร็จ (สถานะ 5)" ของผู้ใช้คนนั้นเท่านั้น
#   * ทุก MEMBER_REWARD_EVERY บาท ได้โค้ด 1 ใบ  (จำนวนใบที่ควรได้ = ยอดสะสม // EVERY)
#   * ถือโค้ดที่ยังใช้ได้พร้อมกันได้ครั้งละ 1 ใบ  ใบที่ควรได้แต่ยังออกไม่ได้ จะออกให้เมื่อใบก่อนหน้าถูกใช้/หมดอายุ
#   * โค้ดหมดอายุโดยไม่ได้ใช้ = สิทธิ์ใบนั้นหมดไป (ไม่ออกซ้ำ)  ออเดอร์ที่ใช้โค้ดถูกยกเลิก = คืนโค้ดให้ (ถ้ายังไม่หมดอายุ)
#   * ค่าส่วนลด/ขั้นต่ำถูกเก็บในโค้ดตอนออกใบ แก้ config ภายหลังไม่กระทบใบที่ออกไปแล้ว
#
# เก็บใน data/member_codes.json (list ของ dict):
#   code, username, issued_at, expires_at, value, min_order, issued_by_order, used_order_id, used_at
#   used_order_id: "" = ยังไม่ใช้ | "PENDING" = กำลังจองระหว่างสร้างออเดอร์ | MZxxxx = ใช้กับออเดอร์นั้นแล้ว
#
# หมายเหตุ: ล็อกด้วย threading.Lock ใน process เดียว (พอสำหรับ Flask เครื่องเดียว) ไม่ใช่ล็อกข้ามหลาย process

import datetime
import secrets
import threading

import config
import orders
import storage

FILENAME = "member_codes.json"
FMT = "%Y-%m-%d %H:%M:%S"
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"     # ไม่มี O/0/I/1 กันอ่านผิด
PENDING = "PENDING"
PENDING_TTL_SECONDS = 120        # จองไว้แล้วระบบล้มก่อนผูกออเดอร์ -> เกินเวลานี้ถือว่าไม่ได้ใช้

_lock = threading.RLock()


# ---------- เครื่องมือพื้นฐาน ----------

def _now():
    return datetime.datetime.now()


def _parse(text):
    try:
        return datetime.datetime.strptime(str(text), FMT)
    except (ValueError, TypeError):
        return None


def _load():
    try:
        data = storage.load_json(FILENAME)
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _save(records):
    storage.save_json(FILENAME, records)


def _same_user(a, b):
    return str(a or "").strip().lower() == str(b or "").strip().lower() and str(a or "").strip() != ""


def state(rec, now=None):
    """สถานะของโค้ด: active | used | expired"""
    now = now or _now()
    used = rec.get("used_order_id", "")
    if used == PENDING:
        reserved_at = _parse(rec.get("used_at"))
        if reserved_at and (now - reserved_at).total_seconds() <= PENDING_TTL_SECONDS:
            return "used"
        used = ""                                   # จองค้าง (ระบบล้มกลางทาง) -> ปล่อยคืน
    if used:
        return "used"
    expires = _parse(rec.get("expires_at"))
    if expires is None or now >= expires:
        return "expired"
    return "active"


# ---------- ยอดสะสม ----------

def food_amount(order):
    """ค่าอาหารสุทธิของออเดอร์ (ไม่รวมค่าส่ง) รองรับออเดอร์เก่ารูปแบบ ORD…"""
    def num(value):
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0
    if order.get("food_total") is not None:
        return num(order["food_total"])
    total = order.get("total") if order.get("total") is not None else order.get("grand_total")
    fee = order.get("delivery_fee") if order.get("delivery_fee") is not None else order.get("fee")
    return max(0.0, num(total) - num(fee))


def delivered_spend(username):
    """ยอดสะสมของผู้ใช้ จากออเดอร์สถานะ 5 เท่านั้น"""
    return round(sum(food_amount(o) for o in orders.load_orders()
                     if _same_user(o.get("username"), username) and orders.get_status(o) == 5), 2)


def earned_count(spend):
    """ยอดสะสมนี้ควรได้โค้ดรวมกี่ใบ"""
    every = config.MEMBER_REWARD_EVERY
    if not config.MEMBER_REWARD_ENABLED or not every or every <= 0:
        return 0
    return int(spend // every)


# ---------- ออกโค้ด / ตรวจโค้ด ----------

def _new_code(existing):
    while True:
        code = "MB-" + "".join(secrets.choice(ALPHABET) for _ in range(6))
        if code not in existing:
            return code


def active_code(username, records=None):
    """โค้ดที่ใช้ได้ของผู้ใช้ (ใบที่หมดอายุช้าสุดก่อน) ไม่มีคืน None"""
    records = _load() if records is None else records
    now = _now()
    mine = [r for r in records if _same_user(r.get("username"), username) and state(r, now) == "active"]
    mine.sort(key=lambda r: r.get("expires_at", ""))
    return mine[0] if mine else None


def issue_if_earned(username, source_order_id=""):
    """ออกโค้ดให้ผู้ใช้ถ้ายอดสะสมถึงเกณฑ์และยังไม่มีใบที่ใช้ได้ คืนโค้ดที่ออกใหม่ (ไม่ได้ออก = None)"""
    if not config.MEMBER_REWARD_ENABLED or not username or str(username).lower() == "admin":
        return None
    spend = delivered_spend(username)
    with _lock:
        records = _load()
        issued = sum(1 for r in records if _same_user(r.get("username"), username))
        if earned_count(spend) <= issued or active_code(username, records):
            return None
        now = _now()
        rec = {
            "code": _new_code({r.get("code") for r in records}),
            "username": username,
            "issued_at": now.strftime(FMT),
            "expires_at": (now + datetime.timedelta(days=config.MEMBER_REWARD_VALID_DAYS)).strftime(FMT),
            "value": config.MEMBER_REWARD_BAHT,
            "min_order": config.MEMBER_REWARD_MIN_ORDER,
            "issued_by_order": source_order_id,
            "used_order_id": "",
            "used_at": "",
        }
        records.append(rec)
        _save(records)
        return rec


def validate(code, username):
    """ตรวจโค้ดที่ลูกค้าเลือกไว้ (เรียกทุกครั้งที่คิดราคา) ต้องเป็นของผู้ใช้คนนี้และยังใช้ได้ คืน record หรือ None"""
    if not code or not username:
        return None
    for rec in _load():
        if rec.get("code") == str(code) and _same_user(rec.get("username"), username):
            return rec if state(rec) == "active" else None
    return None


def reserve(code, username):
    """จองโค้ดแบบอะตอมมิก (ตอนจะสร้างออเดอร์) สำเร็จคืน True — กันใช้ซ้ำสองออเดอร์พร้อมกัน"""
    with _lock:
        records = _load()
        for rec in records:
            if rec.get("code") == str(code) and _same_user(rec.get("username"), username):
                if state(rec) != "active":
                    return False
                rec["used_order_id"] = PENDING
                rec["used_at"] = _now().strftime(FMT)
                _save(records)
                return True
    return False


def attach(code, order_id):
    """ผูกโค้ดที่จองไว้เข้ากับออเดอร์ที่สร้างสำเร็จ"""
    with _lock:
        records = _load()
        for rec in records:
            if rec.get("code") == str(code) and rec.get("used_order_id") == PENDING:
                rec["used_order_id"] = order_id
                _save(records)
                return True
    return False


def release(code):
    """คืนโค้ดที่จองไว้ (สร้างออเดอร์ไม่สำเร็จ)"""
    with _lock:
        records = _load()
        for rec in records:
            if rec.get("code") == str(code) and rec.get("used_order_id") == PENDING:
                rec["used_order_id"] = ""
                rec["used_at"] = ""
                _save(records)


def release_for_order(order_id):
    """ออเดอร์ที่ใช้โค้ดถูกยกเลิก -> คืนโค้ด (ถ้าหมดอายุไปแล้ว ก็หมดอายุตามปกติ)"""
    with _lock:
        records = _load()
        changed = False
        for rec in records:
            if rec.get("used_order_id") == order_id:
                rec["used_order_id"] = ""
                rec["used_at"] = ""
                changed = True
        if changed:
            _save(records)
        return changed


# ---------- สรุปไว้แสดงผล ----------

def _expires_text(rec):
    expires = _parse(rec.get("expires_at"))
    return expires.strftime("%d/%m/%Y") if expires else ""


def summary(username):
    """ข้อมูลสำหรับการ์ดสมาชิก (ตะกร้า/ประวัติ)"""
    spend = delivered_spend(username)
    every = config.MEMBER_REWARD_EVERY or 0
    enabled = bool(config.MEMBER_REWARD_ENABLED and every > 0)
    rec = active_code(username) if enabled else None
    progress = spend % every if enabled else 0
    return {
        "enabled": enabled,
        "spend": spend,
        "every": every,
        "to_next": round(every - progress, 2) if enabled else 0,
        "progress_pct": int(progress * 100 // every) if enabled else 0,
        "value": config.MEMBER_REWARD_BAHT,
        "min_order": config.MEMBER_REWARD_MIN_ORDER,
        "active": rec,
        "active_expires": _expires_text(rec) if rec else "",
    }


def issued_by(order_id, username):
    """โค้ดที่ออกให้เพราะออเดอร์นี้ส่งสำเร็จ (และยังใช้ได้) — ไว้โชว์ 'คุณได้รับสิทธิ์' ในหน้าสถานะ"""
    for rec in _load():
        if (rec.get("issued_by_order") == order_id and _same_user(rec.get("username"), username)
                and state(rec) == "active"):
            return dict(rec, expires_text=_expires_text(rec))
    return None


def all_codes():
    """รายการโค้ดทั้งหมดสำหรับแอดมิน (ใหม่สุดก่อน) พร้อมสถานะ"""
    out = []
    for rec in _load():
        row = dict(rec)
        row["state"] = state(rec)
        row["expires_text"] = _expires_text(rec)
        out.append(row)
    out.sort(key=lambda r: r.get("issued_at", ""), reverse=True)
    return out
