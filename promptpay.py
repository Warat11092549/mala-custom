# promptpay.py - สร้างข้อความ (payload) สำหรับ QR พร้อมเพย์ (ไม่มี print/input)


def crc16(text):
    """คำนวณค่าตรวจสอบ CRC16 ที่ท้าย payload (มาตรฐาน CCITT-FALSE)"""
    crc = 0xFFFF
    for byte in text.encode("ascii"):
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc = crc << 1
            crc &= 0xFFFF
    return format(crc, "04X")


def field(tag, value):
    """ประกอบ 1 ช่องข้อมูล = รหัส(2 หลัก) + ความยาว(2 หลัก) + ค่า"""
    return tag + str(len(value)).zfill(2) + value


def make_payload(phone, amount):
    """สร้าง payload พร้อมเพย์แบบระบุเบอร์โทรและจำนวนเงิน"""
    digits = "".join(ch for ch in phone if ch.isdigit())
    if digits.startswith("0"):
        digits = "66" + digits[1:]          # 0933189044 -> 66933189044
    target = "00" + digits                   # เติม 00 นำหน้า ให้ครบรูปแบบ 0066...

    merchant = field("00", "A000000677010111") + field("01", target)

    text = (
        field("00", "01")                    # เวอร์ชัน
        + field("01", "12")                  # 12 = QR แบบระบุยอด (ใช้ครั้งเดียว)
        + field("29", merchant)              # ข้อมูลบัญชีพร้อมเพย์
        + field("53", "764")                 # สกุลเงิน บาท
        + field("54", "{:.2f}".format(amount))
        + field("58", "TH")                  # ประเทศไทย
    )
    text += "6304"
    return text + crc16(text)

def make_qr_svg(payload):
    """แปลง payload เป็นภาพ QR แบบ SVG (ฝังลงในหน้าเว็บได้)"""
    import segno
    qr = segno.make(payload, error="m")
    return qr.svg_inline(scale=5, border=2)