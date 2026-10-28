# app.py - ปรับแต่งโครงสร้างให้ทำงานร่วมกับ orders.py (ใช้คีย์ lines, total, status 1-5,9) อย่างสมบูรณ์

import os
import re
import math
from datetime import datetime
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, send_from_directory, abort, jsonify
)
import storage
import cart
import promo
import budget
import auth
import orders
import report
import delivery
import config
import promptpay
import settings
import shop_status
import member_codes
import reviews
import alerts
import receipts
import vat

app = Flask(__name__)
app.secret_key = "mala-custom-secret"
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # จำกัดไฟล์อัปโหลดไม่เกิน 5 MB
auth.create_default_admin()


# ไอคอนแทนอิโมจิ: ใช้ใน template ด้วย {{ ic('chili') }} (ไฟล์อยู่ static/icons/<ชื่อ>.png)
from markupsafe import Markup, escape as _esc


@app.template_global("ic")
def ic(name, cls=""):
    src = url_for("static", filename=f"icons/{name}.png")
    return Markup(f'<img class="ic {_esc(cls)}" src="{src}" alt="" aria-hidden="true">')


# หน้าที่ลูกค้าใช้เลือก/สั่งอาหาร (โชว์แถบ "ร้านปิด" เฉพาะหน้าเหล่านี้ ส่วนหน้าชำระเงิน/ติดตามออเดอร์เดิมไม่โชว์)
ORDERING_ENDPOINTS = ["home", "shop", "sauces", "seeds", "cart_page", "budget_page", "random_page",
                      "checkout", "checkout_summary", "order_history"]


@app.context_processor
def inject_shop_state():
    """ส่งสถานะร้าน + ประกาศโปรโมชันให้ทุก template (shop_state / promo_banner)"""
    ctx = {
        "shop_state": shop_status.get_status(),
        "promo_banner": settings.promo_banner(),
        "ordering_endpoints": ORDERING_ENDPOINTS,
        "stack_coupon_allowed": config.MEMBER_CODE_STACK_WITH_COUPON,
        "vat_cfg": vat.config_view(),      # {enabled, rate, demo, notice} ให้ทุกหน้าใช้แสดง VAT/ข้อความโหมดจำลอง
    }
    if session.get("role") == "admin":      # ตัวเลขแจ้งเตือนหลังร้าน (ลูกค้าไม่เห็น/ไม่เสียเวลาคำนวณ)
        ctx["admin_alerts"] = alerts.summary()
        ctx["alert_poll_seconds"] = config.ADMIN_ALERT_POLL_SECONDS
    return ctx


def closed_redirect(endpoint="cart_page"):
    """ถ้าร้านปิดอยู่: แจ้งลูกค้าแล้วคืน redirect (ร้านเปิดอยู่คืน None) — ใช้กั้นทุกทางที่นำไปสู่การสร้างออเดอร์"""
    state = shop_status.get_status()
    if state["open"]:
        return None
    flash(f"{state['headline']} — ยังสั่งซื้อไม่ได้ในตอนนี้ "
          + (state["detail"] + " " if state["detail"] else "")
          + "ดูเมนูและเลือกของไว้ล่วงหน้าได้นะ")
    return redirect(url_for(endpoint))


SPICY_LEVELS = {
    1: "ไม่เผ็ด",
    2: "เผ็ดน้อย",
    3: "เผ็ดปานกลาง",
    4: "เผ็ดมาก",
    5: "เผ็ดพ่นไฟ",
}
SAUCE_CATEGORY = "น้ำจิ้ม"
SEED_CATEGORY = "เม็ดหม่าล่า"


def safe_find_soup(soup_id):
    """ค้นหาน้ำซุปโดยแปลง ID เป็น string เสมอ หากไม่พบให้ใช้ซุปแรกเพื่อป้องกัน Error"""
    soups = storage.load_soups()
    if not soups:
        return {"id": "default", "name": "ซุปหม่าล่าดั้งเดิม", "price": 50.0}

    if soup_id:
        sid_str = str(soup_id).strip()
        for s in soups:
            if str(s.get("id", "")).strip() == sid_str:
                return s
    return soups[0]


def safe_find_product(product_id):
    """ค้นหาสินค้าโดยแปลง ID เป็น string เสมอ ป้องกันปัญหา int vs str mismatch"""
    if not product_id:
        return None
    products = storage.load_products()
    pid_str = str(product_id).strip()
    for p in products:
        if str(p.get("id", "")).strip() == pid_str:
            return p
    return None


def safe_get_cart_items(cart_dict):
    """แปลงรายการใน cart_dict เป็นออบเจกต์สินค้าโดยรองรับทั้ง ID ตัวเลขและข้อความ"""
    if not cart_dict or not isinstance(cart_dict, dict):
        return []
    products = storage.load_products()
    prod_map = {str(p.get("id", "")).strip(): p for p in products if "id" in p}

    items = []
    for p_id, qty in cart_dict.items():
        pid_str = str(p_id).strip()
        p = prod_map.get(pid_str)
        if p and int(qty) > 0:
            price = float(p.get("price", 0))
            q = int(qty)
            items.append({
                "id": str(p.get("id")),
                "product": p,
                "name": p.get("name", "วัตถุดิบ"),
                "price": price,
                "qty": q,
                "subtotal": price * q,
                "image": p.get("image", ""),
            })
    return items


def item_category(item):
    """หมวดของรายการ (รองรับทั้งรายการในตะกร้า ที่มี product และรายการในออเดอร์เก่า)"""
    if not isinstance(item, dict):
        return ""
    return item.get("category") or (item.get("product") or {}).get("category", "") or ""


def split_items(items):
    """แยกรายการเป็น (วัตถุดิบ, น้ำจิ้ม, เม็ดหม่าล่า) ใช้โชว์น้ำจิ้ม/เม็ดไว้แถบเดียวกับน้ำซุป"""
    ingredients, sauce_items, seed_items = [], [], []
    for it in items or []:
        cat = item_category(it)
        if cat == SAUCE_CATEGORY:
            sauce_items.append(it)
        elif cat == SEED_CATEGORY:
            seed_items.append(it)
        else:
            ingredients.append(it)
    return ingredients, sauce_items, seed_items


def prune_cart():
    """ล้างของที่ไม่มีในร้านแล้ว (ถูกลบจากหลังร้าน) หรือจำนวนผิดปกติ ออกจากตะกร้า
    ไม่งั้นลูกค้าจะมองไม่เห็นแต่กดสั่งไม่ได้ (ระบบแจ้ง 'หมดแล้ว' แต่ไม่มีปุ่มลบ)"""
    cart_data = session.get("cart")
    if not isinstance(cart_data, dict) or not cart_data:
        return
    known = {str(p.get("id", "")).strip() for p in storage.load_products()}
    cleaned = {}
    for key, qty in cart_data.items():
        try:
            q = int(qty)
        except (TypeError, ValueError):
            continue
        if str(key).strip() in known and q > 0:
            cleaned[str(key).strip()] = q
    if cleaned != cart_data:
        session["cart"] = cleaned
        session.modified = True


def get_pricing(soup):
    """คำนวณราคาวัตถุดิบและส่วนลด"""
    prune_cart()
    if not soup or not isinstance(soup, dict):
        soup = {"id": "default", "name": "ซุปหม่าล่า", "price": 50.0}

    cart_data = session.get("cart", {})
    items = safe_get_cart_items(cart_data)
    items_total = sum(item["subtotal"] for item in items)
    subtotal = soup.get("price", 0) + items_total

    # สิทธิ์สมาชิก: ตรวจกับไฟล์ทุกครั้งที่คิดราคา (ต้องเป็นของ user นี้ ยังไม่ใช้ ยังไม่หมดอายุ) ไม่เชื่อค่าใน session เฉย ๆ
    member_reward = None
    member_dropped = False
    chosen = session.get("member_code")
    if chosen:
        rec = member_codes.validate(chosen, session.get("username"))
        if rec:
            member_reward = {"code": rec["code"], "value": rec["value"], "min": rec["min_order"]}
        else:
            session.pop("member_code", None)
            session.modified = True
            member_dropped = True
    pricing = promo.calculate_discount(subtotal, session.get("coupon"), member_reward)
    if member_dropped:
        pricing["member_note"] = "สิทธิ์สมาชิกที่เลือกไว้หมดอายุหรือใช้ไม่ได้แล้ว"
    
    # เติม Key เพื่อป้องกัน KeyError กับ orders.py
    if "tier_percent" not in pricing:
        pricing["tier_percent"] = 0
    if "tier_discount" not in pricing:
        pricing["tier_discount"] = 0.0
    if "coupon_code" not in pricing:
        pricing["coupon_code"] = session.get("coupon", "")
    if "coupon_discount" not in pricing:
        pricing["coupon_discount"] = 0.0
    if "final_total" not in pricing:
        pricing["final_total"] = pricing.get("total", subtotal)

    # VAT รวมอยู่ในราคาแล้ว: แยกจากยอดหลังหักส่วนลดทุกประเภท (ไม่บวกเพิ่ม · ไม่รวมค่าส่ง) ใช้ vat.py ที่เดียว
    pricing["vat"] = vat.calculate(pricing["final_total"], 0)

    return items, items_total, pricing


def normalize_order(order):
  """แปลงคีย์ข้อมูลออเดอร์ให้รองรับทั้ง total, grand_total, food_total, fee, lines และ items"""
  if not order or not isinstance(order, dict):
    return order

  # 0. สถานะ: แปลงเป็นตัวเลขเสมอ (-1 เก่า -> 9) และใส่ชื่อสถานะไว้แสดงผล
  order["status"] = orders.get_status(order)
  order["status_name"] = orders.STATUS_NAMES.get(order["status"], "")

  # 1. จัดการวันที่
  order["created_at"] = (
      order.get("date")
      or order.get("created_at")
      or datetime.now().strftime("%Y-%m-%d %H:%M")
  )

  # 2. ดึงรายการสินค้า
  raw_items = (
      order.get("lines")
      or order.get("items")
      or order.get("item_list")
      or order.get("cart")
      or []
  )

  products = storage.load_products()
  prod_map = {str(p.get("id", "")).strip(): p for p in products if "id" in p}

  normalized_items = []
  if isinstance(raw_items, list):
    for item in raw_items:
      if isinstance(item, dict):
        p_id = str(item.get("id") or item.get("product_id") or "").strip()
        name = item.get("name") or (
            prod_map[p_id].get("name") if p_id in prod_map else "วัตถุดิบ"
        )
        # ราคา 0 (เช่น ตัวเลือกกรองเม็ด) ต้องเป็น 0 ตามที่บันทึกไว้ ห้ามไปดึงราคาปัจจุบันของสินค้ามาแทน
        price_raw = item.get("price")
        if price_raw is None:
            price_raw = prod_map[p_id].get("price") if p_id in prod_map else 0
        price = float(price_raw or 0)
        qty = int(item.get("qty") or item.get("quantity") or 1)
        subtotal_raw = item.get("subtotal")
        subtotal = float(price * qty if subtotal_raw is None else subtotal_raw)
        category = item_category(item) or (
            prod_map[p_id].get("category", "") if p_id in prod_map else ""
        )
        image = item.get("image") or (
            prod_map[p_id].get("image") if p_id in prod_map else ""
        )

        normalized_items.append({
            "id": p_id,
            "name": name,
            "price": price,
            "qty": qty,
            "subtotal": subtotal,
            "image": image,
            "category": category,
        })

  # ผูกคีย์รายการสินค้าให้ครบทุกชื่อ
  order["lines"] = normalized_items
  order["item_list"] = normalized_items
  order["items"] = normalized_items
  order["item_count"] = len(normalized_items)
  # แยกกลุ่มไว้โชว์: น้ำจิ้ม/เม็ดหม่าล่า อยู่แถบเดียวกับซุป ส่วนรายการด้านล่างเหลือแค่วัตถุดิบ
  (order["ingredient_items"], order["sauce_items"],
   order["seed_items"]) = split_items(normalized_items)
  order["ingredient_count"] = len(order["ingredient_items"])

  # 3. กำหนดค่า total และ grand_total ให้ตรงกัน
  tot = (
      order.get("total")
      if order.get("total") is not None
      else order.get("grand_total", 0.0)
  )
  try:
    tot_val = float(tot or 0.0)
  except (ValueError, TypeError):
    tot_val = 0.0

  order["total"] = tot_val
  order["grand_total"] = tot_val

  # 4. ค่าจัดส่ง (fee / delivery_fee)
  fee_val = (
      order.get("delivery_fee")
      if order.get("delivery_fee") is not None
      else order.get("fee", 0.0)
  )
  try:
    fee_num = float(fee_val or 0.0)
  except (ValueError, TypeError):
    fee_num = 0.0

  order["fee"] = fee_num
  order["delivery_fee"] = fee_num

  # 5. ค่าอาหาร (food_total)
  pricing_obj = (
      order.get("pricing", {}) if isinstance(order.get("pricing"), dict) else {}
  )
  food_tot = (
      order.get("food_total")
      if order.get("food_total") is not None
      else pricing_obj.get(
          "final_total", order.get("subtotal", tot_val - fee_num)
      )
  )
  try:
    order["food_total"] = float(food_tot or 0.0)
  except (ValueError, TypeError):
    order["food_total"] = 0.0

  # 6. VAT (ใช้แสดงผลเท่านั้น ออเดอร์เก่าไม่มีคีย์เหล่านี้ = ไม่มี VAT)
  order["vat_enabled"] = bool(order.get("vat_enabled"))
  try:
    order["vat_amount"] = float(order.get("vat_amount") or 0.0) if order["vat_enabled"] else 0.0
    order["vat_rate"] = float(order.get("vat_rate") or 0.0) if order["vat_enabled"] else 0.0
  except (ValueError, TypeError):
    order["vat_amount"], order["vat_rate"] = 0.0, 0.0
  order["vat_demo"] = bool(order.get("vat_demo")) and order["vat_enabled"]
  # vat_mode: "included" = VAT รวมอยู่ในราคา (ระบบปัจจุบัน) · ออเดอร์ที่มี VAT แต่ไม่มีคีย์นี้ = "added" (บวกเพิ่มแบบเดิม)
  order["vat_mode"] = (order.get("vat_mode") or "added") if order["vat_enabled"] else ""
  if order["vat_mode"] == "included":
    try:
      order["subtotal_ex_vat"] = float(order["subtotal_ex_vat"]) if order.get("subtotal_ex_vat") is not None \
          else round(order["food_total"] - order["vat_amount"], 2)      # ใช้ค่าที่บันทึกไว้เท่านั้น (ไม่คิดจากราคาสินค้าปัจจุบัน)
    except (ValueError, TypeError):
      order["subtotal_ex_vat"] = round(order["food_total"] - order["vat_amount"], 2)

  order["customer_name"] = (
      order.get("customer_name")
      or order.get("name")
      or order.get("username")
      or ""
  )

  return order

@app.before_request
def require_login():
    """ตรวจสิทธิ์การเข้าใช้งาน"""
    endpoint = request.endpoint or ""
    open_pages = ["login", "register", "static"]

    # ยกเลิกออเดอร์ที่ค้างไม่ชำระเกินเวลา + คืนสต็อก (ตรวจไม่เกินทุก 15 วินาที)
    if endpoint != "static":
        try:
            orders.expire_unpaid_orders()
        except Exception as error:      # อย่าให้ตัวเก็บกวาดทำเว็บล่ม
            app.logger.warning("expire_unpaid_orders ล้มเหลว: %s", error)

    if endpoint not in open_pages and "username" not in session:
        return redirect(url_for("login"))

    if endpoint.startswith("admin_") and session.get("role") != "admin":
        return redirect(url_for("home"))

    if session.get("role") == "admin":
        admin_allowed = ["logout", "static", "view_slip"]
        if endpoint not in admin_allowed and not endpoint.startswith("admin_"):
            return redirect(url_for("admin_orders"))


# ===================== หน้าต้อนรับ (หลังล็อกอิน ก่อนเลือกซุป) =====================

@app.route("/welcome")
def welcome():
    """หน้าต้อนรับ: โผล่หลังล็อกอินเท่านั้น (ไม่ใช่ด่านบังคับ — เข้า / ตรงได้ตลอด) แสดงสถานะร้าน/โปรโมชัน + ปุ่มไปสั่ง"""
    me = session.get("username")
    try:
        returning = any(o.get("username") == me for o in orders.load_orders())
    except Exception:
        returning = False
    return render_template("welcome.html", shop_name=config.SHOP_NAME,
                           display_name=session.get("name") or "", returning=returning)


# ===================== หน้าหลัก / เลือกซุป =====================

@app.route("/")
def home():
    soups = storage.load_soups()
    return render_template("home.html", soups=soups, spicy_levels=SPICY_LEVELS)


@app.route("/select_soup", methods=["POST"])
def select_soup():
    soup_id = request.form.get("soup")
    spicy = request.form.get("spicy")

    if not soup_id or not spicy:
        return redirect(url_for("home"))

    # ตรวจค่าที่ส่งมา (เดิม int() พังด้วย 500 ถ้าไม่ใช่ตัวเลข และรับซุป/ระดับเผ็ดที่ไม่มีจริง)
    if not str(spicy).isdigit() or int(spicy) not in SPICY_LEVELS:
        return redirect(url_for("home"))
    if str(soup_id).strip() not in {str(s.get("id", "")).strip() for s in storage.load_soups()}:
        return redirect(url_for("home"))

    session["soup_id"] = str(soup_id).strip()
    session["spicy"] = int(spicy)
    session.modified = True
    return redirect(url_for("shop"))


@app.route("/shop")
def shop():
    if "soup_id" not in session:
        return redirect(url_for("home"))

    soup = safe_find_soup(session["soup_id"])
    products = storage.load_products()

    categories = []
    for p in products:
        if p["category"] not in categories and p["category"] not in (SAUCE_CATEGORY, SEED_CATEGORY):
            categories.append(p["category"])

    spicy_level = session.get("spicy", 1)
    items, items_total, pricing = get_pricing(soup)

    raw_cart = session.get("cart", {})
    quantities = {str(k): v for k, v in raw_cart.items()}

    return render_template(
        "shop.html",
        soup=soup,
        spicy_level=spicy_level,
        spicy_name=SPICY_LEVELS.get(spicy_level, "เผ็ดน้อย"),
        products=products,
        categories=categories,
        quantities=quantities,
        pricing=pricing,
    )


# ===================== จัดการตะกร้าสินค้า =====================

@app.route("/add/<product_id>", methods=["POST"])
def add_to_cart(product_id):
    product = safe_find_product(product_id)
    cart_data = session.get("cart", {})
    if not isinstance(cart_data, dict):
        cart_data = {}

    if product and product.get("available", True):
        pid_str = str(product.get("id"))
        current = cart_data.get(pid_str, 0)
        if current == 0 and product.get("id") in cart_data:
            current = cart_data.get(product.get("id"), 0)

        if product.get("category") == SEED_CATEGORY:
            # เม็ดหม่าล่า (กรอง/ไม่กรอง) เลือกได้ 1 แบบ ชามละ 1 -> เลือกอันใหม่แล้วเอาอันเก่าออก
            if product.get("stock", 0) > 0:
                for p in storage.load_products():
                    if p.get("category") == SEED_CATEGORY:
                        cart_data.pop(str(p.get("id")), None)
                cart_data[pid_str] = 1
        elif current < product.get("stock", 999):
            cart_data[pid_str] = current + 1

    session["cart"] = cart_data
    session.modified = True
    return go_back(product_id)


@app.route("/decrease/<product_id>", methods=["POST"])
def decrease_item(product_id):
    cart_data = session.get("cart", {})
    pid_str = str(product_id).strip()

    target_key = None
    if pid_str in cart_data:
        target_key = pid_str
    elif pid_str.isdigit() and int(pid_str) in cart_data:
        target_key = int(pid_str)

    if target_key is not None:
        if cart_data[target_key] > 1:
            cart_data[target_key] -= 1
        else:
            del cart_data[target_key]

    session["cart"] = cart_data
    session.modified = True
    return go_back(product_id)


@app.route("/remove/<product_id>", methods=["POST"])
def remove_item(product_id):
    cart_data = session.get("cart", {})
    pid_str = str(product_id).strip()
    cart_data.pop(pid_str, None)
    if pid_str.isdigit():
        cart_data.pop(int(pid_str), None)
    session["cart"] = cart_data
    session.modified = True
    return go_back(product_id)


def go_back(product_id):
    back = request.form.get("back")
    if back == "cart":
        return redirect(url_for("cart_page"))
    if back == "sauces":
        return redirect(url_for("sauces") + "#item-" + str(product_id))
    if back == "seeds":
        return redirect(url_for("seeds") + "#item-" + str(product_id))
    return redirect(url_for("shop") + "#item-" + str(product_id))


@app.route("/sauces")
def sauces():
    if "soup_id" not in session:
        return redirect(url_for("home"))

    soup = safe_find_soup(session["soup_id"])

    sauce_list = []
    for p in storage.load_products():
        if p["category"] == SAUCE_CATEGORY:
            sauce_list.append(p)

    spicy_level = session.get("spicy", 1)
    items, items_total, pricing = get_pricing(soup)

    raw_cart = session.get("cart", {})
    quantities = {str(k): v for k, v in raw_cart.items()}

    return render_template(
        "sauces.html",
        soup=soup,
        spicy_level=spicy_level,
        spicy_name=SPICY_LEVELS.get(spicy_level, "เผ็ดน้อย"),
        sauces=sauce_list,
        quantities=quantities,
        pricing=pricing,
    )


@app.route("/seeds")
def seeds():
    """ขั้นตอนเลือกเม็ดหม่าล่า (ต่อจากน้ำจิ้ม ก่อนตะกร้า) ข้ามได้"""
    if "soup_id" not in session:
        return redirect(url_for("home"))

    soup = safe_find_soup(session["soup_id"])
    seed_list = [p for p in storage.load_products() if p["category"] == SEED_CATEGORY]

    spicy_level = session.get("spicy", 1)
    items, items_total, pricing = get_pricing(soup)

    raw_cart = session.get("cart", {})
    quantities = {str(k): v for k, v in raw_cart.items()}

    chosen_seed = next((p["id"] for p in seed_list if quantities.get(str(p["id"]), 0) > 0), "")

    return render_template(
        "seeds.html",
        chosen_seed=chosen_seed,
        soup=soup,
        spicy_level=spicy_level,
        spicy_name=SPICY_LEVELS.get(spicy_level, "เผ็ดน้อย"),
        seeds=seed_list,
        quantities=quantities,
        pricing=pricing,
    )


@app.route("/seeds/choose", methods=["POST"])
def seeds_choose():
    """เลือกกรองเม็ด/ไม่กรองเม็ด (เลือกได้อย่างเดียว) แล้วไปหน้าตะกร้า"""
    if "soup_id" not in session:
        return redirect(url_for("home"))

    seed_ids = {str(p["id"]) for p in storage.load_products() if p["category"] == SEED_CATEGORY}
    cart_data = {k: v for k, v in session.get("cart", {}).items() if str(k) not in seed_ids}

    choice = request.form.get("seed", "").strip()
    if choice:
        p = safe_find_product(choice)
        if p and p["category"] == SEED_CATEGORY and p.get("available") and p.get("stock", 0) > 0:
            cart_data[str(p["id"])] = 1      # เลือกได้ 1 อย่าง ชามละ 1
        else:
            flash("ตัวเลือกนี้ใช้ไม่ได้ในตอนนี้ กรุณาเลือกใหม่")
            return redirect(url_for("seeds"))

    session["cart"] = cart_data
    session.modified = True
    return redirect(url_for("cart_page"))


@app.route("/cart")
def cart_page():
    if "soup_id" not in session:
        return redirect(url_for("home"))

    soup = safe_find_soup(session["soup_id"])
    spicy_level = session.get("spicy", 1)
    items, items_total, pricing = get_pricing(soup)

    ingredients, sauce_items, seed_items = split_items(items)

    return render_template(
        "cart.html",
        soup=soup,
        spicy_level=spicy_level,
        spicy_name=SPICY_LEVELS.get(spicy_level, "เผ็ดน้อย"),
        items=items,
        ingredients=ingredients,
        sauce_items=sauce_items,
        seed_items=seed_items,
        items_total=items_total,
        pricing=pricing,
        coupons=promo.COUPONS,
        member=member_codes.summary(session.get("username")),
    )


@app.route("/apply_coupon", methods=["POST"])
def apply_coupon():
    code = request.form.get("code", "").strip().upper()

    if code in promo.COUPONS:
        session["coupon"] = code
        if session.get("member_code") and not config.MEMBER_CODE_STACK_WITH_COUPON:
            session.pop("member_code", None)
            flash(f"ใช้คูปอง {code} แล้ว (คูปองใช้ร่วมกับสิทธิ์สมาชิกไม่ได้ ระบบเอาสิทธิ์สมาชิกออกให้ — กดใช้ใหม่ได้ถ้าต้องการสลับ)")
        else:
            flash(f"ใช้คูปอง {code} แล้ว")
    else:
        flash("ไม่พบโค้ดคูปองนี้ ลองตรวจตัวสะกดอีกครั้ง")

    return redirect(url_for("cart_page"))


@app.route("/remove_coupon", methods=["POST"])
def remove_coupon():
    session.pop("coupon", None)
    return redirect(url_for("cart_page"))


@app.route("/member/apply", methods=["POST"])
def member_apply():
    """ลูกค้ากด 'ใช้สิทธิ์สมาชิก' — เซิร์ฟเวอร์หาโค้ดของ user คนนี้เอง ไม่รับโค้ดจากฟอร์ม"""
    rec = member_codes.active_code(session.get("username"))
    if not rec:
        flash("ตอนนี้คุณยังไม่มีสิทธิ์สมาชิกที่ใช้ได้")
        return redirect(url_for("cart_page"))
    session["member_code"] = rec["code"]
    message = f"ใช้สิทธิ์สมาชิก ลด {rec['value']:g} บาทแล้ว"
    if session.get("coupon") and not config.MEMBER_CODE_STACK_WITH_COUPON:
        session.pop("coupon", None)
        message += " (สิทธิ์สมาชิกใช้ร่วมกับคูปองไม่ได้ ระบบเอาคูปองออกให้)"
    session.modified = True
    flash(message)
    return redirect(url_for("cart_page"))


@app.route("/member/remove", methods=["POST"])
def member_remove():
    session.pop("member_code", None)
    session.modified = True
    return redirect(url_for("cart_page"))


# ===================== จัดตามงบ / สุ่ม =====================

def make_plan_result(raw_res):
    """แปลงผลจาก budget.py ให้หน้าเว็บใช้ได้ (มีราคาต่อรายการ, เงินเหลือ, ราคาซุป ครบ)"""
    plan = {str(k): int(v) for k, v in raw_res.get("plan", {}).items()}
    lines = safe_get_cart_items(plan)
    for line in lines:
        line["line_total"] = line["subtotal"]    # template อ่านคีย์ line_total
    total = raw_res.get("total", 0)
    after_tier = promo.calculate_discount(total)["final_total"]
    return {
        "ok": raw_res.get("ok", False),
        "total": total,
        "left": raw_res.get("left", 0),
        "soup_price": raw_res.get("soup_price", 0),
        "pay_after_tier": after_tier,            # ยอดหลังส่วนลดตามยอด (ยังไม่รวมคูปอง/ค่าส่ง)
        "plan": plan,
        "lines": lines,
        "msg": raw_res.get("msg", ""),
    }


@app.route("/budget", methods=["GET", "POST"])
def budget_page():
    if "soup_id" not in session:
        return redirect(url_for("home"))

    soup = safe_find_soup(session.get("soup_id"))
    spicy_level = session.get("spicy", 1)
    result = None
    error = ""
    amount = ""

    if request.method == "POST":
        amount = request.form.get("budget", "").strip()
        if not amount.isdigit():
            error = "กรุณาพิมพ์งบเป็นตัวเลข"
        elif int(amount) > 5000:
            error = "งบสูงเกินไป ลองใส่ไม่เกิน 5000 บาท"
        else:
            raw_res = budget.budget_mala(int(amount), soup, storage.load_products())
            result = make_plan_result(raw_res)
            session["budget_plan"] = result["plan"]
            session.modified = True

    return render_template(
        "budget.html",
        soup=soup,
        spicy_level=spicy_level,
        spicy_name=SPICY_LEVELS.get(spicy_level, "เผ็ดน้อย"),
        result=result,
        error=error,
        amount=amount,
    )


@app.route("/budget/use", methods=["POST"])
def budget_use():
    if "soup_id" not in session:
        return redirect(url_for("home"))

    plan = None
    amount = request.form.get("budget", "").strip()
    if amount.isdigit():
        # คำนวณใหม่จากงบ + ซุปปัจจุบัน (ผลเหมือนที่โชว์ในหน้า /budget) กันใช้ชุดเก่าที่ค้างใน session
        soup = safe_find_soup(session.get("soup_id"))
        raw_res = budget.budget_mala(int(amount), soup, storage.load_products())
        if raw_res.get("ok"):
            plan = {str(k): int(v) for k, v in raw_res.get("plan", {}).items()}
    if not plan:
        plan = session.get("budget_plan")

    if plan:
        session["cart"] = plan
        session.modified = True
        flash("เพิ่มรายการจัดตามงบเข้าตะกร้าเรียบร้อยแล้ว!")
        return redirect(url_for("sauces"))

    return redirect(url_for("budget_page"))


@app.route("/random", methods=["GET", "POST"])
def random_page():
    if "soup_id" not in session:
        return redirect(url_for("home"))

    soup = safe_find_soup(session.get("soup_id"))
    spicy_level = session.get("spicy", 1)
    result = None
    error = ""
    amount = ""

    if request.method == "POST":
        amount = request.form.get("budget", "").strip()
        if not amount.isdigit():
            error = "กรุณาพิมพ์งบเป็นตัวเลข"
        elif int(amount) > 5000:
            error = "งบสูงเกินไป ลองใส่ไม่เกิน 5000 บาท"
        else:
            raw_res = budget.random_mala(int(amount), soup, storage.load_products())
            result = make_plan_result(raw_res)
            if result["ok"]:
                session["random_plan"] = result["plan"]
                session["random_soup"] = session.get("soup_id")    # กันใช้ชุดสุ่มที่ได้ตอนเลือกซุปอื่น
                session.modified = True

    return render_template(
        "lucky.html",
        soup=soup,
        spicy_level=spicy_level,
        spicy_name=SPICY_LEVELS.get(spicy_level, "เผ็ดน้อย"),
        result=result,
        error=error,
        amount=amount,
    )


@app.route("/random/use", methods=["POST"])
def random_use():
    if "soup_id" not in session:
        return redirect(url_for("home"))

    plan = session.get("random_plan")
    if plan and session.get("random_soup") != session.get("soup_id"):
        plan = None    # ชุดสุ่มนี้คิดตามซุปตัวเก่า ให้สุ่มใหม่
    if not plan:
        amount = request.form.get("budget", "").strip()
        if amount.isdigit():
            soup = safe_find_soup(session.get("soup_id"))
            raw_res = budget.random_mala(int(amount), soup, storage.load_products())
            if raw_res.get("ok"):
                plan = {str(k): int(v) for k, v in raw_res.get("plan", {}).items()}

    if plan:
        session["cart"] = plan
        session.modified = True
        flash("สุ่มวัตถุดิบเข้าตะกร้าเรียบร้อยแล้ว!")
        return redirect(url_for("sauces"))

    return redirect(url_for("random_page"))


@app.route("/reset", methods=["POST"])
def reset():
    username = session.get("username")
    name = session.get("name")
    role = session.get("role")

    session.clear()

    session["username"] = username
    session["name"] = name
    session["role"] = role
    return redirect(url_for("home"))


# ===================== สมาชิก & ประวัติการสั่งซื้อ =====================

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        ok, message = auth.register_user(
            request.form.get("username", ""),
            request.form.get("password", ""),
            request.form.get("confirm", ""),
            request.form.get("name", ""),
        )
        flash(message)
        if ok:
            return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = auth.check_login(
            request.form.get("username", ""),
            request.form.get("password", ""),
        )
        if user is not None:
            session["username"] = user["username"]
            session["name"] = user["name"]
            session["role"] = user["role"]
            if user["role"] == "admin":
                return redirect(url_for("admin_orders"))
            return redirect(url_for("welcome"))     # ลูกค้าเห็นหน้าต้อนรับครั้งเดียวหลังล็อกอิน (ข้ามได้ ไม่บังคับ)
        flash("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/history")
def order_history():
    username = session.get("username")
    if not username:
        return redirect(url_for("login"))

    all_orders = orders.load_orders()
    user_orders = []
    for o in all_orders:
        if o.get("username") == username:
            item = normalize_order(o)
            item["seconds_left"] = orders.seconds_left(o)
            deadline = orders.payment_deadline(o)
            item["deadline_text"] = deadline.strftime("%H:%M") if deadline else ""
            user_orders.append(item)

    user_orders.reverse()
    return render_template("history.html", orders=user_orders,
                           member=member_codes.summary(username))


@app.route("/reorder/<order_id>", methods=["POST"])
def reorder(order_id):
    order = orders.find_order(order_id)
    if not order or str(order.get("username", "")).lower() != str(session.get("username", "")).lower():
        flash("ไม่พบออเดอร์นี้")      # สั่งซ้ำได้เฉพาะออเดอร์ของตัวเอง (กันดูรายการของคนอื่นด้วยการเดาเลขออเดอร์)
        return redirect(url_for("order_history"))

    order = normalize_order(order)

    if "soup" in order and isinstance(order["soup"], dict):
        session["soup_id"] = str(order["soup"].get("id"))
    session["spicy"] = order.get("spicy_level", 1)

    cart_dict = {}
    for item in order.get("lines", []):
        p_id = str(item.get("id"))
        qty = item.get("qty", 1)
        if p_id:
            cart_dict[p_id] = qty

    session["cart"] = cart_dict
    session.modified = True
    flash("ดึงรายการสินค้าจากออเดอร์เดิมเข้าตะกร้าเรียบร้อยแล้ว!")
    return redirect(url_for("cart_page"))


# ===================== ปักหมุดจัดส่ง & เช็คเอาต์ =====================

@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    if "soup_id" not in session:
        return redirect(url_for("home"))

    blocked = closed_redirect()
    if blocked:
        return blocked

    soup = safe_find_soup(session["soup_id"])
    items, items_total, pricing = get_pricing(soup)

    if not split_items(items)[0]:
        flash("ตะกร้ายังไม่มีวัตถุดิบ กรุณาเลือกวัตถุดิบอย่างน้อย 1 อย่างก่อนนะ")
        return redirect(url_for("shop"))

    form = session.get("delivery", {})
    error = ""

    if request.method == "POST":
        name = request.form.get("fullname", "").strip() or request.form.get("name", "").strip()
        phone = request.form.get("phone", "").replace("-", "").replace(" ", "").strip()
        address = request.form.get("address", "").strip()
        note = request.form.get("note", "").strip()

        try:
            lat = float(request.form.get("lat", ""))
            lng = float(request.form.get("lng", ""))
        except ValueError:
            lat = None
            lng = None

        form = {
            "name": name,
            "phone": phone,
            "address": address,
            "note": note,
            "lat": lat,
            "lng": lng,
        }

        if name == "":
            error = "กรุณากรอกชื่อผู้รับ"
        elif not (phone.isascii() and phone.isdigit() and 9 <= len(phone) <= 10):
            error = "เบอร์โทรต้องเป็นตัวเลข 9-10 หลัก"
        elif address == "":
            error = "กรุณากรอกที่อยู่จัดส่ง"
        elif lat is None:
            error = "กรุณาปักหมุดตำแหน่งที่จะให้ไปส่งบนแผนที่"
        elif not (-90 <= lat <= 90 and -180 <= lng <= 180):
            error = "ตำแหน่งไม่ถูกต้อง ลองปักหมุดใหม่อีกครั้ง"
        else:
            result = delivery.calculate_delivery(lat, lng)
            if not result["ok"]:
                error = (
                    f"ตำแหน่งนี้ห่างจากร้านประมาณ {result['km']} กม. "
                    f"ไกลเกินพื้นที่จัดส่ง (ส่งได้ไม่เกิน {delivery.MAX_KM} กม.)"
                )
            else:
                form["km"] = result["km"]
                form["fee"] = result["fee"]
                session["delivery"] = form
                session.modified = True
                return redirect(url_for("checkout_summary"))

    saved = None
    if form.get("lat") is not None and form.get("lng") is not None:
        saved = {"lat": form["lat"], "lng": form["lng"]}

    return render_template(
        "checkout.html",
        pricing=pricing,
        form=form,
        saved=saved,
        error=error,
        shop_lat=delivery.SHOP_LAT,
        shop_lng=delivery.SHOP_LNG,
        free_km=delivery.FREE_KM,
        rate=delivery.RATE_PER_KM,
        max_km=delivery.MAX_KM,
    )


@app.route("/checkout/summary")
def checkout_summary():
    if "soup_id" not in session:
        return redirect(url_for("home"))

    blocked = closed_redirect()
    if blocked:
        return blocked

    soup = safe_find_soup(session["soup_id"])
    items, items_total, pricing = get_pricing(soup)

    if not split_items(items)[0]:
        flash("ตะกร้ายังไม่มีวัตถุดิบ เลือกวัตถุดิบอย่างน้อย 1 อย่างก่อนนะ")
        return redirect(url_for("shop"))

    info = session.get("delivery")
    if not info:
        return redirect(url_for("checkout"))

    result = delivery.calculate_delivery(info["lat"], info["lng"])
    if not result["ok"]:
        return redirect(url_for("checkout"))

    breakdown = vat.calculate(pricing["final_total"], result["fee"])
    grand_total = breakdown["grand_total"]
    spicy_level = session.get("spicy", 1)

    return render_template(
        "checkout_summary.html",
        soup=soup,
        items=items,
        ingredients=split_items(items)[0],
        sauce_items=split_items(items)[1],
        seed_items=split_items(items)[2],
        pricing=pricing,
        info=info,
        km=result["km"],
        fee=result["fee"],
        vat=breakdown,
        grand_total=grand_total,
        spicy_level=spicy_level,
        spicy_name=SPICY_LEVELS.get(spicy_level, "เผ็ดน้อย"),
    )


# ===================== ออเดอร์ / ชำระเงิน / สลิป =====================

def get_my_order(order_id):
    order = orders.find_order(order_id)
    if order is None:
        return None
    if (
        order.get("username") == session.get("username")
        or session.get("role") == "admin"
    ):
        return normalize_order(order)
    return None


@app.errorhandler(413)
def file_too_large(error):
    flash("ไฟล์ใหญ่เกินไป (ไม่เกิน 5 MB) ลองย่อรูปหรือแคปหน้าจอสลิปแทนนะ")
    return redirect(request.referrer or url_for("home"))


@app.route("/order/create", methods=["POST"])
def place_order():
    if "soup_id" not in session:
        return redirect(url_for("home"))

    # ด่านสำคัญสุด: ปิดร้านอยู่ห้ามสร้างออเดอร์ ไม่ว่าลูกค้าจะมาทางหน้าไหนหรือยิง POST ตรง ๆ
    blocked = closed_redirect()
    if blocked:
        return blocked

    soup = safe_find_soup(session["soup_id"])
    items, items_total, pricing = get_pricing(soup)
    info = session.get("delivery")

    if not split_items(items)[0]:
        flash("กรุณาเลือกวัตถุดิบอย่างน้อย 1 รายการก่อนสั่งซื้อนะ")
        return redirect(url_for("shop"))

    if not info:
        return redirect(url_for("checkout"))

    result = delivery.calculate_delivery(info["lat"], info["lng"])
    if not result["ok"]:
        return redirect(url_for("checkout"))

    # เพดานออเดอร์ที่ยังไม่ชำระ กันคนสั่งทิ้งไว้จนของหมดร้าน
    if orders.count_unpaid(session["username"]) >= config.MAX_UNPAID_ORDERS:
        flash(f"คุณมีออเดอร์ที่ยังไม่ได้ชำระเงินครบ {config.MAX_UNPAID_ORDERS} ออเดอร์แล้ว "
              "กรุณาชำระเงินหรือยกเลิกออเดอร์เดิมก่อน จึงจะสั่งเพิ่มได้")
        return redirect(url_for("order_history"))

    problems = orders.check_stock(session.get("cart", {}))
    if problems:
        for text in problems:
            flash(text)
        return redirect(url_for("cart_page"))

    breakdown = vat.calculate(pricing["final_total"], result["fee"])     # สูตรเดียวกับหน้าสรุปยอดทุกประการ
    grand_total = breakdown["grand_total"]
    spicy_level = session.get("spicy", 1)

    # จองโค้ดสมาชิก (ถ้าใช้อยู่และมีผลกับยอดจริง) ก่อนสร้างออเดอร์ — จองสำเร็จแค่ครั้งเดียวต่อโค้ด กันสั่งซ้อนสองออเดอร์
    used_code = pricing.get("member_code", "")
    if used_code and not member_codes.reserve(used_code, session["username"]):
        session.pop("member_code", None)
        session.modified = True
        flash("สิทธิ์สมาชิกนี้ถูกใช้ไปแล้วหรือหมดอายุ กรุณาตรวจยอดอีกครั้งก่อนสั่งซื้อ")
        return redirect(url_for("cart_page"))

    try:
        order = orders.create_order(
            session["username"],
            soup,
            spicy_level,
            SPICY_LEVELS.get(spicy_level, "เผ็ดน้อย"),
            items,
            pricing,
            info,
            result["km"],
            result["fee"],
            grand_total,
            breakdown,
        )
    except Exception:
        if used_code:
            member_codes.release(used_code)
        raise
    if used_code:
        member_codes.attach(used_code, order["order_id"])

    for key in [
        "cart",
        "coupon",
        "member_code",
        "random_plan",
        "random_soup",
        "budget_plan",
        "delivery",
        "soup_id",
        "spicy",
    ]:
        session.pop(key, None)
    session.modified = True

    return redirect(url_for("order_pay", order_id=order["order_id"]))


@app.route("/order/<order_id>/pay")
def order_pay(order_id):
    order = get_my_order(order_id)
    if order is None:
        return redirect(url_for("home"))

    if order.get("status") not in (1, 2):
        if order.get("status") == orders.CANCELLED:
            flash("ออเดอร์นี้ถูกยกเลิกแล้ว (เช่น เกินเวลาชำระเงิน) ถ้าต้องการสั่งใหม่ใช้ปุ่ม \"สั่งอีกครั้ง\" ในประวัติได้เลย")
        return redirect(url_for("order_status", order_id=order_id))

    payload = promptpay.make_payload(
        config.PROMPTPAY_ID, order.get("total", order.get("grand_total", 0))
    )
    qr_svg = promptpay.make_qr_svg(payload)

    return render_template(
        "pay.html",
        order=order,
        qr_svg=qr_svg,
        seconds_left=orders.seconds_left(order),
        timeout_minutes=config.PAYMENT_TIMEOUT_MINUTES,
        account_name=config.PROMPTPAY_NAME,
        shop_name=config.SHOP_NAME,
        shop_phone=config.SHOP_PHONE,
        shop_address=config.SHOP_ADDRESS,
    )


@app.route("/order/<order_id>/slip", methods=["POST"])
def upload_slip(order_id):
    order = get_my_order(order_id)
    if order is None:
        return redirect(url_for("home"))
    if order.get("status") not in (1, 2):
        flash("ออเดอร์นี้ถูกยกเลิกหรือปิดแล้ว ส่งสลิปไม่ได้")
        return redirect(url_for("order_status", order_id=order_id))

    raw_order = orders.find_order(order_id)    # ออเดอร์ดิบ ไม่ใช่ตัวที่ normalize แล้ว
    ok, message = orders.save_slip(raw_order, request.files.get("slip"))
    flash(message)

    if ok:
        return redirect(url_for("order_status", order_id=order_id))
    return redirect(url_for("order_pay", order_id=order_id))


@app.route("/order/<order_id>/cancel", methods=["POST"])
def customer_cancel_order(order_id):
    """ลูกค้ายกเลิกออเดอร์ของตัวเองที่ยังไม่ได้ส่งสลิป (คืนสต็อกให้ทันที)"""
    raw_order = orders.find_order(order_id)
    ok, message = orders.cancel_by_customer(raw_order, session.get("username"))
    flash(message if not ok else "ยกเลิกออเดอร์เรียบร้อยแล้ว สินค้าถูกคืนเข้าสต็อก")
    return redirect(url_for("order_history"))


@app.route("/slip/<order_id>")
def view_slip(order_id):
    order = get_my_order(order_id)
    if order is None or not order.get("slip"):
        abort(404)
    return send_from_directory(orders.SLIP_FOLDER, order["slip"])


@app.route("/order/<order_id>")
def order_status(order_id):
    order = get_my_order(order_id)
    if order is None:
        return redirect(url_for("home"))

    # ยังไม่ได้แนบสลิป (หรือสลิปถูกปฏิเสธ -> กลับเป็นสถานะ 1) ดูสถานะไม่ได้
    # ต้องกลับไปหน้าชำระเงินเพื่อส่งสลิปก่อน
    if order.get("status") == 1:
        if not order.get("slip_note"):    # ถ้าโดนปฏิเสธ หน้าชำระเงินมีแจ้งเตือนอยู่แล้ว
            flash("กรุณาชำระเงินและแนบสลิปก่อน จึงจะดูสถานะออเดอร์ได้")
        return redirect(url_for("order_pay", order_id=order_id))

    steps = [
        (2, orders.STATUS_NAMES.get(2, "รอตรวจสอบ")),
        (3, orders.STATUS_NAMES.get(3, "ร้านกำลังจัดเตรียม")),
        (4, orders.STATUS_NAMES.get(4, "กำลังจัดส่ง")),
        (5, orders.STATUS_NAMES.get(5, "จัดส่งสำเร็จ")),
    ]

    is_owner = str(order.get("username", "")).lower() == str(session.get("username", "")).lower()
    can_rev, _ = reviews.can_review(order, session.get("username"))
    return render_template(
        "order_status.html",
        order=order,
        status_name=orders.STATUS_NAMES.get(order.get("status", 1), ""),
        steps=steps,
        can_review=can_rev and is_owner,
        show_review_form=can_rev and is_owner and (not order.get("review_skipped") or request.args.get("review") == "1"),
        review_comment_max=config.REVIEW_COMMENT_MAX,
        new_member_code=member_codes.issued_by(order.get("order_id"), order.get("username")) if order.get("status") == 5 else None,
    )


@app.route("/order/<order_id>/review", methods=["POST"])
def submit_review(order_id):
    """ลูกค้าให้ดาว 1-5 + คอมเมนต์ (ไม่บังคับ) หลังจัดส่งสำเร็จ — ตรวจเจ้าของ/สถานะ/ค่าดาวฝั่งเซิร์ฟเวอร์"""
    ok, message = reviews.submit(order_id, session.get("username"),
                                 request.form.get("stars", ""), request.form.get("comment", ""))
    flash(message)
    return redirect(url_for("order_status", order_id=order_id))


@app.route("/order/<order_id>/review/skip", methods=["POST"])
def skip_review(order_id):
    ok, message = reviews.skip(order_id, session.get("username"))
    flash(message)
    return redirect(url_for("order_status", order_id=order_id))


# ===================== หลังร้าน (Admin) =====================

@app.route("/admin")
def admin_orders():
    status_filter = request.args.get("status", "")
    keyword = request.args.get("q", "").strip()
    all_orders = orders.load_orders()

    for o in all_orders:
        normalize_order(o)

    counts = {}
    for order in all_orders:
        st = order.get("status", 1)
        counts[st] = counts.get(st, 0) + 1

    order_list = []
    for order in reversed(all_orders):
        if status_filter and str(order.get("status", 1)) != str(status_filter):
            continue
        if keyword:
            text = keyword.lower()
            o_id = str(order.get("order_id") or "").lower()
            c_name = str(order.get("customer_name") or "").lower()
            phone = str(order.get("phone") or "").lower()
            if text not in o_id and text not in c_name and text not in phone:
                continue
        order_list.append(order)

    return render_template(
        "admin_orders.html",
        order_list=order_list,
        counts=counts,
        status_names=orders.STATUS_NAMES,
        status_filter=status_filter,
        keyword=keyword,
        total_orders=len(all_orders),
    )


@app.route("/admin/order/<order_id>")
def admin_order_detail(order_id):
    order = orders.find_order(order_id)
    if order is None:
        flash("ไม่พบออเดอร์นี้")
        return redirect(url_for("admin_orders"))

    normalize_order(order)

    all_orders = orders.load_orders()
    counts = {}
    for o in all_orders:
        st = o.get("status", 1)
        counts[st] = counts.get(st, 0) + 1

    return render_template(
        "admin_order.html",
        order=order,
        status_name=orders.STATUS_NAMES.get(order.get("status", 1), ""),
        status_names=orders.STATUS_NAMES,
        counts=counts,
        total_orders=len(all_orders),
    )



# ===================== ใบเสร็จรับเงิน / ใบกำกับภาษีอย่างย่อ =====================

def _render_receipt(order, is_admin):
    normalize_order(order)
    return render_template("receipt.html", order=order, r=receipts.build(order), is_admin=is_admin)


@app.route("/order/<order_id>/receipt")
def order_receipt(order_id):
    """ลูกค้าดูใบเสร็จของตัวเอง (ออกให้หลังร้านตรวจสลิปผ่านแล้วเท่านั้น)"""
    order = get_my_order(order_id)
    if order is None:
        return redirect(url_for("home"))
    if not receipts.can_issue(order):
        flash("ใบเสร็จจะออกให้หลังร้านตรวจสอบการโอนเงินเรียบร้อยแล้ว")
        return redirect(url_for("order_status", order_id=order_id))
    return _render_receipt(order, False)


@app.route("/admin/order/<order_id>/receipt")
def admin_order_receipt(order_id):
    """แอดมินดู/พิมพ์ใบเสร็จของออเดอร์ที่ตรวจสลิปผ่านแล้ว"""
    order = orders.find_order(order_id)
    if order is None:
        flash("ไม่พบออเดอร์นี้")
        return redirect(url_for("admin_orders"))
    if not receipts.can_issue(order):
        flash("ออกใบเสร็จได้เฉพาะออเดอร์ที่ตรวจสลิปผ่านแล้ว")
        return redirect(url_for("admin_order_detail", order_id=order_id))
    return _render_receipt(order, True)


@app.route("/admin/order/<order_id>/action", methods=["POST"])
def admin_order_action(order_id):
  order = orders.find_order(order_id)
  if order is None:
    flash("ไม่พบออเดอร์นี้")
    return redirect(url_for("admin_orders"))
    
  action = request.form.get("action", "")
  note = request.form.get("note", "").strip()

  # แมปชื่อ Action ให้ตรงกับ orders.py
  action_map = {
      "preparing": "approve",
      "delivering": "deliver",
      "completed": "done",
  }
  action = action_map.get(action, action)

  ok, message = orders.apply_action(order, action, note)
  flash(message)
  return redirect(url_for("admin_order_detail", order_id=order_id))

@app.route("/admin/products")
def admin_products():
    if session.get("role") != "admin":
        return redirect(url_for("home"))
    products = storage.load_products()
    return render_template(
        "admin_products.html",
        products=products,
        categories=list(config.PRODUCT_CATEGORIES.keys()),
    )


def generate_next_product_id(products):
    """หาเลข ID สูงสุดแล้ว +1 กัน ID ชนกันหลังลบสินค้า (รูปแบบ p_N)"""
    max_id = 0
    for p in products:
        numbers = re.findall(r"\d+", str(p.get("id", "")))
        if numbers:
            max_id = max(max_id, int(numbers[0]))
    return f"p_{max_id + 1}"


def product_form_error(message):
    flash(message, "error")
    return redirect(url_for("admin_products"))


@app.route("/admin/product/save", methods=["POST"])
def admin_save_product():
    """เพิ่ม/แก้ไขสินค้า (ตรวจข้อมูลก่อนบันทึก ไม่ให้เกิด 500)"""
    if session.get("role") != "admin":
        return redirect(url_for("home"))

    prod_id = request.form.get("id", "").strip()
    name = request.form.get("name", "").strip()
    category = request.form.get("category", "").strip()
    detail = request.form.get("detail", "").strip()
    available = request.form.get("available") == "on"

    if name == "":
        return product_form_error("กรุณากรอกชื่อสินค้า")
    if category not in config.PRODUCT_CATEGORIES:
        return product_form_error("หมวดหมู่ไม่ถูกต้อง กรุณาเลือกจากรายการ")
    try:
        price = float(request.form.get("price", ""))
        stock = int(request.form.get("stock", ""))
    except ValueError:
        return product_form_error("ราคาต้องเป็นตัวเลข และสต็อกต้องเป็นจำนวนเต็ม")
    if not math.isfinite(price) or price < 0 or stock < 0:
        return product_form_error("ราคาและสต็อกต้องไม่ติดลบ")

    products = storage.load_products()
    target = None
    if prod_id:
        for p in products:
            if str(p["id"]) == prod_id:
                target = p
        if target is None:
            return product_form_error("ไม่พบสินค้าที่ต้องการแก้ไข")
        product_id = prod_id
    else:
        product_id = generate_next_product_id(products)

    # รูปภาพ: ตรวจจากเนื้อไฟล์จริง และตั้งชื่อไฟล์เองจากรหัสสินค้า
    # (เดิมใช้ secure_filename ซึ่งตัดอักษรไทยทิ้ง "ไก่.jpg" จึงกลายเป็นไฟล์ชื่อ "jpg")
    image_name = None
    image_file = request.files.get("image_file")
    if image_file and image_file.filename:
        ext = orders.detect_image_type(image_file.read(12))
        image_file.seek(0)
        if ext is None:
            return product_form_error("รองรับเฉพาะรูป JPG, PNG, WEBP")
        folder = config.PRODUCT_CATEGORIES[category]
        upload_folder = os.path.join(app.static_folder, "images", folder)
        os.makedirs(upload_folder, exist_ok=True)
        filename = f"{product_id}.{ext}"
        image_file.save(os.path.join(upload_folder, filename))
        image_name = f"{folder}/{filename}"

    if target is not None:
        target.update({
            "name": name, "category": category, "price": price,
            "stock": stock, "detail": detail, "available": available,
        })
        if image_name:
            target["image"] = image_name
    else:
        products.append({
            "id": product_id,
            "name": name,
            "category": category,
            "price": price,
            "stock": stock,
            "detail": detail,
            "image": image_name or "",
            "available": available,
        })

    storage.save_products(products)
    flash("บันทึกข้อมูลสินค้าเรียบร้อยแล้ว", "success")
    return redirect(url_for("admin_products"))


@app.route("/admin/product/delete/<prod_id>", methods=["POST"])
def admin_delete_product(prod_id):
    if session.get("role") != "admin":
        return redirect(url_for("home"))

    products = storage.load_products()
    products = [p for p in products if str(p["id"]) != str(prod_id)]
    if hasattr(storage, "save_products"):
        storage.save_products(products)
    flash("ลบสินค้าเรียบร้อยแล้ว", "success")
    return redirect(url_for("admin_products"))


@app.route("/admin/report")
def admin_report():
    """สรุปรายได้รายวัน/รายเดือน + วัตถุดิบที่ลูกค้าสั่งมากสุด"""
    try:
        days = int(request.args.get("days", 30))
    except ValueError:
        days = 30
    if days not in (0, 7, 30):
        days = 30
    data = report.build_report(
        request.args.get("basis", "paid"),
        request.args.get("month", ""),
        days,
    )
    return render_template("admin_report.html", **data)


# ===================== หลังร้าน: ตั้งค่าร้าน / รีวิว =====================

@app.route("/admin/settings")
def admin_settings():
    """เปิด-ปิดร้าน, แถบประกาศโปรโมชัน, ดูกติกาและโค้ดสมาชิก"""
    return render_template(
        "admin_settings.html",
        mode=settings.load()["shop_mode"],
        closed_note=settings.load()["closed_note"],
        promo=settings.load()["promo"],
        receipt=settings.load()["receipt"],
        promo_max=config.PROMO_BANNER_MAX,
        hours_error=shop_status.hours_config_error(),
        codes=member_codes.all_codes()[:30],
        rules={
            "every": config.MEMBER_REWARD_EVERY, "baht": config.MEMBER_REWARD_BAHT,
            "min": config.MEMBER_REWARD_MIN_ORDER, "days": config.MEMBER_REWARD_VALID_DAYS,
            "enabled": config.MEMBER_REWARD_ENABLED,
            "stack_coupon": config.MEMBER_CODE_STACK_WITH_COUPON,
        },
    )


@app.route("/admin/settings/shop", methods=["POST"])
def admin_settings_shop():
    ok, message = settings.set_shop_mode(request.form.get("mode", ""), request.form.get("closed_note", ""))
    flash(message)
    back = "admin_orders" if request.form.get("next") == "admin_orders" else "admin_settings"
    return redirect(url_for(back))


@app.route("/admin/settings/receipt", methods=["POST"])
def admin_settings_receipt():
    ok, message = settings.set_receipt(request.form)
    flash(message)
    return redirect(url_for("admin_settings"))


@app.route("/admin/settings/promo", methods=["POST"])
def admin_settings_promo():
    ok, message = settings.set_promo(request.form.get("enabled") == "on", request.form.get("text", ""))
    flash(message)
    return redirect(url_for("admin_settings"))


@app.route("/admin/reviews")
def admin_reviews():
    """คะแนนเฉลี่ย + ออเดอร์ที่ได้ดาวต่ำ + รีวิวทั้งหมด (เห็นเฉพาะแอดมิน ไม่โชว์ลูกค้า)"""
    view = request.args.get("view", "all")
    data = reviews.summary(max_stars=config.LOW_STAR_THRESHOLD if view == "low" else None)
    return render_template("admin_reviews.html", view=view, **data)


# ===================== หลังร้าน: แจ้งเตือนสลิป/ออเดอร์ใหม่/สต็อก (v1.9) =====================

@app.route("/admin/api/alerts")
def admin_api_alerts():
    """JSON ให้หน้าแอดมินถามซ้ำทุก ๆ ไม่กี่วินาที (สิทธิ์ admin ตรวจที่ before_request เพราะชื่อขึ้นต้น admin_)"""
    resp = jsonify(alerts.summary())
    resp.headers["Cache-Control"] = "no-store"
    return resp


if __name__ == "__main__":
    app.run(debug=True)