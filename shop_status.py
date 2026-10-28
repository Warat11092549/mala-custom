# shop_status.py - ร้านเปิดหรือปิดอยู่ตอนนี้ (ไม่มี print/input)
# ลำดับการตัดสิน: ปิดชั่วคราวโดยแอดมิน > บังคับเปิดโดยแอดมิน > เวลาทำการใน config.py
# ฟังก์ชัน get_status(now=...) รับเวลาจากภายนอกได้ เพื่อให้ทดสอบได้โดยไม่ต้องรอเวลาจริง

from datetime import datetime, time, timedelta, timezone

import config
import settings

WEEKDAYS_TH = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]


def now_shop():
    """เวลาปัจจุบันตามเขตเวลาร้าน (UTC+7)"""
    return datetime.now(timezone(timedelta(hours=config.SHOP_UTC_OFFSET)))


def _parse_hhmm(text):
    hour, minute = str(text).strip().split(":")
    return time(int(hour), int(minute))


def _hours():
    """คืน (เวลาเปิด, เวลาปิด) หรือ None ถ้าไม่จำกัดเวลา / ตั้งค่าผิดรูปแบบ
    ตั้งค่าผิด -> ถือว่าไม่จำกัดเวลา (เปิดตลอด) แทนที่จะล็อกร้านปิดทั้งที่เจ้าของพิมพ์ผิด และแจ้งเตือนในหน้าตั้งค่า"""
    if not config.OPEN_TIME or not config.CLOSE_TIME:
        return None
    try:
        return _parse_hhmm(config.OPEN_TIME), _parse_hhmm(config.CLOSE_TIME)
    except (ValueError, TypeError):
        return None


def hours_config_error():
    """ข้อความเตือนถ้า OPEN_TIME/CLOSE_TIME ตั้งผิดรูปแบบ (ไม่ผิดคืนค่าว่าง)"""
    if config.OPEN_TIME or config.CLOSE_TIME:
        if _hours() is None:
            return "OPEN_TIME / CLOSE_TIME ใน config.py ต้องเป็นรูปแบบ HH:MM เช่น 10:00 — ตอนนี้ระบบจึงถือว่าร้านเปิดตลอด"
    return ""


def _windows(now):
    """ช่วงเวลาเปิดรับออเดอร์ตั้งแต่เมื่อวานถึงอีก 8 วัน: list ของ (เวลาเปิด, เวลาหยุดรับ) เรียงตามเวลา"""
    hours = _hours()
    if hours is None:
        return []
    open_t, close_t = hours
    tz = now.tzinfo
    out = []
    for offset in range(-1, 9):
        day = now.date() + timedelta(days=offset)
        if day.weekday() in config.CLOSED_WEEKDAYS:
            continue
        start = datetime.combine(day, open_t, tzinfo=tz)
        end = datetime.combine(day, close_t, tzinfo=tz)
        if end <= start:                      # ข้ามเที่ยงคืน
            end += timedelta(days=1)
        end -= timedelta(minutes=max(0, int(config.LAST_ORDER_BEFORE_CLOSE_MIN or 0)))
        if end > start:
            out.append((start, end))
    return out


def _day_label(now, when):
    diff = (when.date() - now.date()).days
    if diff == 0:
        return "วันนี้"
    if diff == 1:
        return "พรุ่งนี้"
    return "วัน" + WEEKDAYS_TH[when.weekday()]


def hours_text():
    hours = _hours()
    if hours is None:
        return "เปิดตลอด"
    text = f"{hours[0].strftime('%H:%M')}–{hours[1].strftime('%H:%M')} น."
    if config.CLOSED_WEEKDAYS:
        days = ", ".join(WEEKDAYS_TH[d] for d in sorted(set(config.CLOSED_WEEKDAYS)) if 0 <= d <= 6)
        text += f" (หยุดวัน{days})"
    return text


def get_status(now=None, settings_data=None):
    """สถานะร้านตอนนี้ คืน dict:
      open        True/False ร้านรับออเดอร์ได้ไหม
      reason      open | manual_open | manual_closed | outside_hours | day_off
      headline    ข้อความสั้นหัวแถบ/หัวการ์ด
      detail      ข้อความรอง (เวลาเปิดครั้งถัดไป / หมายเหตุจากร้าน)
      next_open   ข้อความ เช่น "วันนี้ 10:00 น." (ไม่ทราบ = ค่าว่าง)
      hours_text  เวลาทำการ
      mode        shop_mode ที่แอดมินตั้งไว้
    """
    now = now or now_shop()
    data = settings_data if settings_data is not None else settings.load()
    mode = data.get("shop_mode", "auto")
    result = {"open": True, "reason": "open", "headline": "ร้านเปิดอยู่", "detail": "",
              "next_open": "", "hours_text": hours_text(), "mode": mode,
              "closed_note": data.get("closed_note", "")}

    if mode == "closed":
        note = data.get("closed_note", "")
        result.update(open=False, reason="manual_closed", headline="ร้านปิดชั่วคราว",
                      detail=note or "กรุณารอร้านเปิดอีกครั้ง")
        return result

    if mode == "open":
        result.update(reason="manual_open", headline="ร้านเปิดอยู่")
        return result

    windows = _windows(now)
    if not windows:                                   # ไม่จำกัดเวลา (หรือตั้งค่าผิด) -> เปิดตลอด
        return result
    if any(start <= now < end for start, end in windows):
        return result

    upcoming = [start for start, _ in windows if start > now]
    reason = "day_off" if now.weekday() in config.CLOSED_WEEKDAYS else "outside_hours"
    result.update(open=False, reason=reason, headline="ร้านปิดอยู่ตอนนี้")
    if upcoming:
        when = upcoming[0]
        result["next_open"] = f"{_day_label(now, when)} {when.strftime('%H:%M')} น."
        result["detail"] = f"เปิดรับออเดอร์อีกครั้ง {result['next_open']}"
    else:
        result["detail"] = f"เวลาทำการ {result['hours_text']}"
    return result
