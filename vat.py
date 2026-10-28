# vat.py - คำนวณ VAT แบบ "รวมอยู่ในราคาแล้ว" (VAT Included) — ไม่มี print/input
# ทุกหน้าที่แสดงหรือบันทึก VAT ต้องเรียกที่นี่ที่เดียว ห้ามคิดสูตรเองในหน้าอื่น
#
# กติกา (ตั้งค่าที่ config.py: VAT_ENABLED / VAT_RATE / VAT_DEMO_MODE)
#   * ราคาที่ลูกค้าเห็น = ราคาที่ลูกค้าจ่าย (รวม VAT แล้ว) ไม่บวก VAT เพิ่มเข้าไปในยอดชำระ
#   * VAT ที่รวมอยู่ = ค่าอาหารหลังหักส่วนลด x อัตรา / (100 + อัตรา)   (7% -> x 7/107)
#     ปัดสตางค์แบบครึ่งขึ้นด้วย Decimal ไม่ใช้ float ตรง ๆ
#   * มูลค่าก่อน VAT = ค่าอาหารหลังหักส่วนลด - VAT  (ลบจากตัวเลขที่ปัดแล้ว จึงบวกกลับได้ตรงเป๊ะ)
#   * ไม่คิด VAT บนค่าจัดส่ง · ยอดชำระสุทธิ = ค่าอาหารหลังหักส่วนลด + ค่าจัดส่ง
#   * ปิด VAT (หรืออัตราผิดปกติ) -> VAT = 0 ยอดชำระเท่าเดิมทุกประการ

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

import config

_CENT = Decimal("0.01")


def _dec(value):
    """แปลงเป็น Decimal อย่างปลอดภัย (ค่าแปลก ๆ = 0, ไม่ติดลบ)"""
    try:
        number = Decimal(str(value if value is not None else 0))
    except (InvalidOperation, ValueError):
        return Decimal("0")
    if not number.is_finite() or number < 0:
        return Decimal("0")
    return number


def _money(number):
    return float(number.quantize(_CENT, rounding=ROUND_HALF_UP))


def current_rate():
    """อัตรา VAT ที่ใช้อยู่ตอนนี้ (Decimal) คืน None ถ้าปิดอยู่/ตั้งค่าผิด"""
    if not getattr(config, "VAT_ENABLED", False):
        return None
    try:
        rate = Decimal(str(getattr(config, "VAT_RATE", 7)))
    except (InvalidOperation, ValueError):
        return None
    if not rate.is_finite() or not (0 <= rate <= 30):
        return None
    return rate


def config_view():
    """ข้อมูลให้ template ทุกหน้าใช้ (ส่งผ่าน context processor เป็นตัวแปร vat_cfg)"""
    rate = current_rate()
    enabled = rate is not None
    demo = enabled and bool(getattr(config, "VAT_DEMO_MODE", True))
    return {
        "enabled": enabled,
        "mode": "included",
        "rate": float(rate) if enabled else 0.0,
        "demo": demo,
        "notice": getattr(config, "VAT_DEMO_NOTICE", "") if demo else "",   # แสดงเฉพาะตอนเปิด VAT + โหมดจำลอง
        "notice_text": getattr(config, "VAT_DEMO_NOTICE", ""),              # ข้อความเฉย ๆ (หน้าออเดอร์ที่คิด VAT จำลองไว้ใช้)
    }


def calculate(food_total, fee=0):
    """แยก VAT ที่รวมอยู่ในค่าอาหารหลังหักส่วนลด (food_total) และรวมค่าส่ง (fee) เป็นยอดชำระ

    คืน dict:
      enabled, mode ("included"), rate, demo
      base            ค่าอาหารหลังหักส่วนลด (รวม VAT) = ฐานที่ใช้แยก VAT
      vat_amount      VAT ที่รวมอยู่ในราคา
      subtotal_ex_vat มูลค่าก่อน VAT (base - vat_amount)
      food_with_vat   = base (คงไว้ให้ template เดิม — ไม่ได้บวก VAT เพิ่ม)
      fee             ค่าส่ง (ไม่อยู่ในฐาน VAT)
      grand_total     ยอดชำระสุทธิ = base + fee
    """
    base = _dec(food_total).quantize(_CENT, rounding=ROUND_HALF_UP)
    delivery = _dec(fee).quantize(_CENT, rounding=ROUND_HALF_UP)
    cfg = config_view()
    rate = current_rate()
    if rate is not None:
        vat_amount = (base * rate / (Decimal(100) + rate)).quantize(_CENT, rounding=ROUND_HALF_UP)
    else:
        vat_amount = Decimal("0")
    return {
        "enabled": cfg["enabled"],
        "mode": "included",
        "rate": cfg["rate"],
        "demo": cfg["demo"],
        "base": _money(base),
        "vat_amount": _money(vat_amount),
        "subtotal_ex_vat": _money(base - vat_amount),
        "food_with_vat": _money(base),
        "fee": _money(delivery),
        "grand_total": _money(base + delivery),
    }
