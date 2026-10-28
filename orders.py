# orders.py - สร้างออเดอร์ ตัดสต็อก และจัดการสลิป (ไม่มี print/input)

import os
import time
import secrets
import datetime
import storage
import cart
import auth
import config

# สถานะออเดอร์ (เก็บเป็นตัวเลข แล้วแปลงเป็นข้อความตอนแสดงผล)
STATUS_NAMES = {
    1: "รอชำระเงิน",
    2: "รอตรวจสอบการโอนเงิน",
    3: "ร้านกำลังจัดเตรียม",
    4: "กำลังจัดส่ง",
    5: "จัดส่งสำเร็จ",
    9: "ยกเลิก",
}

# โฟลเดอร์เก็บสลิป (อยู่นอกโฟลเดอร์ static เพื่อไม่ให้ใครเปิดดูตรง ๆ ได้)
SLIP_FOLDER = os.path.join(os.path.dirname(__file__), "uploads", "slips")
os.makedirs(SLIP_FOLDER, exist_ok=True)


def load_orders():
    """อ่านออเดอร์ทั้งหมด"""
    return storage.load_json("orders.json")


def save_orders(all_orders):
    """บันทึกออเดอร์ทั้งหมด"""
    storage.save_json("orders.json", all_orders)


def next_order_id():
    """สร้างเลขออเดอร์ใหม่ เช่น MZ0001 (นับต่อจากเลข MZ สูงสุดที่มีอยู่)"""
    highest = 0
    existing = set()
    for order in load_orders():
        oid = str(order.get("order_id", ""))
        existing.add(oid)
        if oid.startswith("MZ") and oid[2:].isdigit():
            highest = max(highest, int(oid[2:]))
    number = highest + 1
    while "MZ" + str(number).zfill(4) in existing:    # กันเหนียว ไม่ให้ซ้ำกับของเดิม
        number += 1
    return "MZ" + str(number).zfill(4)


def find_order(order_id):
    """หาออเดอร์จากเลขออเดอร์ ไม่เจอคืน None"""
    for order in load_orders():
        if order["order_id"] == order_id:
            return order
    return None


def update_order(order):
  """บันทึกการเปลี่ยนแปลงของออเดอร์ 1 รายการลงไฟล์ orders.json"""
  all_orders = load_orders()
  target_id = str(order.get("order_id") or order.get("id", "")).strip()
  updated = False

  for i in range(len(all_orders)):
    curr_id = str(
        all_orders[i].get("order_id") or all_orders[i].get("id", "")
    ).strip()
    if curr_id == target_id:
      all_orders[i] = order
      updated = True
      break

  if updated:
    save_orders(all_orders)



def check_stock(cart_data):
    """ตรวจสต็อกก่อนสั่ง คืน list ข้อความปัญหา (ถ้าไม่มีปัญหาจะเป็น list ว่าง)"""
    problems = []
    for product_id, qty in cart_data.items():
        p = cart.find_product(product_id)
        if p is None or not p["available"] or p["stock"] <= 0:
            name = p["name"] if p else product_id
            problems.append(f"{name} หมดแล้ว กรุณาลบออกจากตะกร้า")
        elif p["stock"] < qty:
            problems.append(f"{p['name']} เหลือเพียง {p['stock']} ชิ้น กรุณาลดจำนวน")
    return problems


def create_order(username, soup, spicy_level, spicy_name, items, pricing,
                 info, km, delivery_fee, grand_total, vat_info=None):
    """สร้างออเดอร์ใหม่ (สถานะรอชำระเงิน) และตัดสต็อก
    vat_info = ผลจาก vat.calculate() (VAT รวมอยู่ในราคา) ถ้าไม่ส่งมา = ไม่มี VAT
    ยอดชำระ (grand_total) ต้องเท่ากับ ค่าอาหารหลังส่วนลด + ค่าส่ง เสมอ — ไม่ตรง = หยุดก่อนตัดสต็อก"""
    vat_info = vat_info or {}
    vat_on = bool(vat_info.get("enabled"))
    expected_total = round(float(pricing["final_total"]) + float(delivery_fee), 2)
    if abs(float(grand_total) - expected_total) > 0.005:
        raise ValueError(f"ยอดชำระไม่ตรงกับค่าอาหาร+ค่าส่ง ({grand_total} != {expected_total})")
    # 1) ตัดสต็อก
    products = storage.load_products()
    for p in products:
        for item in items:
            if p["id"] == item["id"]:
                p["stock"] -= item["qty"]
    storage.save_products(products)

    # 2) บันทึกออเดอร์
    order = {
        "order_id": next_order_id(),
        "username": username,
        "customer_name": info["name"],
        "phone": info["phone"],
        "address": info.get("address", ""),
        "note": info.get("note", ""),
        "lat": info["lat"],
        "lng": info["lng"],
        "km": km,
        "delivery_fee": delivery_fee,
        "soup": {"id": soup["id"], "name": soup["name"], "price": soup["price"]},
        "spicy_level": spicy_level,
        "spicy_name": spicy_name,
        "lines": items,
        "subtotal": pricing["subtotal"],
        "tier_percent": pricing["tier_percent"],
        "tier_discount": pricing["tier_discount"],
        "coupon_code": pricing["coupon_code"],
        "coupon_discount": pricing["coupon_discount"],
        "member_code": pricing.get("member_code", ""),            # โค้ดสมาชิกที่ใช้ (ว่าง = ไม่ได้ใช้)
        "member_discount": pricing.get("member_discount", 0),
        "food_total": pricing["final_total"],       # ค่าอาหารหลังหักส่วนลด (ไม่รวมค่าส่ง) — แต้ม/โค้ดสมาชิกนับจากค่านี้
        # VAT แบบรวมอยู่ในราคา (vat_mode = "included"): เก็บค่าไว้กับออเดอร์ ถ้าแก้ราคา/config ภายหลังยอดไม่เปลี่ยน
        #   food_total (รวม VAT) = subtotal_ex_vat + vat_amount   และ   total = food_total + delivery_fee
        # ออเดอร์เก่าที่บวก VAT เพิ่มไม่มีคีย์ vat_mode (อ่านเป็น "added": total = food_total + vat_amount + delivery_fee)
        "vat_enabled": vat_on,
        "vat_mode": "included" if vat_on else "",
        "vat_rate": vat_info.get("rate", 0) if vat_on else 0,
        "vat_base": vat_info.get("base", pricing["final_total"]) if vat_on else 0,       # ฐานคิด VAT = ค่าอาหารหลังส่วนลด (รวม VAT)
        "subtotal_ex_vat": vat_info.get("subtotal_ex_vat", pricing["final_total"]) if vat_on else 0,
        "vat_amount": vat_info.get("vat_amount", 0) if vat_on else 0,
        "vat_demo": bool(vat_info.get("demo")) if vat_on else False,
        "total": grand_total,
        "status": 1,
        "slip": "",
        "slip_note": "",
        "points_earned": int(pricing["final_total"] // 10),   # ทุก 10 บาท = 1 คะแนน
        "points_given": False,                                 # จะให้คะแนนหลังตรวจสลิปผ่าน
        "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "expires_at": new_deadline(),     # หมดเวลาชำระเงินเมื่อไหร่ (เกินแล้วระบบยกเลิกเอง)
    }

    all_orders = load_orders()
    all_orders.append(order)
    save_orders(all_orders)
    return order


def detect_image_type(head):
    """ดูจากหัวไฟล์ว่าเป็นรูปภาพชนิดไหน (ไม่เชื่อนามสกุลไฟล์) ไม่ใช่รูปคืน None"""
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def save_slip(order, file):
    """บันทึกสลิปที่ลูกค้าอัปโหลด คืนค่า (สำเร็จไหม, ข้อความ)"""
    if file is None or file.filename == "":
        return False, "กรุณาเลือกไฟล์สลิปก่อน"

    head = file.read(12)    # อ่านหัวไฟล์ไว้ตรวจชนิด
    file.seek(0)            # ย้อนกลับไปต้นไฟล์ก่อนบันทึก
    ext = detect_image_type(head)
    if ext is None:
        return False, ("รองรับเฉพาะรูปภาพ JPG, PNG, WEBP "
                       "(ถ้าเป็นรูปแบบอื่น ให้แคปหน้าจอสลิปแล้วแนบแทน)")

    # ตั้งชื่อไฟล์เอง ไม่ใช้ชื่อที่ลูกค้าส่งมา
    # ต่อท้ายด้วยเลขสุ่ม: กดส่งซ้ำในวินาทีเดียวกันก็ได้ชื่อไม่ซ้ำกัน (เดิมชื่อซ้ำ -> ลบสลิปใหม่ทิ้งเอง)
    stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"{order['order_id']}_{stamp}_{secrets.token_hex(3)}.{ext}"
    new_path = os.path.join(SLIP_FOLDER, filename)
    file.save(new_path)

    # อ่านออเดอร์ล่าสุดจากไฟล์ใหม่อีกรอบ (กันกรณีกดซ้ำ/ถูกยกเลิกระหว่างอัปโหลด)
    current = find_order(order["order_id"]) or order
    if get_status(current) not in (1, 2):
        os.remove(new_path)
        return False, "ออเดอร์นี้ถูกยกเลิกหรือปิดแล้ว ส่งสลิปไม่ได้"

    # ลบสลิปเก่า (ถ้าเคยแนบมาแล้ว) — ต้องไม่ใช่ไฟล์ใหม่ที่เพิ่งบันทึก
    old = current.get("slip", "")
    if old and os.path.basename(old) != filename:
        old_path = os.path.join(SLIP_FOLDER, os.path.basename(old))
        if os.path.exists(old_path):
            os.remove(old_path)

    current["slip"] = filename
    current["slip_note"] = ""
    current["status"] = 2     # รอตรวจสอบการโอนเงิน
    update_order(current)
    return True, "ส่งสลิปเรียบร้อย รอร้านตรวจสอบการโอนเงินนะ"


# ---------- เวลาหมดอายุของออเดอร์ที่ยังไม่ชำระ ----------

_DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M")


def new_deadline():
    """เวลาหมดอายุชำระเงินของออเดอร์ใหม่ (ข้อความ) นับจากตอนนี้"""
    limit = datetime.datetime.now() + datetime.timedelta(minutes=config.PAYMENT_TIMEOUT_MINUTES)
    return limit.strftime("%Y-%m-%d %H:%M:%S")


def _parse_time(text):
    for fmt in _DATE_FORMATS:
        try:
            return datetime.datetime.strptime(str(text), fmt)
        except (ValueError, TypeError):
            continue
    return None


def payment_deadline(order):
    """เวลาที่ออเดอร์ต้องชำระภายใน (datetime) — ออเดอร์เก่าที่ไม่มี expires_at คิดจากวันที่สั่ง
    อ่านเวลาไม่ได้คืน None (ถือว่าไม่หมดอายุ)"""
    deadline = _parse_time(order.get("expires_at"))
    if deadline:
        return deadline
    created = _parse_time(order.get("date") or order.get("created_at"))
    if created:
        return created + datetime.timedelta(minutes=config.PAYMENT_TIMEOUT_MINUTES)
    return None


def seconds_left(order):
    """เหลือเวลาชำระกี่วินาที (ไม่มีกำหนด/ไม่ใช่สถานะ 1 คืน None)"""
    if get_status(order) != 1:
        return None
    deadline = payment_deadline(order)
    if deadline is None:
        return None
    return int((deadline - datetime.datetime.now()).total_seconds())


_last_sweep = 0.0


def expire_unpaid_orders(force=False):
    """ยกเลิกออเดอร์สถานะ 1 ที่เกินเวลาชำระ + คืนสต็อก คืนจำนวนที่ยกเลิก
    เรียกจาก app ทุก request แต่ตรวจจริงไม่เกิน 1 ครั้งต่อ 15 วินาที (force=True = ตรวจทันที)"""
    global _last_sweep
    now = time.time()
    if not force and now - _last_sweep < 15:
        return 0
    _last_sweep = now

    count = 0
    for order in load_orders():
        left = seconds_left(order)
        if left is not None and left <= 0:
            ok, _ = apply_action(order, "cancel", "หมดเวลาชำระเงิน ระบบยกเลิกอัตโนมัติ")
            if ok:
                count += 1
    return count


def count_unpaid(username):
    """นับออเดอร์ของลูกค้าที่ยังไม่ชำระ (สถานะ 1)"""
    return sum(1 for o in load_orders()
               if o.get("username") == username and get_status(o) == 1)


def cancel_by_customer(order, username):
    """ลูกค้ายกเลิกออเดอร์ของตัวเอง — ทำได้เฉพาะที่ยังไม่ส่งสลิป (สถานะ 1)
    คืนค่า (สำเร็จไหม, ข้อความ)"""
    if order is None or order.get("username") != username:
        return False, "ไม่พบออเดอร์นี้"
    if get_status(order) != 1:
        return False, "ยกเลิกเองได้เฉพาะออเดอร์ที่ยังไม่ได้ส่งสลิป ถ้าโอนเงินไปแล้วกรุณาติดต่อร้าน"
    return apply_action(order, "cancel", "ลูกค้ายกเลิกเอง")


def order_lines(order):
    """คืนรายการสินค้าของออเดอร์ ไม่ว่าจะเก็บไว้ใต้คีย์ lines / items / item_list"""
    for key in ("lines", "items", "item_list"):
        value = order.get(key)
        if isinstance(value, list) and value:
            return value
    return []


def restore_stock(order):
    """คืนสต็อกสินค้าตามรายการในออเดอร์ (ใช้ตอนยกเลิก)"""
    products = storage.load_products()
    for p in products:
        for line in order_lines(order):
            if str(p["id"]) == str(line.get("id")):
                p["stock"] += int(line.get("qty", 0))
    storage.save_products(products)


def delete_slip_file(order):
    """ลบไฟล์สลิปของออเดอร์ (ถ้ามี) แล้วเคลียร์ชื่อไฟล์ในออเดอร์"""
    name = order.get("slip", "")
    if name:
        path = os.path.join(SLIP_FOLDER, os.path.basename(name))
        if os.path.exists(path):
            os.remove(path)
    order["slip"] = ""


CANCELLED = 9          # สถานะ "ยกเลิก" ที่ทั้งระบบใช้ (STATUS_NAMES / template / admin)
LEGACY_CANCELLED = -1  # ค่าเก่าที่เคยถูกใช้ผิด ให้แปลงเป็น 9 เสมอ

# ชื่อ action ที่ฟอร์ม/หน้า admin อาจส่งมา -> ชื่อมาตรฐาน
ACTION_ALIASES = {
    "approve": "approve", "confirm": "approve", "preparing": "approve",
    "reject": "reject",
    "deliver": "deliver", "delivering": "deliver",
    "done": "done", "complete": "done", "completed": "done", "finish": "done",
    "cancel": "cancel", "void": "cancel",
}


def get_status(order):
    """อ่านสถานะของออเดอร์เป็นตัวเลขเสมอ (และแปลง -1 เก่าเป็น 9)"""
    try:
        status = int(order.get("status", 1))
    except (ValueError, TypeError):
        status = 1
    if status == LEGACY_CANCELLED:
        status = CANCELLED
    return status


def apply_action(order, action, note=""):
    """
    ให้ admin เปลี่ยนสถานะออเดอร์ แล้วบันทึกลง orders.json ทันที
    คืนค่า (สำเร็จไหม, ข้อความ)

    ลำดับสถานะ:  1 รอชำระ -> 2 รอตรวจสลิป -> 3 เตรียมอาหาร -> 4 กำลังส่ง -> 5 สำเร็จ   (9 = ยกเลิก)
      approve : 2 -> 3   (ให้แต้มสะสมครั้งเดียว)
      reject  : 2 -> 1   (ลบสลิป + บันทึกเหตุผลลง slip_note ไม่ยุ่งกับหมายเหตุของลูกค้า)
      deliver : 3 -> 4
      done    : 4 -> 5
      cancel  : 1,2,3,4 -> 9 (คืนสต็อก และหักแต้มคืนถ้าเคยให้ไปแล้ว)
    """
    status = get_status(order)
    action = ACTION_ALIASES.get(str(action).strip().lower())
    note = (note or "").strip()

    if action is None:
        return False, "ไม่รู้จักคำสั่งนี้"

    if status in (5, CANCELLED):
        return False, "ออเดอร์นี้ปิดงานแล้ว เปลี่ยนสถานะอีกไม่ได้"

    if action == "approve" and status == 2:
        order["status"] = 3
        order["slip_note"] = ""
        message = "อนุมัติสลิปแล้ว ออเดอร์เข้าสู่ขั้นตอนเตรียมอาหาร"
        # ให้คะแนนสะสมครั้งเดียว ตอนอนุมัติสลิป (ติ๊กว่าให้แล้วเฉพาะเมื่อบันทึกแต้มสำเร็จ)
        if not order.get("points_given"):
            try:
                auth.add_points(order["username"], order.get("points_earned", 0))
                order["points_given"] = True
            except Exception:
                message += " (แต่บันทึกแต้มสะสมไม่สำเร็จ กรุณาตรวจ users.json)"

    elif action == "reject" and status == 2:
        delete_slip_file(order)
        order["status"] = 1
        order["slip_note"] = note or "สลิปไม่ถูกต้อง กรุณาแนบสลิปใหม่"
        order["expires_at"] = new_deadline()    # ให้เวลาลูกค้าส่งสลิปใหม่ ไม่งั้นโดนยกเลิกทันทีเพราะเวลาเก่าหมด
        message = "แจ้งสลิปไม่ผ่านแล้ว ลูกค้าจะเห็นเหตุผลและแนบสลิปใหม่ได้"

    elif action == "deliver" and status == 3:
        order["status"] = 4
        message = "เปลี่ยนสถานะเป็นกำลังจัดส่ง"

    elif action == "done" and status == 4:
        order["status"] = 5
        message = "จัดส่งสำเร็จ ปิดออเดอร์เรียบร้อย"

    elif action == "cancel" and status in (1, 2, 3, 4):
        restore_stock(order)
        # ถ้าเคยให้คะแนนไปแล้ว ให้หักคืน
        if order.get("points_given"):
            try:
                auth.add_points(order["username"], -order.get("points_earned", 0))
                order["points_given"] = False
            except Exception:
                pass
        order["status"] = CANCELLED
        try:
            import member_codes                      # import ตรงนี้กัน circular import
            member_codes.release_for_order(order["order_id"])   # ออเดอร์ที่ใช้โค้ดสมาชิกถูกยกเลิก -> คืนโค้ด
        except Exception:
            pass
        if note:
            order["cancel_note"] = note      # เหตุผลการยกเลิก (ไม่ยุ่งกับ note ของลูกค้า)
        message = "ยกเลิกออเดอร์แล้ว และคืนสต็อกสินค้าเรียบร้อย"

    else:
        name = STATUS_NAMES.get(status, status)
        return False, f"ทำรายการนี้ไม่ได้ในสถานะปัจจุบัน ({name})"

    update_order(order)    # <- ต้องบันทึกเสมอ ไม่งั้นสถานะไม่เปลี่ยนจริง

    if action == "done":
        # จัดส่งสำเร็จ = ยอดสะสมเพิ่ม -> ถ้าครบเกณฑ์ ออกโค้ดสมาชิกให้ (ล้มเหลวต้องไม่กระทบการเปลี่ยนสถานะ)
        try:
            import member_codes
            member_codes.issue_if_earned(order["username"], order["order_id"])
        except Exception:
            pass
    return True, message
