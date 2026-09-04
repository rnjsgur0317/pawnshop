// 그냥전당포 - 유저 페이지
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

// ---- 탭
document.querySelectorAll(".tabs button").forEach((btn) => {
  btn.addEventListener("click", () => showTab(btn.dataset.tab));
});
function showTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab-page").forEach((p) => p.classList.toggle("active", p.id === "page-" + name));
}

// ---- 닉네임 기억
const savedNick = localStorage.getItem("nickname") || "";
["sellNick", "buyNick", "myNick"].forEach((id) => ($("#" + id).value = savedNick));
function rememberNick(nick) {
  localStorage.setItem("nickname", nick);
  ["sellNick", "buyNick", "myNick"].forEach((id) => ($("#" + id).value = nick));
}

// ---- 상점 정보 로드
async function loadShop() {
  try {
    const data = await api("/api/shop");
    $("#notice").textContent = data.notice || "";
    const badge = $("#openBadge");
    badge.className = "open-badge " + (data.open ? "open" : "closed");
    badge.textContent = data.open ? "영업중" : "휴업중 · 신청은 받아요";
    const list = $("#stockList");
    if (!data.stock.length) {
      list.innerHTML = '<div class="empty">지금은 판매 중인 물품이 없어요.</div>';
      return;
    }
    list.innerHTML = data.stock.map((s) => `
      <div class="item-row">
        <div style="display:flex;align-items:center;gap:12px;min-width:0">
          ${s.image ? `<img class="stock-thumb" src="/api/stock/image?id=${s.id}" alt="${esc(s.item)}" data-zoom>` : ""}
          <div>
            <div class="name">${esc(s.item)}</div>
            <div class="sub">재고 ${esc(s.qty)}개${s.note ? " · " + esc(s.note) : ""}</div>
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:10px">
          <span class="price">${esc(s.price)}</span>
          <button class="small good" data-order="${s.id}" data-item="${esc(s.item)}" data-price="${esc(s.price)}">주문</button>
        </div>
      </div>`).join("");
    list.querySelectorAll("[data-zoom]").forEach((img) =>
      img.addEventListener("click", () => window.open(img.src, "_blank")));
    list.querySelectorAll("[data-order]").forEach((b) =>
      b.addEventListener("click", () => {
        $("#buyItem").value = b.dataset.item;
        $("#buyQty").value = "1개";
        $("#buyStockId").value = b.dataset.order;
        $("#buyPriceText").textContent = b.dataset.price;
        $("#buyPriceBox").hidden = false;
        $("#buyImageRequired").hidden = false;
        showTab("buy");
        toast("구매신청 폼에 담았어요! 먼저 입금하고 캡쳐를 첨부해주세요.");
      }));
  } catch (e) {
    $("#notice").textContent = "서버에 연결할 수 없습니다.";
  }
}
loadShop();

// ---- 감정신청 (매입)
$("#sellSubmit").addEventListener("click", async () => {
  const nickname = $("#sellNick").value.trim();
  const body = {
    nickname,
    item: $("#sellItem").value.trim(),
    qty: $("#sellQty").value.trim(),
    delivery: document.querySelector('input[name=sellDelivery]:checked').value,
    note: $("#sellNote").value.trim(),
  };
  if (!body.nickname || !body.item || !body.qty) {
    return toast("닉네임/물품/수량을 모두 입력하세요.", true);
  }
  try {
    $("#sellSubmit").disabled = true;
    await api("/api/sell", body);
    rememberNick(nickname);
    ["sellItem", "sellQty", "sellNote"].forEach((id) => ($("#" + id).value = ""));
    toast("감정 신청 완료! 감정가는 '내 신청 조회'에서 확인할 수 있어요.");
  } catch (e) {
    toast(e.message, true);
  } finally {
    $("#sellSubmit").disabled = false;
  }
});

// ---- 구매신청: 입금내역 캡쳐 첨부
let buyImageData = "";

function setBuyImage(dataUrl) {
  buyImageData = dataUrl;
  $("#previewImg").src = dataUrl;
  $("#imagePreview").hidden = false;
  $("#dropzone").hidden = true;
}
function clearBuyImage() {
  buyImageData = "";
  $("#previewImg").src = "";
  $("#imagePreview").hidden = true;
  $("#dropzone").hidden = false;
  $("#buyImageFile").value = "";
}

async function compressImage(file) {
  const bitmap = await createImageBitmap(file);
  const maxW = 1280;
  const scale = Math.min(1, maxW / bitmap.width);
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.85);
}

async function handleImageFile(file) {
  if (!file || !file.type.startsWith("image/")) {
    return toast("이미지 파일만 첨부할 수 있어요.", true);
  }
  try {
    setBuyImage(await compressImage(file));
  } catch (e) {
    toast("이미지를 읽을 수 없어요. 다른 파일로 시도해주세요.", true);
  }
}

$("#dropzone").addEventListener("click", () => $("#buyImageFile").click());
$("#buyImageFile").addEventListener("change", (e) => handleImageFile(e.target.files[0]));
$("#removeImage").addEventListener("click", clearBuyImage);
["dragover", "dragleave", "drop"].forEach((evt) =>
  $("#dropzone").addEventListener(evt, (e) => {
    e.preventDefault();
    $("#dropzone").classList.toggle("dragover", evt === "dragover");
    if (evt === "drop") handleImageFile(e.dataTransfer.files[0]);
  }));

// 물품명을 직접 바꾸면 재고 연동(정가) 해제
$("#buyItem").addEventListener("input", () => {
  $("#buyStockId").value = "";
  $("#buyPriceBox").hidden = true;
  $("#buyImageRequired").hidden = true;
});

// ---- 구매신청
$("#buySubmit").addEventListener("click", async () => {
  const nickname = $("#buyNick").value.trim();
  const stockIdRaw = $("#buyStockId").value;
  const body = {
    nickname,
    item: $("#buyItem").value.trim(),
    qty: $("#buyQty").value.trim(),
    note: $("#buyNote").value.trim(),
    stock_id: stockIdRaw ? parseInt(stockIdRaw, 10) : null,
    image: buyImageData || null,
  };
  if (!body.nickname || !body.item || !body.qty) {
    return toast("닉네임/물품/수량을 모두 입력하세요.", true);
  }
  if (body.stock_id && !buyImageData) {
    return toast("먼저 입금하고 입금내역 캡쳐를 첨부해주세요.", true);
  }
  try {
    $("#buySubmit").disabled = true;
    await api("/api/buy", body);
    rememberNick(nickname);
    ["buyItem", "buyQty", "buyNote", "buyStockId"].forEach((id) => ($("#" + id).value = ""));
    $("#buyPriceBox").hidden = true;
    $("#buyImageRequired").hidden = true;
    clearBuyImage();
    toast("구매신청 완료! 입금 확인 후 우편으로 보내드립니다.");
  } catch (e) {
    toast(e.message, true);
  } finally {
    $("#buySubmit").disabled = false;
  }
});

// ---- 내 신청 조회
$("#myLookup").addEventListener("click", lookupMy);
$("#myNick").addEventListener("keydown", (e) => { if (e.key === "Enter") lookupMy(); });

async function lookupMy() {
  const nickname = $("#myNick").value.trim();
  if (!nickname) return toast("닉네임을 입력하세요.", true);
  rememberNick(nickname);
  const box = $("#myResult");
  box.innerHTML = '<div class="empty">조회 중...</div>';
  try {
    const data = await api("/api/my?nickname=" + encodeURIComponent(nickname));
    const renderRow = (r, kindLabel, isSell) => `
      <div class="item-row">
        <div>
          <div class="name">${kindLabel} ${esc(r.item)} × ${esc(r.qty)}</div>
          <div class="sub">${r.price ? (isSell ? "감정가: " : "") + esc(r.price) + " · " : (isSell ? "감정 대기 · " : "")}${fmtDate(r.created_at)}${r.delivery ? " · " + (r.delivery === "직접" ? "직접 전달" : "우편 발송") : ""}</div>
          ${r.admin_note ? `<div class="sub">사장님 답변: ${esc(r.admin_note)}</div>` : ""}
        </div>
        <span class="badge ${esc(r.status)}">${esc(r.status)}</span>
      </div>`;
    const rows = [
      ...data.sell.map((r) => ({ ...r, _html: renderRow(r, "[감정]", true) })),
      ...data.buy.map((r) => ({ ...r, _html: renderRow(r, "[구매]", false) })),
    ].sort((a, b) => b.created_at - a.created_at);
    box.innerHTML = rows.length
      ? rows.map((r) => r._html).join("")
      : '<div class="empty">이 닉네임으로 넣은 신청이 없어요.</div>';
  } catch (e) {
    box.innerHTML = "";
    toast(e.message, true);
  }
}
