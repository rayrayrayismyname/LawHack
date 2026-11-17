// 罰單申訴通：填寫流程（步驟切換、AI 辨識、事實確認、證據清單、草稿保存）
(function () {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const form = $("#appeal-form");
  const init = JSON.parse($("#initial").textContent);
  const FLAGS = ["plate_mismatch", "evidence_unclear", "sign_obscured", "emergency", "not_driver", "is_speeding"];
  const DRAFT_KEY = "ticket-appeal-draft-v1";
  const touched = new Set();     // 使用者手動改過的欄位，AI 不覆蓋
  let step = 1, factsFor = null;

  function toast(msg) {
    const t = document.createElement("div");
    t.className = "toast"; t.textContent = msg; t.setAttribute("role", "status");
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 2600);
  }

  async function postJSON(url, body) {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || "伺服器忙碌中，請稍後再試。");
    return j;
  }

  // ---------------------------------------------------------------- 步驟
  function go(n) {
    step = Math.max(1, Math.min(4, n));
    $$(".step-panel").forEach(p => p.classList.toggle("current", +p.dataset.step === step));
    $$("#stepper li").forEach(li => {
      const k = +li.dataset.go;
      li.classList.toggle("active", k === step);
      li.classList.toggle("done", k < step);
      li.setAttribute("aria-current", k === step ? "step" : "false");
    });
    if (step === 3) loadFacts();
    if (step === 4) checkMissing();
    const panel = $(`.step-panel[data-step="${step}"]`);
    panel.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
    const first = panel.querySelector("input:not([type=hidden]):not([hidden]), select, textarea");
    if (first) first.focus({ preventScroll: true });
  }
  $$("[data-next]").forEach(b => b.addEventListener("click", () => go(step + 1)));
  $$("[data-prev]").forEach(b => b.addEventListener("click", () => go(step - 1)));
  $$("#stepper li").forEach(li => { li.style.cursor = "pointer"; li.addEventListener("click", () => go(+li.dataset.go)); });

  form.addEventListener("input", e => { if (e.target.name) touched.add(e.target.name); saveDraft(); });
  form.addEventListener("change", e => { if (e.target.name) touched.add(e.target.name); saveDraft(); toggleSpeed(); });

  // ---------------------------------------------------------------- 法條檢查
  async function checkArticle(article, vehicle, box) {
    if (!article.trim()) { box.hidden = true; return; }
    try {
      const r = await postJSON("/api/check-article", { article, vehicle_type: vehicle });
      box.className = "check-result " + r.status;
      const head = { no: "不可被民眾檢舉", conditional: "有條件可檢舉", yes: "可被民眾檢舉", uncertain: "需要完整項款", invalid: "格式無法辨識" }[r.status];
      box.textContent = `${r.label ? r.label + "：" : ""}${head}。${r.message}`;
      box.hidden = false;
    } catch (e) { box.hidden = true; }
  }
  const art = $("#article"), artBox = $("#article-check");
  const runArtCheck = () => { if ($("#source").value === "民眾檢舉") checkArticle(art.value, $("#vehicle_type").value, artBox); else artBox.hidden = true; };
  art.addEventListener("blur", runArtCheck);
  $("#source").addEventListener("change", runArtCheck);
  $("#vehicle_type").addEventListener("change", runArtCheck);
  $("#q-go").addEventListener("click", () => checkArticle($("#q-article").value, $("#q-vehicle").value, $("#q-result")));
  $("#q-article").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); $("#q-go").click(); } });

  // ---------------------------------------------------------------- 罰單照片辨識
  const imgInput = $("#ticket-image"), drop = $("#drop");
  function markAI(name) {
    const el = form.elements[name];
    if (!el) return;
    const field = (el.closest && el.closest(".field, .toggle")) || (el[0] && el[0].closest(".field, .toggle"));
    if (!field) return;
    field.classList.add("ai");
    const label = field.querySelector("label") || field;
    if (field.classList.contains("field") && !label.querySelector(".badge")) {
      const b = document.createElement("span"); b.className = "badge"; b.textContent = "AI"; label.appendChild(b);
    }
  }
  async function extract(file) {
    if (!init.ai || !file) return;
    const prev = $("#ticket-preview");
    prev.src = URL.createObjectURL(file); prev.hidden = false;
    $("#drop-title").textContent = "辨識中…";
    const fd = new FormData(); fd.append("image", file);
    try {
      const r = await fetch("/api/extract", { method: "POST", body: fd });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error);
      let n = 0;
      for (const [k, v] of Object.entries(j.fields || {})) {
        const el = form.elements[k];
        if (el && !el.value && !touched.has(k)) { el.value = v; markAI(k); n++; }
      }
      $("#drop-title").textContent = n ? `已自動填入 ${n} 個欄位` : "沒有辨識到新的欄位";
      $("#drop-note").textContent = (j.warnings || []).join(" ");
      runArtCheck(); saveDraft();
    } catch (e) {
      $("#drop-title").textContent = "辨識失敗，請手動輸入";
      $("#drop-note").textContent = e.message || "";
    }
  }
  if (init.ai) {
    imgInput.addEventListener("change", () => extract(imgInput.files[0]));
    ["dragover", "dragenter"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
    drop.addEventListener("drop", e => extract(e.dataTransfer.files[0]));
  } else { drop.style.cursor = "default"; }

  // ---------------------------------------------------------------- 說明經過：快捷句與語音
  const st = $("#statement");
  $$(".chip[data-add]").forEach(c => c.addEventListener("click", () => {
    st.value = (st.value.trim() ? st.value.trim() + "\n" : "") + c.dataset.add;
    touched.add("statement"); saveDraft(); st.focus();
  }));
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (SR) {
    const mic = $("#mic"); mic.hidden = false;
    let rec = null;
    mic.addEventListener("click", () => {
      if (rec) { rec.stop(); return; }
      rec = new SR(); rec.lang = "zh-TW"; rec.interimResults = false; rec.continuous = true;
      rec.onresult = e => {
        for (let i = e.resultIndex; i < e.results.length; i++) if (e.results[i].isFinal) st.value += e.results[i][0].transcript;
        saveDraft();
      };
      rec.onend = () => { rec = null; mic.classList.remove("rec"); mic.textContent = "語音輸入"; };
      rec.onerror = () => toast("無法使用麥克風，請改用打字。");
      rec.start(); mic.classList.add("rec"); mic.textContent = "停止錄音";
    });
  }

  // ---------------------------------------------------------------- 確認事實
  function setFact(k, v) {
    const el = form.elements[k];
    if (!el || touched.has(k)) return false;
    if (FLAGS.includes(k)) { if (v === true && !el.checked) { el.checked = true; return true; } return false; }
    if (k === "repeat_ticket_times") { if (!el.value && v.length) { el.value = v.join("\n"); return true; } return false; }
    if (typeof v === "boolean") v = v ? "yes" : "no";
    if (!el.value && v !== null && v !== undefined) { el.value = String(v); return true; }
    return false;
  }
  // 罰單本身就看得出是超速單時，預先勾選（使用者可以取消）
  function speedingFromTicket() {
    const a = art.value, fact = form.elements.violation_fact.value;
    return /第\s*(40|四十)\s*條(?!之)/.test(a) || /^\s*40(\D|$)/.test(a) || /超速|時速|速限/.test(fact);
  }
  async function loadFacts() {
    $("#facts_confirmed").value = "1";
    const sp = form.elements.is_speeding;
    if (!touched.has("is_speeding") && !sp.checked && speedingFromTicket()) {
      sp.checked = true; markAI("is_speeding"); toggleSpeed();
    }
    const statement = st.value.trim();
    const key = statement + "|" + art.value;
    if (factsFor === key) return;
    factsFor = key;
    const box = $("#facts-status");
    if (!statement) { box.hidden = false; box.textContent = "你還沒有說明經過，請直接在下方確認或勾選。"; return; }
    box.hidden = false; box.textContent = "正在整理你的說明…";
    const ticket = {};
    ["source", "article", "vehicle_type", "violation_time", "violation_fact", "violation_place"].forEach(k => ticket[k] = form.elements[k].value);
    try {
      const j = await postJSON("/api/facts", { ticket, statement });
      const filled = [];
      for (const [k, v] of Object.entries(j.facts || {})) if (setFact(k, v)) { markAI(k); filled.push(k); }
      box.textContent = j.source === "ai"
        ? `AI 從你的說明整理出 ${filled.length} 項事實（淺藍色標示），請確認。`
        : `系統用關鍵字整理出 ${filled.length} 項事實（淺藍色標示）。目前未啟用 AI，請仔細確認。`;
      if (j.summary) { const s = $("#facts-summary"); s.hidden = false; s.textContent = "AI 整理的經過：" + j.summary; }
      toggleSpeed(); saveDraft();
    } catch (e) { box.textContent = e.message + " 你仍然可以直接在下方確認。"; }
  }
  function toggleSpeed() {
    $("#speed-fields").hidden = !form.elements.is_speeding.checked;
    const citizen = form.elements.source.value === "民眾檢舉";
    $$(".citizen-only").forEach(el => { el.hidden = !citizen; });
  }
  toggleSpeed();

  // ---------------------------------------------------------------- 證據清單
  const evList = $("#ev-list"), evText = $("#evidence_text");
  evText.hidden = true;
  function evRow(name = "", desc = "") {
    const row = document.createElement("div"); row.className = "ev-row";
    row.innerHTML = '<input type="text" class="name" placeholder="證據名稱（例：現場照片）" aria-label="證據名稱">' +
      '<input type="text" class="desc" placeholder="說明（例：隔天拍攝，標誌遭樹枝遮蔽）" aria-label="證據說明">' +
      '<button type="button" class="icon-btn" aria-label="刪除這項證據">×</button>';
    row.querySelector(".name").value = name; row.querySelector(".desc").value = desc;
    row.querySelector("button").addEventListener("click", () => { row.remove(); saveDraft(); });
    row.addEventListener("input", saveDraft);
    evList.appendChild(row);
  }
  function evCollect() {
    return $$(".ev-row", evList).map(r => ({ name: r.querySelector(".name").value.trim(), description: r.querySelector(".desc").value.trim() })).filter(e => e.name);
  }
  $("#ev-add").addEventListener("click", () => { evRow(); evList.lastChild.querySelector("input").focus(); });
  $("#evidence-files").addEventListener("change", e => {
    Array.from(e.target.files).forEach(f => evRow(f.name.replace(/\.[^.]+$/, ""), ""));
    e.target.value = ""; saveDraft();
  });

  // ---------------------------------------------------------------- 送出
  function checkMissing() {
    const miss = [];
    if (!form.elements.source.value) miss.push("舉發方式");
    if (!art.value.trim()) miss.push("違反法條");
    if (!form.elements.violation_time.value.trim()) miss.push("違規時間");
    if (!form.elements.received_date.value.trim() && !form.elements.due_date.value.trim()) miss.push("收到通知單日期或應到案日期");
    const box = $("#missing");
    box.hidden = !miss.length;
    box.textContent = miss.length ? `還沒填：${miss.join("、")}。不填也能產生文件，但判斷會不完整、期限也無法計算。` : "";
  }
  form.addEventListener("submit", () => {
    evText.value = evCollect().map(e => e.description ? `${e.name}：${e.description}` : e.name).join("\n");
    if ($("#facts_confirmed").value === "1") {
      FLAGS.forEach(k => {
        if (!form.elements[k].checked) {
          const h = document.createElement("input"); h.type = "hidden"; h.name = k; h.value = "no"; form.appendChild(h);
        }
      });
    }
    const b = $("#submit"); b.disabled = true; b.textContent = "分析中…";
  });

  // ---------------------------------------------------------------- 草稿
  function saveDraft() {
    try {
      const data = {};
      $$("input, select, textarea", form).forEach(el => {
        if (!el.name || el.type === "file" || el.type === "hidden") return;
        data[el.name] = el.type === "checkbox" ? el.checked : el.value;
      });
      data.__evidence = evCollect();
      localStorage.setItem(DRAFT_KEY, JSON.stringify(data));
      $("#draft-state").textContent = "已自動儲存在這台裝置。";
    } catch (e) { /* 瀏覽器不允許儲存時就略過 */ }
  }
  function loadDraft() {
    let data = null;
    try { data = JSON.parse(localStorage.getItem(DRAFT_KEY) || "null"); } catch (e) { return false; }
    if (!data) return false;
    for (const [k, v] of Object.entries(data)) {
      const el = form.elements[k];
      if (!el || k.startsWith("__")) continue;
      if (el.type === "checkbox") el.checked = !!v; else el.value = v;
    }
    (data.__evidence || []).forEach(e => evRow(e.name, e.description));
    return true;
  }
  $("#draft-clear").addEventListener("click", () => {
    try { localStorage.removeItem(DRAFT_KEY); } catch (e) {}
    location.href = "/";
  });

  // ---------------------------------------------------------------- 初始化
  if (!init.sample && loadDraft()) {
    $("#draft-state").textContent = "已載入上次沒填完的草稿。";
  } else {
    (init.evidence || []).forEach(e => evRow(e.name, e.description || ""));
  }
  if (!evList.children.length) evRow();
  go(1);
  window.scrollTo(0, 0);
  runArtCheck();
})();
