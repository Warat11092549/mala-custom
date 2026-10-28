# fix_data.py - ซ่อมข้อมูลให้ตรงกับโค้ด (รันซ้ำกี่ครั้งก็ได้ ปลอดภัย)
#
# วิธีใช้ (รันในโฟลเดอร์โปรเจกต์):   python fix_data.py
#
# สิ่งที่ทำ
#   1) รูปสินค้าที่ products.json ชี้ แต่ไม่มีไฟล์จริง -> หาไฟล์ที่ถูกต้องให้
#        - ไฟล์ที่ถูกตั้งชื่อเพี้ยนเป็น "jpg"/"png" (เกิดจาก secure_filename ตัดชื่อไทย) -> เปลี่ยนชื่อให้ตรงกับที่ JSON ระบุ
#        - ไฟล์ที่ตั้งชื่อตามรหัสสินค้า เช่น P020.jpg ในโฟลเดอร์อื่น -> แก้ JSON ให้ชี้ไปที่ไฟล์นั้น
#   2) หมวดหมู่สินค้าที่ไม่อยู่ใน config.PRODUCT_CATEGORIES (เช่น "meat", "เส้น/บุก") -> แปลงเป็นหมวดมาตรฐาน
#   3) ออเดอร์ที่สถานะเป็น -1 (ค่าเก่าที่ผิด) -> แก้เป็น 9 (ยกเลิก)
#   4) รายงาน (ไม่ลบให้) ไฟล์รูปที่ไม่มีสินค้าใช้ และรูปที่ยังหาไม่เจอ

import os

import config
import storage

BASE = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(BASE, "static", "images")
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")

# หมวดที่เคยสะกดต่างไป -> หมวดมาตรฐาน
CATEGORY_FIX = {"เส้น/บุก": "เส้น"}
for thai, folder in config.PRODUCT_CATEGORIES.items():
    CATEGORY_FIX[folder] = thai          # "meat" -> "เนื้อสัตว์" ฯลฯ

changes = []


def img_path(rel):
    return os.path.join(IMG_DIR, *rel.split("/"))


def find_by_id(product_id):
    """หาไฟล์รูปที่ชื่อ = รหัสสินค้า (เช่น P020.jpg) ในทุกโฟลเดอร์รูป"""
    for root, _, files in os.walk(IMG_DIR):
        for f in files:
            name, ext = os.path.splitext(f)
            if name == product_id and ext.lower() in IMG_EXT:
                rel = os.path.relpath(os.path.join(root, f), IMG_DIR)
                return rel.replace(os.sep, "/")
    return None


data = storage.load_json("products.json")

for item in data["products"] + data["soups"]:
    # --- (2) หมวดหมู่ ---
    cat = item.get("category")
    if cat in CATEGORY_FIX and cat not in config.PRODUCT_CATEGORIES:
        item["category"] = CATEGORY_FIX[cat]
        changes.append(f"{item['id']} {item['name']}: หมวด '{cat}' -> '{item['category']}'")

    # --- (1) รูปภาพ ---
    rel = item.get("image", "")
    if not rel or os.path.isfile(img_path(rel)):
        continue

    folder, _, wanted = rel.rpartition("/")
    ext = os.path.splitext(wanted)[1].lstrip(".").lower()
    broken = os.path.join(IMG_DIR, folder, ext) if folder and ext else None   # ไฟล์ชื่อ "jpg"

    if broken and os.path.isfile(broken):
        os.rename(broken, img_path(rel))
        changes.append(f"{item['id']} {item['name']}: เปลี่ยนชื่อไฟล์ {folder}/{ext} -> {rel}")
        continue

    found = find_by_id(item["id"])
    if found:
        changes.append(f"{item['id']} {item['name']}: image '{rel}' -> '{found}'")
        item["image"] = found

storage.save_json("products.json", data)

# --- (3) ออเดอร์สถานะ -1 ---
all_orders = storage.load_json("orders.json")
fixed_orders = 0
for order in all_orders:
    if order.get("status") in (-1, "-1"):
        order["status"] = 9
        fixed_orders += 1
if fixed_orders:
    storage.save_json("orders.json", all_orders)
    changes.append(f"ออเดอร์ที่แก้สถานะ -1 -> 9: {fixed_orders} รายการ")

# --- (4) รายงาน ---
used = {i.get("image", "") for i in data["products"] + data["soups"]}
orphans, missing = [], []
for root, _, files in os.walk(IMG_DIR):
    for f in files:
        rel = os.path.relpath(os.path.join(root, f), IMG_DIR).replace(os.sep, "/")
        if rel not in used and rel != "mala-bg.jpg":
            orphans.append(rel)
for item in data["products"] + data["soups"]:
    if item.get("image") and not os.path.isfile(img_path(item["image"])):
        missing.append(f"{item['id']} {item['name']} -> {item['image']}")

print("=== ผลการซ่อมข้อมูล ===")
for c in changes:
    print(" ✔", c)
if not changes:
    print(" (ไม่มีอะไรต้องแก้ ข้อมูลตรงกันแล้ว)")
if missing:
    print("\n⚠ รูปที่ยังหาไม่เจอ (ต้องอัปโหลดใหม่ในหน้าจัดการสินค้า):")
    for m in missing:
        print("   -", m)
if orphans:
    print("\nℹ ไฟล์รูปที่ไม่มีสินค้าใช้ (ตรวจดูแล้วลบเองได้ ระบบไม่ลบให้):")
    for o in orphans:
        print("   -", "static/images/" + o)
