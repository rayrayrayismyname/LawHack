// 罰單申訴通：結果頁（編輯陳述意見書、儲存、複製、列印、待辦勾選）
(function () {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const rid = JSON.parse($("#rid").textContent);
  let dirty = false;

  function toast(msg) {
    const t = document.createElement("div");
    t.className = "toast"; t.textContent = msg; t.setAttribute("role", "status");
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 3200);
  }

  // 文字框自動長高
  function grow(t) { t.style.height = "auto"; t.style.height = t.scrollHeight + 4 + "px"; }
  $$(".doc textarea").forEach(t => {
    grow(t);
    t.addEventListener("input", () => {
      grow(t); dirty = true;
      const s = $("#save-state"); if (s) s.textContent = "有尚未儲存的修改";
    });
  });
  window.addEventListener("resize", () => $$(".doc textarea").forEach(grow));

  function collect() {
    return {
      facts: $("#l-facts").value,
      reasons: $$(".l-reason").map(t => t.value),
      evidence: $("#l-evidence").value.split("\n"),
      request: $("#l-request").value,
    };
  }

  async function save() {
    const btn = $("#save");
    btn.disabled = true; btn.textContent = "儲存中…";
    try {
      const r = await fetch(`/result/${rid}/letter`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(collect()),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || "儲存失敗");
      dirty = false;
      $("#save-state").textContent = "已儲存，Word 檔已更新";
      toast((j.warnings || [])[0] || "已儲存修改");
      return true;
    } catch (e) {
      toast("儲存失敗，請再試一次。");
      return false;
    } finally { btn.disabled = false; btn.textContent = "儲存修改"; }
  }

  if ($("#doc")) {
    $("#save").addEventListener("click", save);
    // 下載前若有未儲存的修改，先儲存再下載
    $$("a[data-dl]").forEach(a => a.addEventListener("click", async e => {
      if (!dirty) return;
      e.preventDefault();
      if (await save()) location.href = a.href;
    }));
    window.addEventListener("beforeunload", e => { if (dirty) { e.preventDefault(); e.returnValue = ""; } });

    $("#copy").addEventListener("click", async () => {
      const L = collect();
      const doc = $("#doc");
      const subject = doc.querySelector("p").textContent;
      const lines = ["交通違規陳述意見書", "", subject, "說明：", "一、事實經過", L.facts, "二、陳述理由"];
      L.reasons.forEach((x, i) => lines.push(`（${"一二三四五六七八九十"[i] || i + 1}）${x}`));
      lines.push("三、檢附證據");
      L.evidence.filter(x => x.trim()).forEach((x, i) => lines.push(`附件${i + 1}：${x}`));
      lines.push("四、請求事項", L.request);
      try { await navigator.clipboard.writeText(lines.join("\n")); toast("已複製全文，可貼到線上陳述表單"); }
      catch (e) { toast("瀏覽器不允許複製，請手動選取文字。"); }
    });
    $("#print").addEventListener("click", () => window.print());
  }

  // 待辦勾選：存在這台裝置
  $$(".checklist[data-store]").forEach(list => {
    const key = `ticket-appeal-${rid}-${list.dataset.store}`;
    let saved = [];
    try { saved = JSON.parse(localStorage.getItem(key) || "[]"); } catch (e) {}
    const boxes = $$("input[type=checkbox]", list);
    boxes.forEach((b, i) => {
      b.checked = !!saved[i];
      b.addEventListener("change", () => {
        try { localStorage.setItem(key, JSON.stringify(boxes.map(x => x.checked))); } catch (e) {}
      });
    });
  });
})();
