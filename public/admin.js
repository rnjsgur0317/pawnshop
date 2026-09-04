// 그냥전당포 - 관리자 페이지
"use strict";

const $ = (sel) => document.querySelector(sel);

function toast(msg, isError) {
  const el = $("#toast");
  el.textContent = msg;
  el.className = isError ? "show error" : "show";
  clearTimeout(el._t);
  el._t = setTimeout(() => (el.className = ""), 2600);
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function api(path, body) {
  const opt = body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : {};
  const res = await fetch(path, opt);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "요청 실패");
  return data;
}

function fmtDate(ts) {
  const d = new Date(ts * 1000);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

let cache = { sell: [], buy: [], stock: [] };
const filters = { sell: "전체", buy: "전체" };

// ---- 화면 전환
function show(view) {
  ["viewSetup", "viewLogin", "viewDash"].forEach((id) => ($("#" + id).style.display = id === view ? "" : "none"));
}

async function boot() {
  try {
    const st = await api("/api/admin/state");
    if (st.needs_setup) return show("viewSetup");
    if (!st.logged_in) return show("viewLogin");
    show("viewDash");
    await refresh();
  } catch (e) {
    toast("서버에 연결할 수 없습니다.", true);
  }
}
boot();

// ---- 초기 설정 / 로그인
$("#setupBtn").addEventListener("click", async () => {
  const pw = $("#setupPw").value, pw2 = $("#setupPw2").value;
  if (pw.length < 4) return toast("비밀번호는 4자 이상으로 하세요.", true);
  if (pw !== pw2) return toast("비밀번호 확인이 일치하지 않습니다.", true);
  try {
    await api("/api/admin/setup", { password: pw });
    toast("설정 완료!");
    show("viewDash");
    await refresh();
  } catch (e) { toast(e.message, true); }
});

$("#loginBtn").addEventListener("click", doLogin);
$("#loginPw").addEventListener("keydown", (e) => { if (e.key === "Enter") doLogin(); });
async function doLogin() {
  try {
    await api("/api/admin/login", { password: $("#loginPw").value });
    $("#loginPw").value = "";
    show("viewDash");
    await refresh();
  } catch (e) { toast(e.message, true); }
}

$("#logoutBtn").addEventListener("click", async () => {
  await api("/api/admin/logout", {});
  show("viewLogin");
});

// ---- 탭
document.querySelectorAll(".tabs button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".tab-page").forEach((p) => p.classList.toggle("active", p.id === "page-" + btn.dataset.tab));
  });
});

// ---- 필터
document.querySelectorAll(".filter-bar").forEach((bar) => {
  bar.querySelectorAll("button").forEach((b) => {
    b.addEventListener("click", () => {
      bar.querySelectorAll("button").forEach((x) => x.classList.toggle("active", x === b));
      filters[bar.dataset.filterFor] = b.dataset.f;
      render();
    });
  });
});

// ---- 데이터 로드
async function refresh() {
  try {
    const data = await api("/api/admin/data");
    cache = data;
    $("#setNotice").value = data.notice || "";
    document.querySelector(`input[name=setOpen][value="${data.open ? 1 : 0}"]`).checked = true;
    render();
  } catch (e) {
    if (String(e.message).includes("로그인")) return show("viewLogin");
    toast(e.message, true);
  }
}
setInterval(() => { if ($("#viewDash").style.display !== "none") refresh(); }, 30000);

// ---- 렌더링
function render() {
  const pendingSell = cache.sell.filter((r) => r.status === "대기").length;
  const pendingBuy = cache.buy.filter((r) => r.status === "대기").length;
  const incoming = cache.sell.filter((r) => r.delivery !== "직접" && !r.received && r.status !== "거절");

  $("#stats").innerHTML = `
    <div class="stat"><div class="num">${incoming.length}</div><div class="lbl">확인할 우편 물품</div></div>
    <div class="stat"><div class="num">${pendingSell}</div><div class="lbl">대기중 감정신청</div></div>
    <div class="stat"><div class="num">${pendingBuy}</div><div class="lbl">대기중 구매신청</div></div>
    <div class="stat"><div class="num">${cache.stock.filter((s) => s.visible && s.qty > 0).length}</div><div class="lbl">판매중 물품</div></div>`;

  setBadge("#cntIncoming", incoming.length);
  setBadge("#cntSell", pendingSell);
  setBadge("#cntBuy", pendingBuy);

  // 들어온 물품
  $("#incomingList").innerHTML = incoming.length
    ? incoming.map((r) => `
      <div class="req-card">
        <div class="head">
          <div>
            <div class="name"><b>${esc(r.item)} × ${esc(r.qty)}</b> <span class="sub">by ${esc(r.nickname)}</span></div>
            <div class="sub">${r.price ? "감정가: " + esc(r.price) + " · " : "감정 전 · "}${fmtDate(r.created_at)}${r.note ? " · " + esc(r.note) : ""}</div>
          </div>
          <span class="badge ${esc(r.status)}">${esc(r.status)}</span>
        </div>
        <div class="controls">
          <button class="small good" data-receive="${r.id}">수령 확인</button>
        </div>
      </div>`).join("")
    : '<div class="empty">확인할 물품이 없어요.</div>';
  $("#incomingList").querySelectorAll("[data-receive]").forEach((b) =>
    b.addEventListener("click", async () => {
      try {
        await api("/api/admin/request", { kind: "sell", id: +b.dataset.receive, received: true });
        toast("수령 확인 완료");
        refresh();
      } catch (e) { toast(e.message, true); }
    }));

  renderRequests("sell", "#sellList");
  renderRequests("buy", "#buyList");
  renderStock();
}

function setBadge(sel, n) {
  const el = $(sel);
  el.hidden = n === 0;
  el.textContent = n;
}

function renderRequests(kind, listSel) {
  const rows = cache[kind].filter((r) => filters[kind] === "전체" || r.status === filters[kind]);
  const box = $(listSel);
  box.innerHTML = rows.length
    ? rows.map((r) => `
      <div class="req-card">
        <div class="head">
          <div>
            <div class="name"><b>${esc(r.item)} × ${esc(r.qty)}</b> <span class="sub">by ${esc(r.nickname)}</span></div>
            <div class="sub">
              ${r.price ? (kind === "sell" ? "감정가" : "가격") + ": " + esc(r.price) + " · " : (kind === "sell" ? "감정 전 · " : "")}${fmtDate(r.created_at)}
              ${r.delivery ? " · " + (r.delivery === "직접" ? "직접 전달" : "우편" + (r.received ? "(수령됨)" : "(미수령)")) : ""}
              ${r.stock_id ? " · 재고연동 #" + r.stock_id : ""}
              ${r.note ? "<br>메모: " + esc(r.note) : ""}
            </div>
          </div>
          <span class="badge ${esc(r.status)}">${esc(r.status)}</span>
        </div>
        ${kind === "buy" && r.image ? `
        <div style="margin-top:10px">
          <div class="sub" style="margin-bottom:4px">입금내역 캡쳐 (클릭하면 크게 보기)</div>
          <a href="/api/admin/image?id=${r.id}" target="_blank">
            <img src="/api/admin/image?id=${r.id}" alt="입금내역"
                 style="max-height:130px;max-width:100%;border:1px solid var(--border-strong);border-radius:8px">
          </a>
        </div>` : ""}
        ${kind === "buy" && !r.image ? `<div class="sub" style="margin-top:8px">입금내역 캡쳐 없음 (자유 신청)</div>` : ""}
        <div class="controls">
          <select data-status>
            ${["대기", "승인", "거절", "완료"].map((s) => `<option ${s === r.status ? "selected" : ""}>${s}</option>`).join("")}
          </select>
          ${kind === "sell" ? `<input type="text" data-price maxlength="60" placeholder="감정가 (예: 32,000원)" value="${esc(r.price)}" style="flex:1;min-width:130px">` : ""}
          <input type="text" data-note maxlength="200" placeholder="유저에게 보일 답변" value="${esc(r.admin_note)}">
          <button class="small good" data-save>저장</button>
          <button class="small danger" data-delete>삭제</button>
        </div>
      </div>`).join("")
    : '<div class="empty">신청이 없어요.</div>';

  box.querySelectorAll(".req-card").forEach((card, i) => {
    card.querySelector("[data-save]").addEventListener("click", async () => {
      const body = {
        kind,
        id: rows[i].id,
        status: card.querySelector("[data-status]").value,
        admin_note: card.querySelector("[data-note]").value.trim(),
      };
      const priceInput = card.querySelector("[data-price]");
      if (priceInput) body.price = priceInput.value.trim();
      try {
        await api("/api/admin/request", body);
        toast("저장 완료");
        refresh();
      } catch (e) { toast(e.message, true); }
    });
    card.querySelector("[data-delete]").addEventListener("click", async () => {
      if (!confirm(`[${rows[i].item}] 신청을 삭제할까요? 되돌릴 수 없어요.`)) return;
      try {
        await api("/api/admin/request", { kind, id: rows[i].id, delete: true });
        toast("삭제 완료");
        refresh();
      } catch (e) { toast(e.message, true); }
    });
  });
}

function renderStock() {
  const box = $("#stockList");
  box.innerHTML = cache.stock.length
    ? cache.stock.map((s) => `
      <div class="req-card" style="${!s.visible || s.qty === 0 ? "opacity:.55" : ""}">
        <div class="head">
          <div>
            <div class="name"><b>${esc(s.item)}</b> <span class="price">${esc(s.price)}</span></div>
            <div class="sub">재고 ${s.qty}개${s.note ? " · " + esc(s.note) : ""}${s.visible ? "" : " · 숨김"}</div>
          </div>
        </div>
        <div class="controls">
          <input type="number" data-qty min="0" value="${s.qty}" style="max-width:90px;flex:none">
          <button class="small" data-setqty="${s.id}">수량 저장</button>
          <button class="small" data-toggle="${s.id}" data-visible="${s.visible}">${s.visible ? "숨기기" : "보이기"}</button>
          <button class="small danger" data-del="${s.id}">삭제</button>
        </div>
      </div>`).join("")
    : '<div class="empty">등록된 물품이 없어요.</div>';

  box.querySelectorAll("[data-setqty]").forEach((b) =>
    b.addEventListener("click", async () => {
      const qty = parseInt(b.parentElement.querySelector("[data-qty]").value, 10);
      if (isNaN(qty) || qty < 0) return toast("수량을 확인하세요.", true);
      try {
        await api("/api/admin/stock", { action: "update", id: +b.dataset.setqty, qty });
        toast("수량 변경 완료");
        refresh();
      } catch (e) { toast(e.message, true); }
    }));
  box.querySelectorAll("[data-toggle]").forEach((b) =>
    b.addEventListener("click", async () => {
      try {
        await api("/api/admin/stock", { action: "update", id: +b.dataset.toggle, visible: b.dataset.visible !== "1" });
        refresh();
      } catch (e) { toast(e.message, true); }
    }));
  box.querySelectorAll("[data-del]").forEach((b) =>
    b.addEventListener("click", async () => {
      if (!confirm("이 물품을 삭제할까요?")) return;
      try {
        await api("/api/admin/stock", { action: "delete", id: +b.dataset.del });
        toast("삭제 완료");
        refresh();
      } catch (e) { toast(e.message, true); }
    }));
}

// ---- 재고 등록
$("#stAdd").addEventListener("click", async () => {
  const body = {
    action: "add",
    item: $("#stItem").value.trim(),
    price: $("#stPrice").value.trim(),
    qty: parseInt($("#stQty").value, 10),
    note: $("#stNote").value.trim(),
  };
  if (!body.item || !body.price || isNaN(body.qty) || body.qty < 0) {
    return toast("물품/가격/수량을 확인하세요.", true);
  }
  try {
    await api("/api/admin/stock", body);
    ["stItem", "stPrice", "stNote"].forEach((id) => ($("#" + id).value = ""));
    $("#stQty").value = 1;
    toast("등록 완료");
    refresh();
  } catch (e) { toast(e.message, true); }
});

// ---- 설정
$("#setSave").addEventListener("click", async () => {
  try {
    await api("/api/admin/settings", {
      notice: $("#setNotice").value,
      open: document.querySelector("input[name=setOpen]:checked").value === "1",
    });
    toast("저장 완료");
    refresh();
  } catch (e) { toast(e.message, true); }
});

$("#pwChange").addEventListener("click", async () => {
  try {
    await api("/api/admin/password", { old: $("#pwOld").value, new: $("#pwNew").value });
    $("#pwOld").value = $("#pwNew").value = "";
    toast("비밀번호 변경 완료");
  } catch (e) { toast(e.message, true); }
});
