# delivery.py - คำนวณระยะทางและค่าส่ง (ไม่มี print/input)

import math
from config import SHOP_LAT, SHOP_LNG

FREE_KM = 5          # ส่งฟรีภายในกี่ กม.
RATE_PER_KM = 5      # ส่วนที่เกินคิดกิโลเมตรละกี่บาท
MAX_KM = 15          # ไกลสุดที่ส่งได้


def distance_km(lat1, lng1, lat2, lng2):
    """ระยะเส้นตรงระหว่างสองจุดบนโลก เป็นกิโลเมตร (สูตร Haversine)"""
    earth_radius = 6371    # รัศมีโลก กม.

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lng / 2) ** 2
    return earth_radius * 2 * math.asin(math.sqrt(a))


def calculate_delivery(lat, lng):
    """คำนวณระยะทางจากร้านถึงลูกค้า แล้วคืนค่าส่ง"""
    km = round(distance_km(SHOP_LAT, SHOP_LNG, lat, lng), 1)

    # ไกลเกินพื้นที่ส่ง
    if km > MAX_KM:
        return {"ok": False, "km": km, "fee": 0}

    extra = km - FREE_KM          # ระยะส่วนที่เกิน 5 กม.
    if extra <= 0:
        fee = 0
    else:
        fee = math.ceil(extra) * RATE_PER_KM    # ปัดขึ้นเป็นกิโลเมตรเต็ม แล้วคูณอัตรา

    return {"ok": True, "km": km, "fee": fee}