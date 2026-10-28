import json
import os

# โหลดข้อมูล products.json
with open("data/products.json", "r", encoding="utf-8") as f:
    data = json.load(f)

items = data.get("soups", []) + data.get("products", [])

print("\n🔍 --- ผลการตรวจสอบไฟล์รูปภาพ ---")
missing_count = 0

for item in items:
    img_rel = item.get("image", "")
    full_path = os.path.join("static", "images", img_rel)
    
    if os.path.exists(full_path):
        print(f"✅ เจอไฟล์: {item['name']} -> static/images/{img_rel}")
    else:
        missing_count += 1
        print(f"❌ หาไม่เจอ: {item['name']} (ตั้งไว้: static/images/{img_rel})")

if missing_count == 0:
    print("\n🎉 รูปภาพทั้งหมดถูกต้องครบถ้วน!")
else:
    print(f"\n⚠️ มีรูปภาพหาไม่เจอทั้งหมด {missing_count} รายการ")