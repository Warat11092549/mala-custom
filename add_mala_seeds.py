# add_mala_seeds.py - ตั้งตัวเลือก "เม็ดหม่าล่า" 2 แบบ: กรองเม็ดออก / ไม่กรองเม็ด (รันซ้ำได้)
# ใช้:  python add_mala_seeds.py   แล้วไปแก้ราคา/สต็อก ได้ที่หน้า admin "สต็อกสินค้า"
# หมายเหตุ: ตัวเลือกพวกนี้ไม่ใช่ของที่หมดจริง จึงตั้งสต็อกสูงไว้ และตั้งราคา 0 บาท (ถ้าจะคิดเงินเพิ่ม แก้ราคาในหน้า admin)

import storage

SAMPLES = [
    ("P041", "กรองเม็ดหม่าล่าออก", 0, "ไม่มีเม็ดในชาม กินง่าย ได้กลิ่นหอมและรสหม่าล่าครบ"),
    ("P042", "ไม่กรองเม็ดหม่าล่า", 0, "เม็ดหม่าล่าอยู่ในซุป ชาแบบดั้งเดิม (เคี้ยวเม็ดได้)"),
]
OLD_IDS = {"P043"}    # ตัวเลือกเก่า "ชามาก" ที่เลิกใช้แล้ว

products = [p for p in storage.load_products() if str(p["id"]) not in OLD_IDS]
by_id = {str(p["id"]): p for p in products}
added = 0
for pid, name, price, detail in SAMPLES:
    if pid in by_id:
        by_id[pid].update({"name": name, "price": price, "detail": detail,
                           "category": "เม็ดหม่าล่า", "available": True})
        if by_id[pid].get("stock", 0) < 1000:
            by_id[pid]["stock"] = 9999
        continue
    products.append({
        "id": pid, "name": name, "category": "เม็ดหม่าล่า", "price": price,
        "stock": 9999, "available": True, "image": "", "detail": detail, "tag": "seed",
    })
    added += 1
storage.save_products(products)
print(f"ตั้งค่าตัวเลือกเม็ดหม่าล่าเรียบร้อย (เพิ่มใหม่ {added} รายการ)")
