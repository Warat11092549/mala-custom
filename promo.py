# promo.py - คำนวณส่วนลดและโปรโมชั่น (ไม่มี print/input)

import config

# ส่วนลดตามยอด: (ยอดขั้นต่ำ, เปอร์เซ็นต์ที่ลด) เรียงจากมากไปน้อย
TIERS = [
    (200, 10),
    (100, 5),
]

# คูปอง: ชื่อโค้ด -> รายละเอียด
COUPONS = {
    "MALA10": {"type": "baht", "value": 10, "min": 50,
               "detail": "ลด 10 บาท เมื่อครบ 50 บาท"},
    "SPICY15": {"type": "percent", "value": 15, "min": 100,
                "detail": "ลด 15% เมื่อครบ 100 บาท"},
}


def get_tier_percent(subtotal):
    """คืนเปอร์เซ็นต์ส่วนลดตามยอด (0 ถ้ายังไม่ถึง)"""
    for min_amount, percent in TIERS:
        if subtotal >= min_amount:
            return percent
    return 0


def get_next_tier_hint(subtotal):
    """บอกว่าซื้อเพิ่มอีกเท่าไรจะได้ส่วนลดขั้นถัดไป"""
    # reversed = วนจากขั้นเล็กไปขั้นใหญ่
    for min_amount, percent in reversed(TIERS):
        if subtotal < min_amount:
            return f"ซื้ออีก {min_amount - subtotal} บาท ลด {percent}%"
    return ""


def calculate_discount(subtotal, coupon_code=None, member_reward=None):
    """คำนวณส่วนลดทั้งหมด คืนค่าเป็น dictionary

    ลำดับ: ส่วนลดตามยอด -> คูปอง -> สิทธิ์สมาชิก (ลดสูงสุด 2 ชั้น)
    member_reward = {"code", "value", "min"} ที่ผ่านการตรวจโค้ดฝั่งเซิร์ฟเวอร์แล้ว (promo.py ไม่อ่านไฟล์เอง)
    กติกา: สิทธิ์สมาชิกซ้อนกับส่วนลดตามยอดได้เสมอ ส่วนคูปองซ้อนได้ก็ต่อเมื่อ config.MEMBER_CODE_STACK_WITH_COUPON
    ถ้าซ้อนไม่ได้และสิทธิ์สมาชิกใช้งานได้จริง (ยอดถึงขั้นต่ำ) -> ใช้สิทธิ์สมาชิก ไม่คิดคูปอง
    """
    # 1) ส่วนลดตามยอด
    tier_percent = get_tier_percent(subtotal)
    tier_discount = subtotal * tier_percent / 100
    after_tier = subtotal - tier_discount

    # 3) สิทธิ์สมาชิกใช้งานได้ไหม (เช็คก่อน เพราะมีผลกับคูปอง)
    member_applies = False
    member_note = ""
    if member_reward:
        if subtotal >= member_reward["min"]:
            member_applies = True
        else:
            member_note = f"ยอดยังไม่ถึงขั้นต่ำ {member_reward['min']:g} บาท สิทธิ์สมาชิกจึงยังไม่ถูกใช้"

    # 2) ส่วนลดคูปอง (คิดจากยอดที่เหลือหลังหักส่วนลดตามยอด)
    coupon_discount = 0
    coupon_note = ""
    if coupon_code in COUPONS:
        coupon = COUPONS[coupon_code]
        if member_applies and not config.MEMBER_CODE_STACK_WITH_COUPON:
            coupon_note = "คูปองใช้ร่วมกับสิทธิ์สมาชิกไม่ได้ จึงยังไม่ถูกใช้"
        elif subtotal >= coupon["min"]:
            if coupon["type"] == "percent":
                coupon_discount = after_tier * coupon["value"] / 100
            else:
                coupon_discount = coupon["value"]
            # ส่วนลดต้องไม่เกินยอดที่เหลือ (กันยอดติดลบ)
            if coupon_discount > after_tier:
                coupon_discount = after_tier
        else:
            coupon_note = f"ยอดยังไม่ถึงขั้นต่ำ {coupon['min']} บาท คูปองจึงยังไม่ถูกใช้"

    # 3) สิทธิ์สมาชิก (ลดเป็นบาทคงที่ ไม่เกินยอดที่เหลือ)
    after_coupon = after_tier - coupon_discount
    member_discount = 0
    if member_applies:
        member_discount = min(float(member_reward["value"]), after_coupon)

    final_total = after_coupon - member_discount

    return {
        "subtotal": subtotal,
        "tier_percent": tier_percent,
        "tier_discount": round(tier_discount, 2),
        "coupon_code": coupon_code,
        "coupon_discount": round(coupon_discount, 2),
        "coupon_note": coupon_note,
        "member_selected": bool(member_reward),
        "member_code": member_reward["code"] if member_applies else "",
        "member_discount": round(member_discount, 2),
        "member_note": member_note,
        "final_total": round(final_total, 2),
        "hint": get_next_tier_hint(subtotal),
    }
