import random

def get_recommended_set(products, budget=100):
    """
    ระบบสุ่มเลือกชุดวัตถุดิบหม่าล่าให้อยู่ภายในงบประมาณที่กำหนด
    """
    # กรองเฉพาะสินค้าที่พร้อมขายและมีสต็อก
    available_items = [
        p for p in products 
        if p.get("available", True) and p.get("stock", 0) > 0
    ]
    
    selected_items = []
    current_total = 0
    
    # สุ่มลำดับสินค้า
    random.shuffle(available_items)
    
    for item in available_items:
        price = item.get("price", 0)
        if current_total + price <= budget:
            selected_items.append(item)
            current_total += price
            
    return {
        "items": selected_items,
        "total_price": current_total,
        "budget": budget
    }