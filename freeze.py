from app import app  # หากไฟล์หลักของคุณชื่อ app.py
from flask_frozen import Freezer

# หมายเหตุ: ถ้าไฟล์หลักของคุณชื่อ main.py ให้แก้ไขบรรทัดแรกเป็น `from main import app`
# โดยคำว่า app ตัวหลังคือชื่อตัวแปรที่สร้าง Flask เช่น app = Flask(__name__)

freezer = Freezer(app)

if __name__ == '__main__':
    freezer.freeze()