# settings.py - ค่าตั้งที่แอดมินแก้ได้จากหน้าเว็บ (เก็บใน data/settings.json)
#   shop_mode   : "auto" = เปิด-ปิดตามเวลาใน config.py | "closed" = ปิดร้านชั่วคราว | "open" = บังคับเปิดนอกเวลา
#   closed_note : ข้อความที่ลูกค้าเห็นตอนปิดร้านชั่วคราว (เช่น "กลับมา 18:00 น.")
#   promo       : แถบประกาศโปรโมชันหน้าแรก {enabled, text}
# ไฟล์หาย/พัง -> ใช้ค่าเริ่มต้น (เปิดตามเวลา ไม่มีแถบประกาศ) ไม่ทำให้เว็บล่ม

import config
import storage

FILENAME = "settings.json"
SHOP_MODES = ("auto", "closed", "open")


def _defaults():
    return {"shop_mode": "auto", "closed_note": "", "promo": {"enabled": False, "text": ""},
            "receipt": {"legal_name": "", "tax_id": "", "branch": "", "address": "", "vat_registered": False, "vat_rate": 7}}


def load():
    data = _defaults()
    try:
        raw = storage.load_json(FILENAME)
    except (OSError, ValueError):
        return data
    if not isinstance(raw, dict):
        return data
    if raw.get("shop_mode") in SHOP_MODES:
        data["shop_mode"] = raw["shop_mode"]
    data["closed_note"] = str(raw.get("closed_note") or "")[:100]
    promo = raw.get("promo")
    if isinstance(promo, dict):
        data["promo"]["enabled"] = bool(promo.get("enabled"))
        data["promo"]["text"] = str(promo.get("text") or "")[:config.PROMO_BANNER_MAX]
    rc = raw.get("receipt")
    if isinstance(rc, dict):
        for key, limit in (("legal_name", 100), ("tax_id", 13), ("branch", 60), ("address", 200)):
            data["receipt"][key] = str(rc.get(key) or "")[:limit]
        data["receipt"]["vat_registered"] = bool(rc.get("vat_registered"))
        try:
            data["receipt"]["vat_rate"] = min(max(float(rc.get("vat_rate", 7)), 0), 30)
        except (TypeError, ValueError):
            pass
    return data


def save(data):
    storage.save_json(FILENAME, data)


def set_shop_mode(mode, note=""):
    """บันทึกโหมดเปิด-ปิดร้าน คืน (สำเร็จไหม, ข้อความ)"""
    if mode not in SHOP_MODES:
        return False, "โหมดไม่ถูกต้อง"
    data = load()
    data["shop_mode"] = mode
    data["closed_note"] = (note or "").strip()[:100] if mode == "closed" else ""
    save(data)
    return True, {"auto": "ตั้งให้ร้านเปิด-ปิดตามเวลาทำการแล้ว",
                  "closed": "ปิดร้านชั่วคราวแล้ว ลูกค้ายังดูเมนูได้แต่สั่งซื้อไม่ได้",
                  "open": "เปิดร้านนอกเวลาแล้ว (ปิดเองเมื่อไม่ต้องการรับออเดอร์)"}[mode]


def set_promo(enabled, text):
    """บันทึกแถบประกาศโปรโมชัน คืน (สำเร็จไหม, ข้อความ)"""
    text = " ".join((text or "").split())      # ตัดช่องว่าง/ขึ้นบรรทัดซ้ำ
    if len(text) > config.PROMO_BANNER_MAX:
        return False, f"ข้อความยาวเกินไป (ไม่เกิน {config.PROMO_BANNER_MAX} ตัวอักษร)"
    if enabled and not text:
        return False, "กรุณาพิมพ์ข้อความประกาศก่อนเปิดแสดง"
    data = load()
    data["promo"] = {"enabled": bool(enabled), "text": text}
    save(data)
    return True, "บันทึกประกาศแล้ว" if enabled else "ซ่อนแถบประกาศแล้ว"


def promo_banner():
    """ประกาศที่จะโชว์หน้าแรก คืน dict {enabled, text} (enabled=True เมื่อมีข้อความจริง)"""
    promo = load()["promo"]
    return {"enabled": bool(promo["enabled"] and promo["text"]), "text": promo["text"]}


def set_receipt(form):
    """บันทึกข้อมูลผู้ขายบนใบเสร็จ/VAT คืน (สำเร็จไหม, ข้อความ)"""
    one = lambda k, n: " ".join(str(form.get(k, "")).split())[:n]
    tax_id = "".join(ch for ch in str(form.get("tax_id", "")) if ch.isdigit())
    vat_on = form.get("vat_registered") == "on"
    try:
        rate = float(form.get("vat_rate") or 7)
    except ValueError:
        return False, "อัตรา VAT ต้องเป็นตัวเลข"
    if not 0 <= rate <= 30:
        return False, "อัตรา VAT ต้องอยู่ระหว่าง 0-30"
    if tax_id and len(tax_id) != 13:
        return False, "เลขประจำตัวผู้เสียภาษีต้องมี 13 หลัก"
    if vat_on and not tax_id:
        return False, "ร้านที่จด VAT ต้องกรอกเลขประจำตัวผู้เสียภาษี 13 หลัก"
    data = load()
    data["receipt"] = {"legal_name": one("legal_name", 100), "tax_id": tax_id, "branch": one("branch", 60),
                       "address": one("address", 200), "vat_registered": vat_on, "vat_rate": rate}
    save(data)
    return True, "บันทึกข้อมูลใบเสร็จแล้ว"


def receipt_info():
    """ข้อมูลผู้ขายสำหรับใบเสร็จ: ช่องที่ว่างใช้ค่าจาก config.py แทน"""
    rc = load()["receipt"]
    return {
        "name": rc["legal_name"] or config.SHOP_NAME,
        "tax_id": rc["tax_id"],
        "branch": rc["branch"] or ("สำนักงานใหญ่" if rc["tax_id"] else ""),
        "address": rc["address"] or config.SHOP_ADDRESS,
        "vat_registered": rc["vat_registered"],
        "vat_rate": rc["vat_rate"],
    }
