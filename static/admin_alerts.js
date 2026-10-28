/* admin_alerts.js - แจ้งเตือนหลังร้าน: ออเดอร์ใหม่ / สลิปเข้า / สต็อกใกล้หมด (ทำงานทุกหน้าแอดมิน)
 *
 * - ถามเซิร์ฟเวอร์ทุก N วินาที (GET /admin/api/alerts) แล้วอัปเดตป้ายตัวเลขบนเมนูและการ์ดหน้าจัดการออเดอร์
 * - เสียงสร้างด้วย Web Audio (ไม่ต้องมีไฟล์เสียง) · เบราว์เซอร์บังคับให้ผู้ใช้ "แตะ/คลิก" หน้าเว็บก่อนถึงจะส่งเสียงได้
 *   ปุ่ม 🔔 บนเมนูจึงต้องกดเปิดหนึ่งครั้ง และหลังรีเฟรชอาจต้องแตะหน้าจอที่ไหนก็ได้อีกครั้งเพื่อปลุกเสียง
 * - จำว่า "เห็นออเดอร์ไหนไปแล้ว" ใน localStorage จึงไม่ดังซ้ำเมื่อเปลี่ยนหน้า/รีเฟรช
 * - ข้อความทุกอย่างใส่ด้วย textContent (ชื่อลูกค้า/ชื่อสินค้ามาจากผู้ใช้ ห้ามใส่เป็น HTML)
 */
(function () {
  "use strict";

  var script = document.currentScript;
  if (!script) { return; }
  var URL_ALERTS = script.getAttribute("data-url");
  var URL_ORDER = script.getAttribute("data-order-url") || "";      // มี __ID__ ให้แทนที่
  var URL_PRODUCTS = script.getAttribute("data-products-url") || "";
  var URL_SLIPS = script.getAttribute("data-slips-url") || "";        // หน้ารายการออเดอร์ที่กรองสถานะ "รอตรวจสอบการโอนเงิน"
  var POLL_MS = Math.max(3, parseInt(script.getAttribute("data-poll") || "10", 10)) * 1000;

  var K_ORDERS = "mala_seen_orders";   // id ออเดอร์ที่เคยเห็น (สถานะ 1-2)
  var K_SLIPS = "mala_seen_slips";     // id ออเดอร์ที่ "รอตรวจสลิป" ที่เคยเห็น (ถูกตรวจแล้ว/ถูกตีกลับจะหลุดจากชุดนี้)
  var K_LOW = "mala_seen_low";         // id สินค้าที่เคยเตือนว่าใกล้หมด
  var K_SOUND = "mala_alert_sound";    // "1" = ผู้ใช้เปิดเสียงไว้

  var originalTitle = document.title;
  var failures = 0;
  var offlineToast = null;

  // ---------- localStorage แบบกันพัง (โหมดส่วนตัว/ปิดการเก็บข้อมูลก็ไม่ล่ม) ----------
  function load(key) {
    try {
      var raw = localStorage.getItem(key);
      return raw === null ? null : JSON.parse(raw);
    } catch (e) { return null; }
  }
  function save(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* ไม่เป็นไร */ }
  }

  // ---------- เสียง ----------
  var ctx = null;
  function getCtx() {
    if (ctx) { return ctx; }
    var AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) { return null; }
    try { ctx = new AC(); } catch (e) { ctx = null; }
    return ctx;
  }

  function soundWanted() { return load(K_SOUND) === 1; }

  function note(freq, start, dur, vol) {
    var c = getCtx();
    if (!c) { return; }
    var osc = c.createOscillator();
    var gain = c.createGain();
    osc.type = "sine";
    osc.frequency.value = freq;
    var t0 = c.currentTime + start;
    gain.gain.setValueAtTime(0.0001, t0);
    gain.gain.exponentialRampToValueAtTime(vol, t0 + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    osc.connect(gain);
    gain.connect(c.destination);
    osc.start(t0);
    osc.stop(t0 + dur + 0.05);
  }

  // order = "ติ๊ง-ต่อง" 2 โน้ต (ออเดอร์ใหม่ ยังไม่จ่าย) · slip = 3 โน้ตไล่ขึ้น ซ้ำ 2 รอบ ดังกว่า (สลิปเข้า ต้องไปตรวจ)
  function chime(kind) {
    if (!soundWanted()) { return; }
    var c = getCtx();
    if (!c || c.state !== "running") { return; }
    if (kind === "slip") {
      for (var r = 0; r < 2; r++) {
        note(784, r * 0.9, 0.35, 0.5);
        note(988, r * 0.9 + 0.18, 0.35, 0.5);
        note(1319, r * 0.9 + 0.36, 0.5, 0.5);
      }
    } else {
      note(880, 0, 0.3, 0.35);
      note(1175, 0.16, 0.45, 0.35);
    }
  }

  // ---------- ปุ่มเปิด/ปิดเสียง ----------
  var toggle = document.getElementById("alert-sound-toggle");

  function paintToggle() {
    if (!toggle) { return; }
    var label = toggle.querySelector(".alert-sound-label");
    var wanted = soundWanted();
    var running = !!(ctx && ctx.state === "running");
    toggle.classList.toggle("is-on", wanted && running);
    toggle.classList.toggle("is-pending", wanted && !running);
    toggle.classList.toggle("is-offline", failures >= 3);
    var text = "เสียง: ปิด";
    if (failures >= 3) { text = "ขาดการเชื่อมต่อ"; }
    else if (wanted && running) { text = "เสียง: เปิด"; }
    else if (wanted) { text = "แตะหน้าจอเพื่อเปิดเสียง"; }
    if (label) { label.textContent = text; }
    toggle.title = failures >= 3
      ? "ติดต่อเซิร์ฟเวอร์ไม่ได้ ระบบแจ้งเตือนอาจไม่ทำงาน (จะลองใหม่เอง)"
      : "เปิด/ปิดเสียงแจ้งเตือนออเดอร์ใหม่";
  }

  function wake() {
    var c = getCtx();
    if (c && c.state === "suspended") {
      c.resume().then(paintToggle, paintToggle);
    }
    paintToggle();
  }

  if (toggle) {
    toggle.addEventListener("click", function (ev) {
      ev.preventDefault();
      if (soundWanted()) {
        save(K_SOUND, 0);
      } else {
        save(K_SOUND, 1);
        var c = getCtx();
        if (c) {
          var p = c.resume();
          var done = function () { paintToggle(); chime("order"); };   // เล่นเสียงตัวอย่างให้รู้ว่าดัง
          if (p && p.then) { p.then(done, paintToggle); } else { done(); }
          return;
        }
      }
      paintToggle();
    });
  }

  // เปิดเสียงไว้จากรอบก่อนแต่เบราว์เซอร์ยังไม่ให้ส่งเสียง -> ปลุกตอนผู้ใช้แตะอะไรก็ได้ครั้งแรก
  ["pointerdown", "keydown", "touchstart"].forEach(function (evName) {
    document.addEventListener(evName, function once() {
      if (soundWanted()) { wake(); }
      if (ctx && ctx.state === "running") {
        document.removeEventListener(evName, once, true);
      }
    }, true);
  });
  if (soundWanted()) { getCtx(); }

  // ---------- ข้อความลอย (toast) ----------
  var box = null;
  function toast(text, opts) {
    opts = opts || {};
    if (!box) {
      box = document.createElement("div");
      box.className = "alert-toasts";
      box.setAttribute("role", "status");
      box.setAttribute("aria-live", "polite");
      document.body.appendChild(box);
    }
    var el = document.createElement(opts.href ? "a" : "div");
    el.className = "alert-toast " + (opts.kind || "");
    if (opts.href) { el.href = opts.href; }
    var strong = document.createElement("strong");
    strong.textContent = opts.title || "";
    var span = document.createElement("span");
    span.textContent = text;
    el.appendChild(strong);
    el.appendChild(span);
    var close = document.createElement("button");
    close.type = "button";
    close.className = "alert-toast-x";
    close.setAttribute("aria-label", "ปิด");
    close.textContent = "×";
    close.addEventListener("click", function (ev) {
      ev.preventDefault(); ev.stopPropagation(); el.remove();
    });
    el.appendChild(close);
    box.appendChild(el);
    while (box.children.length > 5) { box.removeChild(box.firstChild); }
    setTimeout(function () { if (el.parentNode) { el.remove(); } }, opts.ms || 15000);
    return el;
  }

  function orderHref(id) { return URL_ORDER.replace("__ID__", encodeURIComponent(id)); }
  function baht(n) { return Number(n || 0).toLocaleString("th-TH", { maximumFractionDigits: 2 }); }

  // ---------- วาดตัวเลข/รายการลงหน้า ----------
  function paint(d) {
    var counts = { slips: d.pending_slips, low: d.low_total };
    Object.keys(counts).forEach(function (k) {
      document.querySelectorAll('[data-alert-count="' + k + '"]').forEach(function (el) {
        el.textContent = counts[k];
      });
      document.querySelectorAll('[data-alert-badge="' + k + '"]').forEach(function (el) {
        el.textContent = counts[k];
        el.hidden = !counts[k];
      });
      document.querySelectorAll('[data-alert-card="' + k + '"]').forEach(function (el) {
        el.classList.toggle("is-active", counts[k] > 0);
      });
    });

    var list = document.getElementById("alert-low-list");
    if (list) {
      list.textContent = "";
      var rows = d.out_of_stock.map(function (r) { return { r: r, out: true }; })
        .concat(d.low_stock.map(function (r) { return { r: r, out: false }; }));
      if (!rows.length) {
        var ok = document.createElement("span");
        ok.className = "alert-ok";
        ok.textContent = "✔ สต็อกทุกรายการยังพอ (เกณฑ์เตือน ≤ " + d.threshold + " ชิ้น)";
        list.appendChild(ok);
      }
      rows.slice(0, 12).forEach(function (x) {
        var tag = document.createElement("a");
        tag.className = "stock-tag" + (x.out ? " is-out" : "");
        tag.href = URL_PRODUCTS || "#";
        tag.textContent = x.r.name + " · " + (x.out ? "หมด" : "เหลือ " + x.r.stock);
        list.appendChild(tag);
      });
      if (rows.length > 12) {
        var more = document.createElement("span");
        more.className = "alert-more";
        more.textContent = "และอีก " + (rows.length - 12) + " รายการ";
        list.appendChild(more);
      }
    }

    // ชื่อแท็บ: (3) จัดการออเดอร์ ... เห็นได้แม้เปิดหน้าอื่นอยู่
    document.title = (d.pending_slips ? "(" + d.pending_slips + ") " : "") + originalTitle;
  }

  // ---------- ตรวจว่ามีอะไรใหม่ ----------
  function detect(d) {
    var openIds = d.open_orders.map(function (o) { return o.id; });
    var seenOrders = load(K_ORDERS);
    var seenSlips = load(K_SLIPS);
    var seenLow = load(K_LOW);
    var lowNow = d.out_of_stock.concat(d.low_stock);
    var lowIds = lowNow.map(function (r) { return r.id; });

    var baseline = !Array.isArray(seenOrders) || !Array.isArray(seenSlips);   // เปิดครั้งแรก: จดไว้เฉย ๆ ไม่ดัง
    if (!baseline) {
      var byId = {};
      d.open_orders.forEach(function (o) { byId[o.id] = o; });
      var newSlips = d.slip_ids.filter(function (id) { return seenSlips.indexOf(id) < 0; });
      var newOrders = openIds.filter(function (id) {
        return seenOrders.indexOf(id) < 0 && newSlips.indexOf(id) < 0;
      });

      if (newSlips.length) {
        chime("slip");
        if (newSlips.length > 3) {
          toast("มี " + newSlips.length + " ออเดอร์ส่งสลิปเข้ามา รอตรวจ", { title: "สลิปเข้า", kind: "is-slip", href: URL_SLIPS, ms: 25000 });
        } else {
          newSlips.forEach(function (id) {
            var o = byId[id];
            toast("#" + id + " · " + o.name + " · " + baht(o.total) + " บาท — รอตรวจสลิป", {
              title: "สลิปเข้า", kind: "is-slip", href: orderHref(id), ms: 25000 });
          });
        }
      } else if (newOrders.length) {
        chime("order");
      }
      newOrders.slice(0, 3).forEach(function (id) {
        var o = byId[id];
        toast("#" + id + " · " + o.name + " · " + baht(o.total) + " บาท — รอลูกค้าชำระเงิน", {
          title: "ออเดอร์ใหม่", kind: "is-order", href: orderHref(id) });
      });
      if (newOrders.length > 3) {
        toast("และออเดอร์ใหม่อีก " + (newOrders.length - 3) + " รายการ", { title: "ออเดอร์ใหม่", kind: "is-order" });
      }
    }

    if (Array.isArray(seenLow)) {
      lowNow.filter(function (r) { return seenLow.indexOf(r.id) < 0; }).slice(0, 3).forEach(function (r) {
        toast(r.name + (r.stock <= 0 ? " หมดแล้ว" : " เหลือ " + r.stock + " ชิ้น"), {
          title: "สต็อกใกล้หมด", kind: "is-low", href: URL_PRODUCTS, ms: 20000 });
      });
    }

    // เก็บ id ออเดอร์ที่เคยเห็นไว้ไม่ลบ (กันออเดอร์ที่ถูกตีสลิปกลับเป็น "รอชำระ" แล้วดังเป็นออเดอร์ใหม่) จำกัด 500 ล่าสุด
    var merged = (Array.isArray(seenOrders) ? seenOrders : []).concat(
      openIds.filter(function (id) { return !Array.isArray(seenOrders) || seenOrders.indexOf(id) < 0; }));
    save(K_ORDERS, merged.slice(-500));
    save(K_SLIPS, d.slip_ids);          // แทนที่ทั้งชุด: สลิปที่ถูกตีกลับแล้วลูกค้าส่งใหม่ จะดังอีกครั้งตามต้องการ
    save(K_LOW, lowIds);
  }

  // ---------- วนถามเซิร์ฟเวอร์ ----------
  function poll() {
    fetch(URL_ALERTS, { credentials: "same-origin", cache: "no-store", headers: { "Accept": "application/json" } })
      .then(function (res) {
        var type = res.headers.get("content-type") || "";
        if (!res.ok || type.indexOf("json") < 0) { throw new Error("bad response"); }   // เช่น session หมดอายุ -> ถูกส่งไปหน้า login
        return res.json();
      })
      .then(function (d) {
        var wasOffline = failures >= 3;
        failures = 0;
        paint(d);
        detect(d);
        if (offlineToast) { offlineToast.remove(); offlineToast = null; }
        if (wasOffline) { toast("เชื่อมต่อได้อีกครั้งแล้ว", { title: "✔ ออนไลน์", ms: 5000 }); }
        paintToggle();
      })
      .catch(function () {
        failures += 1;
        if (failures === 3) {
          offlineToast = toast("ติดต่อเซิร์ฟเวอร์ไม่ได้ ระบบแจ้งเตือนออเดอร์อาจไม่ทำงาน (ลองรีเฟรชหน้า หรือเข้าสู่ระบบใหม่)",
                { title: "ขาดการเชื่อมต่อ", kind: "is-low", ms: 120000 });
        }
        paintToggle();
      });
  }

  paintToggle();
  poll();
  setInterval(poll, POLL_MS);
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) { poll(); }       // กลับมาที่แท็บ = เช็คทันที ไม่ต้องรอรอบ
  });
})();
