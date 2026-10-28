# storage.py - อ่านและบันทึกข้อมูลในไฟล์ JSON

import json
import os

# หาตำแหน่งโฟลเดอร์ data ให้อัตโนมัติ (รันจากที่ไหนก็ได้)
DATA_FOLDER = os.path.join(os.path.dirname(__file__), "data")


def load_json(filename):
    """อ่านไฟล์ JSON แล้วคืนข้อมูลกลับมา"""
    path = os.path.join(DATA_FOLDER, filename)
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def save_json(filename, data):
    """บันทึกข้อมูลลงไฟล์ JSON"""
    path = os.path.join(DATA_FOLDER, filename)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def load_products():
    """คืน list วัตถุดิบทั้งหมด"""
    data = load_json("products.json")
    return data["products"]


def load_soups():
    """คืน list น้ำซุปทั้งหมด"""
    data = load_json("products.json")
    return data["soups"]


def save_products(products):
    """บันทึกวัตถุดิบ โดยคงน้ำซุปเดิมไว้"""
    data = load_json("products.json")
    data["products"] = products
    save_json("products.json", data)