# auth.py - สมัครสมาชิก / เข้าสู่ระบบ (ไม่มี print/input)

from werkzeug.security import generate_password_hash, check_password_hash
import storage


def load_users():
    """อ่านรายชื่อสมาชิกทั้งหมดจาก users.json"""
    return storage.load_json("users.json")


def find_user(username):
    """หาสมาชิกจากชื่อผู้ใช้ (ไม่สนตัวพิมพ์เล็ก/ใหญ่) ไม่เจอคืน None"""
    for user in load_users():
        if user["username"].lower() == username.lower():
            return user
    return None


def register_user(username, password, confirm, name):
    """สมัครสมาชิกใหม่ คืนค่า (สำเร็จไหม, ข้อความ)"""
    username = username.strip()
    name = name.strip()

    if len(username) < 3 or " " in username:
        return False, "ชื่อผู้ใช้ต้องยาวอย่างน้อย 3 ตัวอักษร และห้ามมีช่องว่าง"
    if name == "":
        return False, "กรุณากรอกชื่อที่ใช้แสดง"
    if len(password) < 6:
        return False, "รหัสผ่านต้องยาวอย่างน้อย 6 ตัวอักษร"
    if password != confirm:
        return False, "รหัสผ่านและช่องยืนยันไม่ตรงกัน"
    if find_user(username) is not None:
        return False, "ชื่อผู้ใช้นี้มีคนใช้แล้ว ลองชื่ออื่นนะ"

    users = load_users()
    users.append({
        "username": username,
        "password_hash": generate_password_hash(password, method="pbkdf2:sha256"),
        "name": name,
        "role": "customer",
        "points": 0,
    })
    storage.save_json("users.json", users)
    return True, "สมัครสมาชิกสำเร็จ เข้าสู่ระบบได้เลย"


def check_login(username, password):
    """ตรวจชื่อผู้ใช้และรหัสผ่าน ถ้าถูกคืนข้อมูลสมาชิก ถ้าผิดคืน None"""
    user = find_user(username.strip())
    if user is not None and check_password_hash(user["password_hash"], password):
        return user
    return None


def create_default_admin():
    """สร้างบัญชี admin เริ่มต้น ถ้ายังไม่มี"""
    if find_user("admin") is None:
        users = load_users()
        users.append({
            "username": "admin",
            "password_hash": generate_password_hash("admin1234", method="pbkdf2:sha256"),
            "name": "ผู้ดูแลร้าน",
            "role": "admin",
            "points": 0,
        })
        storage.save_json("users.json", users)
        
        
def add_points(username, points):
    """เพิ่มคะแนนสะสมให้สมาชิก"""
    users = load_users()
    for user in users:
        if user["username"].lower() == username.lower():
                        user["points"] = max(0, user.get("points", 0) + points)
    storage.save_json("users.json", users)