import random

# budget.py - จัดวัตถุดิบตามงบประมาณ (ไม่มี print/input)

# สัดส่วนงบของแต่ละหมวด (รวมกัน = 1.0)
CATEGORY_SHARE = {
    "เนื้อสัตว์": 0.35,
    "ลูกชิ้น": 0.25,
    "ผัก": 0.25,
    "เส้น": 0.15,
}

# หยิบแต่ละอย่างได้ไม่เกินกี่ชิ้น
MAX_PER_ITEM = 5


def get_sellable(products):
    """คัดเฉพาะสินค้าที่พร้อมขายและมีของเหลือ (ไม่รวมน้ำจิ้ม)"""
    result = []
    for p in products:
        if p["category"] in ("น้ำจิ้ม", "เม็ดหม่าล่า"):
            continue    # ข้ามน้ำจิ้ม/เม็ดหม่าล่า ให้ลูกค้าเลือกเองในหน้าของมัน
        if p["available"] and p["stock"] > 0:
            result.append(p)
    return result


def fill_items(plan, items, money):
    """วนใส่ทีละ 1 ชิ้นไปเรื่อย ๆ จนเงินไม่พอ แล้วคืนเงินที่เหลือ"""
    added = True
    while added:
        added = False
        for p in items:
            have = plan.get(p["id"], 0)
            if p["price"] <= money and have < MAX_PER_ITEM and have < p["stock"]:
                plan[p["id"]] = have + 1
                money -= p["price"]
                added = True
    return money


def use_leftover(plan, items, leftover, pick=None):
    """เงินเหลือน้อยเกินซื้อชิ้นใหม่ -> สลับของที่ใส่ไว้เป็นชิ้นที่แพงขึ้นนิดหน่อย
    (เช่น เหลือ 3 บาท สลับของ 5 บาท เป็นของ 8 บาท) ให้ยอดชิดงบมากที่สุด
    คืนเงินที่ยังเหลือ"""
    by_id = {p["id"]: p for p in items}
    while leftover > 0:
        options = []    # (ส่วนต่างราคา, อยู่หมวดเดียวกันไหม, รหัสเดิม, ชิ้นใหม่)
        for cur_id, qty in plan.items():
            if qty <= 0 or cur_id not in by_id:
                continue
            cur = by_id[cur_id]
            for new in items:
                if new["id"] == cur_id:
                    continue
                delta = new["price"] - cur["price"]
                have = plan.get(new["id"], 0)
                if 0 < delta <= leftover and have < MAX_PER_ITEM and have < new["stock"]:
                    same = new["category"] == cur["category"]
                    options.append((delta, same, cur_id, new))
        if not options:
            break
        best_key = max((o[0], o[1]) for o in options)
        top = [o for o in options if (o[0], o[1]) == best_key]
        delta, _, cur_id, new = pick(top) if pick else top[0]
        plan[cur_id] -= 1
        if plan[cur_id] <= 0:
            del plan[cur_id]
        plan[new["id"]] = plan.get(new["id"], 0) + 1
        leftover -= delta
    return leftover


def plan_cost(plan, products):
    """รวมราคาของรายการใน plan"""
    cost = 0
    for p in products:
        if p["id"] in plan:
            cost += p["price"] * plan[p["id"]]
    return cost


def budget_mala(amount, soup, products):
    """จัดชุดหม่าล่าตามงบ คืนผลลัพธ์เป็น dictionary"""
    sellable = get_sellable(products)
    remaining = amount - soup["price"]    # งบที่เหลือหลังหักน้ำซุป
    plan = {}                             # {รหัสสินค้า: จำนวน}

    # งบไม่พอแม้แต่ค่าน้ำซุป
    if remaining <= 0:
        return {"ok": False, "plan": plan, "total": soup["price"],
                "left": 0, "soup_price": soup["price"]}

    # รอบที่ 1: แบ่งงบตามหมวด แล้วหยิบของในหมวดนั้น
    for category, share in CATEGORY_SHARE.items():
        items = []
        for p in sellable:
            if p["category"] == category:
                items.append(p)
        fill_items(plan, items, int(remaining * share))

    # รอบที่ 2: เอาเงินที่เหลือไปเติมจากทุกหมวด
    leftover = remaining - plan_cost(plan, sellable)
    leftover = fill_items(plan, sellable, leftover)

    # รอบที่ 3: ถ้าเหลือเงินน้อยเกินซื้อชิ้นใหม่ ให้อัปเกรดบางชิ้นให้ชิดงบ
    use_leftover(plan, sellable, leftover)

    total = soup["price"] + plan_cost(plan, sellable)
    return {"ok": True, "plan": plan, "total": total,
            "left": amount - total, "soup_price": soup["price"]}
    
def random_mala(amount, soup, products):
    """สุ่มวัตถุดิบตามงบ คืนผลลัพธ์รูปแบบเดียวกับ budget_mala"""
    sellable = get_sellable(products)
    money = amount - soup["price"]    # งบที่เหลือหลังหักน้ำซุป
    plan = {}

    if money <= 0:
        return {"ok": False, "plan": plan, "total": soup["price"],
                "left": 0, "soup_price": soup["price"]}

    # รอบที่ 1: สุ่ม 1 อย่างจากแต่ละหมวด (ถ้างบพอ) ให้ชามมีความหลากหลาย
    categories = list(CATEGORY_SHARE.keys())
    random.shuffle(categories)
    for category in categories:
        choices = []
        for p in sellable:
            if p["category"] == category and p["price"] <= money:
                choices.append(p)
        if choices:
            picked = random.choice(choices)
            plan[picked["id"]] = 1
            money -= picked["price"]

    # รอบที่ 2: สุ่มเพิ่มไปเรื่อย ๆ จนไม่มีอะไรซื้อไหวแล้ว
    while True:
        choices = []
        for p in sellable:
            have = plan.get(p["id"], 0)
            if p["price"] <= money and have < MAX_PER_ITEM and have < p["stock"]:
                choices.append(p)

        if not choices:
            break

        picked = random.choice(choices)
        plan[picked["id"]] = plan.get(picked["id"], 0) + 1
        money -= picked["price"]

    # รอบที่ 3: เหลือเงินน้อยเกินซื้อชิ้นใหม่ -> สุ่มอัปเกรดบางชิ้นให้ชิดงบ
    use_leftover(plan, sellable, money, pick=random.choice)

    total = soup["price"] + plan_cost(plan, sellable)
    return {"ok": True, "plan": plan, "total": total,
            "left": amount - total, "soup_price": soup["price"]}