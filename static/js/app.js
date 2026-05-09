const state = {
  dashboard: null,
  errors: null,
  review: null,
  reviewHistory: null,
  activeBook: "workbook_660",
  activeLevel: "all",
  images: []
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function formatPercent(value) {
  if (!Number.isFinite(value)) return "-";
  return `${Math.round(value * 100)}%`;
}

function setStatus(text) {
  $("#dataStatus").textContent = text;
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "请求失败");
  }
  return data;
}

async function init() {
  bindNavigation();
  bindLevelTabs();
  bindOcr();
  bindReviewControls();
  await loadDashboard();
  await loadBookErrors(state.activeBook);
  await loadReview();
}

function bindNavigation() {
  $$(".nav-item").forEach((button) => {
    button.addEventListener("click", async () => {
      $$(".nav-item").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      const target = button.dataset.target;
      $$(".view").forEach((view) => view.classList.remove("active"));
      $(`#${target}View`).classList.add("active");
      $("#pageTitle").textContent = button.textContent;
      if (target === "review") await loadReview();
    });
  });
}

function bindLevelTabs() {
  $("#levelTabs").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-level]");
    if (!button) return;
    state.activeLevel = button.dataset.level;
    $$("#levelTabs .tab").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    renderErrors();
  });
}

async function loadDashboard() {
  setStatus("读取中");
  state.dashboard = await fetchJson("/api/dashboard");
  state.activeBook = state.dashboard.active_workbook || state.activeBook;
  renderBookSelect();
  renderOverview();
  setStatus(`已同步 ${state.dashboard.generated_at}`);
}

function renderBookSelect() {
  const select = $("#bookSelect");
  select.innerHTML = "";
  state.dashboard.books.forEach((book) => {
    const option = document.createElement("option");
    option.value = book.book_id;
    option.textContent = `${book.label}${book.status === "active" ? " · active" : ""}`;
    select.appendChild(option);
  });
  select.value = state.activeBook;
  select.addEventListener("change", async () => {
    state.activeBook = select.value;
    renderOverview();
    await loadBookErrors(state.activeBook);
  });
}

function getActiveBook() {
  return state.dashboard.books.find((book) => book.book_id === state.activeBook) || state.dashboard.books[0];
}

function renderOverview() {
  const book = getActiveBook();
  if (!book) return;
  const counts = book.abc_counts || book.summary.error_levels || { A: 0, B: 0, C: 0 };
  const errorTotal = (counts.A || 0) + (counts.B || 0) + (counts.C || 0);

  $("#totalRecords").textContent = state.dashboard.totals.records;
  $("#bookRecords").textContent = book.total;
  $("#errorTotal").textContent = errorTotal;
  $("#avgMastery").textContent = formatPercent(book.summary.average_mastery);
  $("#bookMeta").textContent = `${book.total} 条 · ${book.status || "unknown"} · ${book.recorded_range || ""}`;

  renderAbcChart(counts);
  renderTrend(book.summary.recent || []);
  renderRankList("#errorTags", book.summary.error_tags || []);
  renderRankList("#weaknessFocus", tierRankItems(book.summary.target_tiers || {}));
  renderCoverage();
}

function tierRankItems(tiers) {
  return ["90", "110", "135"].map((tier) => ({ name: `${tier} 分必做`, count: tiers[tier] || 0 }));
}

function renderAbcChart(counts) {
  const total = Math.max(1, (counts.A || 0) + (counts.B || 0) + (counts.C || 0));
  const labels = [
    ["A", "计算错误", "fill-a"],
    ["B", "思路卡住", "fill-b"],
    ["C", "无从下手", "fill-c"]
  ];
  $("#abcChart").innerHTML = labels.map(([level, label, fill]) => {
    const count = counts[level] || 0;
    const width = Math.round((count / total) * 100);
    return `
      <div class="abc-row">
        <span class="level-badge level-${level}">${level} · ${label}</span>
        <div class="bar"><div class="bar-fill ${fill}" style="width:${width}%"></div></div>
        <strong>${count}</strong>
      </div>
    `;
  }).join("");
}

function renderTrend(items) {
  if (!items.length) {
    $("#trendChart").innerHTML = '<div class="empty">暂无趋势数据</div>';
    return;
  }
  const width = 640;
  const height = 210;
  const pad = 28;
  const step = items.length > 1 ? (width - pad * 2) / (items.length - 1) : 0;
  const points = items.map((item, index) => {
    const x = pad + step * index;
    const y = height - pad - (Number(item.mastery || 0) * (height - pad * 2));
    return { x, y, item };
  });
  const path = points.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" ");
  const circles = points.map((point) => `
    <circle cx="${point.x}" cy="${point.y}" r="4">
      <title>${point.item.question_id}: ${formatPercent(point.item.mastery)}</title>
    </circle>
  `).join("");
  $("#trendChart").innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="最近掌握度趋势">
      <line x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}" stroke="#d9dfdc" />
      <line x1="${pad}" y1="${pad}" x2="${pad}" y2="${height - pad}" stroke="#d9dfdc" />
      <path d="${path}" fill="none" stroke="#1f7a6b" stroke-width="3" />
      <g fill="#183a36">${circles}</g>
    </svg>
  `;
}

function renderRankList(selector, items) {
  const container = $(selector);
  if (!items.length) {
    container.innerHTML = '<div class="empty">暂无记录</div>';
    return;
  }
  const max = Math.max(...items.map((item) => item.count), 1);
  container.innerHTML = items.map((item) => `
    <div class="rank-row">
      <span>${escapeHtml(item.name)}</span>
      <div class="bar"><div class="bar-fill fill-a" style="width:${Math.round((item.count / max) * 100)}%"></div></div>
      <strong>${item.count}</strong>
    </div>
  `).join("");
}

function renderCoverage() {
  const items = state.dashboard.coverage || [];
  $("#coverageList").innerHTML = items.length ? items.map((item) => `
    <div class="coverage-item">
      <strong>${escapeHtml(item.title)}</strong>
      <p>${escapeHtml(item.conclusion || "暂无摘要")}</p>
    </div>
  `).join("") : '<div class="empty">暂无覆盖文档</div>';
}

async function loadBookErrors(bookId) {
  try {
    state.errors = await fetchJson(`/api/books/${encodeURIComponent(bookId)}/errors`);
    renderErrors();
  } catch (error) {
    $("#errorList").innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
  }
}

function renderErrors() {
  const container = $("#errorList");
  const payload = state.errors;
  if (!payload || !payload.units?.length) {
    container.innerHTML = '<div class="empty">暂无 ABC 错题索引</div>';
    return;
  }
  let html = "";
  payload.units.forEach((unit) => {
    const cards = [];
    ["A", "B", "C"].forEach((level) => {
      if (state.activeLevel !== "all" && state.activeLevel !== level) return;
      (unit.levels[level] || []).forEach((item) => cards.push(renderErrorCard(item)));
    });
    if (cards.length) {
      html += `<div class="unit-block"><h4 class="unit-title">${escapeHtml(unit.label)}</h4>${cards.join("")}</div>`;
    }
  });
  container.innerHTML = html || '<div class="empty">当前筛选没有错题</div>';
}

function renderErrorCard(item) {
  const tags = [item.target_score_tier ? `${item.target_score_tier}分必做` : "", ...(item.required_for_scores || []).map((score) => `${score}`)]
    .filter(Boolean)
    .slice(0, 5);
  return `
    <article class="error-card">
      <div>
        <div class="question-id">${escapeHtml(item.question_id)}</div>
        <span class="level-badge level-${item.level}">${item.level} 级</span>
      </div>
      <div>
        <strong>${escapeHtml(item.performance_level || "未记录")} · ${formatPercent(item.mastery)}</strong>
        <p>${escapeHtml(item.summary || "暂无错因摘要")}</p>
        <div class="tag-list">${tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div>
      </div>
      <span class="tag">${escapeHtml(item.target_score_tier ? `${item.target_score_tier}` : "-")}</span>
    </article>
  `;
}

function bindReviewControls() {
  $("#refreshReview").addEventListener("click", saveReviewSettingsAndLoad);
  $("#dailyLimit").addEventListener("change", saveReviewSettingsAndLoad);
  $$("input[name='tier']").forEach((input) => input.addEventListener("change", saveReviewSettingsAndLoad));
}

function selectedTiers() {
  return $$("input[name='tier']:checked").map((input) => input.value);
}

async function loadReview() {
  const tiers = selectedTiers();
  const limit = Number($("#dailyLimit").value || 10);
  const query = new URLSearchParams({ tiers: tiers.join(","), limit: String(limit) });
  state.review = await fetchJson(`/api/review/today?${query.toString()}`);
  renderReview();
  await loadReviewHistory();
}

async function saveReviewSettingsAndLoad() {
  await fetchJson("/api/review/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      daily_limit: Number($("#dailyLimit").value || 10),
      selected_tiers: selectedTiers().map(Number)
    })
  });
  await loadReview();
}

function renderReview() {
  const review = state.review;
  if (!review) return;
  $("#dailyLimit").value = review.settings.daily_limit;
  $$("input[name='tier']").forEach((input) => {
    input.checked = review.settings.selected_tiers.includes(Number(input.value));
  });
  $("#reviewDue").textContent = review.summary.due_total;
  $("#reviewSelected").textContent = review.summary.pending_total ?? review.summary.selected_total;
  $("#reviewOverflow").textContent = review.summary.overflow_total;
  $("#reviewTodayMeta").textContent = `${review.today} · ${review.label}`;
  $("#reviewTierCounts").innerHTML = ["90", "110", "135"].map((tier) => `
    <div class="tier-cell">
      <span>${tier} 分</span>
      <strong>${review.summary.tier_counts[tier] || 0}</strong>
    </div>
  `).join("");
  renderActivity(review.activity || []);
  $("#reviewQueue").innerHTML = review.queue.length
    ? review.queue.map((item) => renderReviewCard(item, true)).join("")
    : '<div class="empty">今日没有到期回滚题。</div>';
  $("#reviewDeferred").innerHTML = review.deferred.length
    ? review.deferred.map((item) => renderReviewCard(item, false)).join("")
    : '<div class="empty">没有顺延题。</div>';
  bindFeedbackButtons();
}

function renderReviewCard(item, withActions) {
  const summary = item.summary || "暂无摘要";
  return `
    <article class="review-card review-level-${item.level}">
      <div class="review-stamp">
        <strong>${escapeHtml(item.question_id)}</strong>
        <span class="level-badge level-${item.level}">${item.level}</span>
      </div>
      <div class="review-body">
        <div class="review-line">
          <span>${item.target_score_tier} 分必做</span>
          <span>${item.is_new ? "新错题" : `复习 ${item.review_count} 次`}</span>
          <span>${item.overdue_days ? `逾期 ${item.overdue_days} 天` : "今日到期"}</span>
          <span>失败 ${item.recent_fail_count}/${item.fail_count}</span>
        </div>
        <p>${escapeHtml(summary)}</p>
        ${withActions ? `
          <div class="feedback-row" data-qid="${escapeHtml(item.question_id)}">
            <input class="review-note-input" type="text" placeholder="做题 comment，可留空">
            <button class="feedback-pass" data-outcome="pass">对了</button>
            <button class="feedback-a" data-outcome="wrong" data-level="A">仍错 A</button>
            <button class="feedback-b" data-outcome="wrong" data-level="B">仍错 B</button>
            <button class="feedback-c" data-outcome="wrong" data-level="C">仍错 C</button>
          </div>
        ` : ""}
      </div>
    </article>
  `;
}

function renderActivity(days) {
  const container = $("#reviewActivity");
  if (!days.length) {
    container.innerHTML = '<div class="empty compact-empty">暂无复盘活跃记录</div>';
    return;
  }
  const dailyTarget = Math.max(1, Number(state.review?.settings?.daily_limit || 10));
  const cells = days.map((day) => {
    const ratio = Math.min(day.count / dailyTarget, 1);
    const level = activityHeatLevel(ratio, day.count);
    const percent = Math.round(ratio * 100);
    return `<span class="heat-cell heat-${level}" title="${day.date} · ${day.count}/${dailyTarget} 题 · ${percent}%"></span>`;
  }).join("");
  const total = days.reduce((sum, day) => sum + day.count, 0);
  $("#activityMeta").textContent = `近 ${days.length} 天 · ${total} 次 · 目标 ${dailyTarget} 题/天`;
  container.innerHTML = cells;
}

function activityHeatLevel(ratio, count) {
  if (count <= 0) return 0;
  if (ratio < 0.25) return 1;
  if (ratio < 0.5) return 2;
  if (ratio < 0.8) return 3;
  return 4;
}

async function loadReviewHistory() {
  state.reviewHistory = await fetchJson("/api/review/history?limit=30");
  renderReviewHistory();
}

function renderReviewHistory() {
  const container = $("#reviewHistory");
  const history = state.reviewHistory?.history || [];
  if (!history.length) {
    container.innerHTML = '<div class="empty">暂无复盘记录。完成一次回滚后会出现在这里。</div>';
    return;
  }
  container.innerHTML = groupHistoryByDate(history).map((group) => `
    <section class="history-day">
      <div class="history-day-label"><span>${escapeHtml(group.label)}</span></div>
      <div class="history-day-items">
        ${group.items.map(renderHistoryCard).join("")}
      </div>
    </section>
  `).join("");
  bindHistorySaves();
}

function groupHistoryByDate(history) {
  const groups = [];
  history.forEach((event) => {
    const date = formatDateOnly(event.reviewed_at);
    const last = groups[groups.length - 1];
    if (!last || last.label !== date) {
      groups.push({ label: date, items: [event] });
    } else {
      last.items.push(event);
    }
  });
  return groups;
}

function renderHistoryCard(event) {
  const levelClass = event.error_level ? `history-level-${event.error_level}` : "history-level-pass";
  const tierTag = event.target_score_tier ? `<span class="history-tier">${event.target_score_tier} 分必做</span>` : "";
  return `
    <article class="history-card ${levelClass}" data-qid="${escapeHtml(event.question_id)}" data-index="${event.event_index}">
      <div class="history-main">
        <strong>${escapeHtml(event.question_id)}</strong>
        <span>${event.outcome === "pass" ? "对了" : `仍错 ${escapeHtml(event.error_level || "B")}`}</span>
        <span>下次 ${escapeHtml(event.next_due_at || "-")}</span>
        ${tierTag}
      </div>
      <div class="history-edit">
        <select class="history-outcome">
          <option value="pass" ${event.outcome === "pass" ? "selected" : ""}>对了</option>
          <option value="wrong" ${event.outcome === "wrong" ? "selected" : ""}>仍错</option>
        </select>
        <select class="history-level">
          <option value="" ${!event.error_level ? "selected" : ""}>无等级</option>
          <option value="A" ${event.error_level === "A" ? "selected" : ""}>A</option>
          <option value="B" ${event.error_level === "B" ? "selected" : ""}>B</option>
          <option value="C" ${event.error_level === "C" ? "selected" : ""}>C</option>
        </select>
        <input class="history-note" type="text" value="${escapeHtml(event.note || "")}" placeholder="复盘 comment">
        <button class="history-save" type="button">保存</button>
      </div>
    </article>
  `;
}

function bindFeedbackButtons() {
  $$(".feedback-row button").forEach((button) => {
    button.addEventListener("click", async () => {
      const row = button.closest(".feedback-row");
      const payload = {
        question_id: row.dataset.qid,
        outcome: button.dataset.outcome,
        error_level: button.dataset.level || null,
        note: row.querySelector(".review-note-input")?.value.trim() || ""
      };
      await fetchJson("/api/review/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      await loadReview();
      setStatus(`已记录 ${payload.question_id}`);
    });
  });
}

function bindHistorySaves() {
  $$(".history-save").forEach((button) => {
    button.addEventListener("click", async () => {
      const card = button.closest(".history-card");
      const outcome = card.querySelector(".history-outcome").value;
      const level = card.querySelector(".history-level").value;
      const payload = {
        outcome,
        error_level: outcome === "wrong" ? (level || "B") : null,
        note: card.querySelector(".history-note").value.trim()
      };
      await fetchJson(`/api/review/history/${encodeURIComponent(card.dataset.qid)}/${card.dataset.index}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      await loadReview();
      setStatus(`已修改 ${card.dataset.qid}`);
    });
  });
}

function formatDateTime(value) {
  if (!value) return "-";
  return value.replace("T", " ").slice(0, 16);
}

function formatDateOnly(value) {
  if (!value) return "未记录日期";
  return value.slice(0, 10);
}

function bindOcr() {
  const input = $("#imageInput");
  $("#uploadBox").addEventListener("click", (event) => {
    if (event.target !== input) input.click();
  });
  input.addEventListener("change", () => addFiles([...input.files]));
  document.addEventListener("paste", (event) => {
    const files = [...event.clipboardData.items]
      .filter((item) => item.type.startsWith("image/"))
      .map((item) => item.getAsFile())
      .filter(Boolean);
    if (files.length) {
      event.preventDefault();
      addFiles(files);
    }
  });
  $("#ocrForm").addEventListener("submit", submitOcr);
}

function addFiles(files) {
  files.filter((file) => file.type.startsWith("image/")).forEach((file) => {
    const reader = new FileReader();
    reader.onload = () => {
      state.images.push({ name: file.name, data_url: reader.result });
      renderPreviews();
    };
    reader.readAsDataURL(file);
  });
}

function renderPreviews() {
  $("#previewGrid").innerHTML = state.images.map((image, index) => `
    <div class="preview-item">
      <img src="${image.data_url}" alt="${escapeHtml(image.name || `image-${index + 1}`)}">
      <button type="button" aria-label="移除图片" data-remove="${index}">×</button>
    </div>
  `).join("");
  $$("#previewGrid button[data-remove]").forEach((button) => {
    button.addEventListener("click", () => {
      state.images.splice(Number(button.dataset.remove), 1);
      renderPreviews();
    });
  });
}

async function submitOcr(event) {
  event.preventDefault();
  if (!state.images.length) {
    $("#ocrState").textContent = "请先添加图片";
    return;
  }
  const button = $("#ocrSubmit");
  button.disabled = true;
  $("#ocrState").textContent = "识别中";
  $("#ocrOutput").textContent = "正在调用多模态模型，请稍等。";
  $("#ocrFile").textContent = "";
  try {
    const result = await fetchJson("/api/ocr", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        book_id: state.activeBook,
        question_range: $("#questionRange").value.trim(),
        note: $("#batchNote").value.trim(),
        images: state.images
      })
    });
    $("#ocrState").textContent = `完成 · 估计 ${result.question_count} 题`;
    $("#ocrOutput").textContent = result.text || "模型未返回文本。";
    $("#ocrFile").textContent = `已生成：${result.file_path}`;
    state.images = [];
    renderPreviews();
    $("#ocrForm").reset();
  } catch (error) {
    $("#ocrState").textContent = "失败";
    $("#ocrOutput").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

init().catch((error) => {
  setStatus("加载失败");
  console.error(error);
});
