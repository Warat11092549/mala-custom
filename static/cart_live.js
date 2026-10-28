/* cart_live.js - กด + / − / ลบ แล้วอัปเดตเฉพาะการ์ดสินค้ากับแถบยอดรวม โดยไม่โหลดหน้าใหม่ (หน้าไม่เด้ง) */
(function () {
  var ACTION = /\/(add|decrease|remove)\//;
  var queue = Promise.resolve();

  // เอฟเฟกต์เล็ก ๆ ตอนการ์ดอัปเดต
  var style = document.createElement("style");
  style.textContent =
    "@keyframes liveFlash{0%{box-shadow:0 0 0 0 rgba(224,59,0,.45)}100%{box-shadow:0 0 0 14px rgba(224,59,0,0)}}" +
    ".live-flash{animation:liveFlash .5s ease-out}";
  document.head.appendChild(style);

  function swapById(doc, id) {
    var fresh = doc.getElementById(id);
    var old = document.getElementById(id);
    if (!fresh || !old) return false;
    old.replaceWith(fresh);
    return fresh;
  }

  function send(url, body, cardId, fallbackForm) {
    return fetch(url, {
      method: "POST",
      body: body,
      credentials: "same-origin",
      headers: { "X-Requested-With": "fetch" }
    })
      .then(function (res) {
        return res.text().then(function (html) { return { res: res, html: html }; });
      })
      .then(function (r) {
        var doc = new DOMParser().parseFromString(r.html, "text/html");
        var oldEl = document.querySelector("#live-bar [data-live-total]");
        var oldTotal = oldEl ? oldEl.textContent.trim() : null;
        var card = cardId ? swapById(doc, cardId) : true;
        swapById(doc, "live-bar");
        var newEl = document.querySelector("#live-bar [data-live-total]");      // ยอดเปลี่ยนจริงถึงจะเด้ง (กดแล้วไม่เปลี่ยน/สต็อกไม่พอ = ไม่ขยับ)
        if (newEl && oldTotal !== null && oldTotal !== newEl.textContent.trim()) {
          newEl.classList.add("bump");
        }
        if (!card) {                      // หน้าที่ได้กลับมาไม่ใช่หน้าเดิม (เช่น session หมดอายุ) -> ไปหน้านั้นตามปกติ
          window.location.href = r.res.url;
        } else if (card !== true) {
          card.classList.add("live-flash");
        }
      })
      .catch(function () {
        fallbackForm.submit();            // เน็ตมีปัญหา -> ส่งแบบเดิม
      });
  }

  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form.action || !ACTION.test(form.action)) return;
    var holder = form.closest(".product-card, .item-card");
    if (!holder) return;                  // ใช้เฉพาะในการ์ดสินค้า (หน้าตะกร้าทำงานแบบเดิม)
    e.preventDefault();
    var url = form.action;
    var body = new FormData(form);        // จับค่าไว้ตอนกดเลย กดรัว ๆ ก็ไม่ตกหล่น
    var cardId = holder.id;
    queue = queue.then(function () { return send(url, body, cardId, form); });
  });
})();
