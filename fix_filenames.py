import os

base_dir = os.path.join("static", "images")
count = 0

for root, dirs, files in os.walk(base_dir):
    for file in files:
        if file.endswith(".jpg.jpg"):
            old_path = os.path.join(root, file)
            new_filename = file[:-4]  # ตัด .jpg ตัวหลังออก 1 อัน
            new_path = os.path.join(root, new_filename)
            os.rename(old_path, new_path)
            print(f"✏️ แก้ไขสำเร็จ: {file} -> {new_filename}")
            count += 1

print(f"\n🎉 แก้ไขชื่อไฟล์ซ้ำเรียบร้อยแล้วทั้งหมด {count} ไฟล์!")