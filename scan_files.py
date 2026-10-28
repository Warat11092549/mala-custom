import os

base_dir = os.path.join("static", "images")
print("\n📁 --- รายชื่อไฟล์รูปภาพทั้งหมดที่มีอยู่ในเครื่อง ---")

for root, dirs, files in os.walk(base_dir):
    folder_name = os.path.relpath(root, base_dir)
    if files:
        print(f"\n📂 โฟลเดอร์: static/images/{folder_name}")
        for f in files:
            print(f"   └── {f}")