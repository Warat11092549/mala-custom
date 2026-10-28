# cart.py - ตรรกะของตะกร้า (ไม่มี print/input เพื่อให้ใช้กับเว็บได้)

import storage


def find_product(product_id):
    """หาวัตถุดิบจากรหัส ถ้าไม่เจอคืน None"""
    for p in storage.load_products():
        if p["id"] == product_id:
            return p
    return None


def find_soup(soup_id):
    """หาน้ำซุปจากรหัส ถ้าไม่เจอคืน None"""
    for s in storage.load_soups():
        if s["id"] == soup_id:
            return s
    return None


def get_cart_items(cart):
    """แปลงตะกร้า {รหัส: จำนวน} เป็น list รายการพร้อมราคา"""
    items = []
    for product_id, qty in cart.items():
        p = find_product(product_id)
        if p is not None:
            items.append({
                "id": p["id"],
                "name": p["name"],
                "price": p["price"],
                "qty": qty,
                "line_total": p["price"] * qty,
            })
    return items


def calculate_total(items):
    """รวมราคาทุกรายการในตะกร้า"""
    total = 0
    for item in items:
        total += item["line_total"]
    return total