const state = {
  dashboard: null,
  errors: null,
  review: null,
  reviewHistory: null,
  activeBook: "workbook_660",
  activeLevel: "all",
  errorFilters: { section: "all", questionType: "all", page: "all" }
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
  bindErrorFilters();
  bindReviewControls();
  bindGitCommit();
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
      $("#gitCommitButton").hidden = target !== "review";
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

function bindErrorFilters() {
  $("#errorFilters").addEventListener("change", (event) => {
    const select = event.target.closest("select[data-filter]");
    if (!select) return;
    state.errorFilters[select.dataset.filter] = select.value;
    renderErrors();
  });
}

async function loadDashboard() {
  setStatus("读取中");
  state.dashboard = await fetchJson("/api/dashboard");
  state.activeBook = state.dashboard.active_workbook || state.activeBook;
  renderBookSelect();
  renderOverview();
  setStatus(formatSyncStatus(state.dashboard.records_sync, state.dashboard.generated_at));
}

function formatSyncStatus(sync, generatedAt) {
  if (!sync) return `已同步 ${generatedAt}`;
  const labels = {
    pulled: sync.message,
    cloned: sync.message,
    up_to_date: "records 已是最新",
    dirty: `${sync.message} · ${sync.dirty_count || 0} 项`,
    diverged: sync.message,
    error: `records 同步失败：${sync.message}`,
    skipped: sync.message,
    missing: sync.message,
    disabled: sync.message
  };
  return labels[sync.status] || `已同步 ${generatedAt}`;
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
    state.activeLevel = "all";
    state.errorFilters = { section: "all", questionType: "all", page: "all" };
    $$("#levelTabs .tab").forEach((item) => item.classList.toggle("active", item.dataset.level === "all"));
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
  $("#abcSourceMeta").textContent = book.book_id === "workbook_880" ? "以 record 字段为准" : "以 MD 索引为准";

  renderAbcChart(counts);
  renderUnitAccuracy(book.summary.unit_accuracy || []);
  renderRankList("#errorTags", book.summary.error_tags || []);
  renderRankList("#weaknessFocus", tierRankItems(book.summary.target_tiers || {}, book.score_tiers || []));
  renderCoverage();
}

function tierRankItems(tiers, tierOptions) {
  return tierOptions.map((tier) => ({ name: formatTierLabel(tier), count: tiers[String(tier)] || 0 }));
}

function formatTierLabel(tier) {
  return typeof tier === "number" || /^\d+$/.test(String(tier)) ? `${tier} 分必做` : String(tier);
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

function renderUnitAccuracy(items) {
  if (!items.length) {
    $("#trendChart").innerHTML = '<div class="empty">暂无单元正确率数据</div>';
    return;
  }
  const width = 680;
  const height = 250;
  const pad = { top: 28, right: 34, bottom: 52, left: 64 };
  const plotWidth = width - pad.left - pad.right;
  const plotHeight = height - pad.top - pad.bottom;
  const step = items.length > 1 ? plotWidth / (items.length - 1) : 0;
  const points = items.map((item, index) => {
    const x = items.length > 1 ? pad.left + step * index : pad.left + plotWidth / 2;
    const y = pad.top + ((1 - Number(item.accuracy || 0)) * plotHeight);
    return { x, y, item };
  });
  const path = points.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" ");
  const circles = points.map((point) => `
    <g class="chart-point" tabindex="0"
      data-label="${escapeHtml(point.item.label)}"
      data-accuracy="${formatPercent(point.item.accuracy)}"
      data-ratio="${point.item.correct}/${point.item.total}"
      transform="translate(${point.x} ${point.y})">
      <circle r="6"></circle>
      <circle class="chart-hit" r="18"></circle>
    </g>
  `).join("");
  const labels = points.map((point) => `
    <text x="${point.x}" y="${height - 16}" text-anchor="middle">${escapeHtml(point.item.label)}</text>
  `).join("");
  $("#trendChart").innerHTML = `
    <div class="chart-tooltip" id="unitAccuracyTooltip" role="status"></div>
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="单元初始正确率">
      <line x1="${pad.left}" y1="${pad.top}" x2="${width - pad.right}" y2="${pad.top}" class="chart-grid" />
      <line x1="${pad.left}" y1="${pad.top + plotHeight / 2}" x2="${width - pad.right}" y2="${pad.top + plotHeight / 2}" class="chart-grid" />
      <line x1="${pad.left}" y1="${height - pad.bottom}" x2="${width - pad.right}" y2="${height - pad.bottom}" class="chart-axis" />
      <line x1="${pad.left}" y1="${pad.top}" x2="${pad.left}" y2="${height - pad.bottom}" class="chart-axis" />
      <text x="${pad.left - 14}" y="${pad.top + 5}" text-anchor="end">100%</text>
      <text x="${pad.left - 14}" y="${pad.top + plotHeight / 2 + 5}" text-anchor="end">50%</text>
      <text x="${pad.left - 14}" y="${height - pad.bottom + 5}" text-anchor="end">0%</text>
      <path d="${path}" fill="none" stroke="#1f7a6b" stroke-width="3" />
      <g>${circles}</g>
      <g class="chart-labels">${labels}</g>
    </svg>
  `;
  bindUnitAccuracyTooltip();
}

function bindUnitAccuracyTooltip() {
  const chart = $("#trendChart");
  const tooltip = $("#unitAccuracyTooltip");
  if (!chart || !tooltip) return;

  chart.querySelectorAll(".chart-point").forEach((point) => {
    const show = () => {
      const rect = point.getBoundingClientRect();
      const chartRect = chart.getBoundingClientRect();
      tooltip.innerHTML = `
        <strong>${escapeHtml(point.dataset.label)}</strong>
        <span>${escapeHtml(point.dataset.accuracy)} · ${escapeHtml(point.dataset.ratio)}</span>
      `;
      tooltip.style.left = `${rect.left - chartRect.left + rect.width / 2}px`;
      tooltip.style.top = `${rect.top - chartRect.top}px`;
      tooltip.classList.add("visible");
    };
    point.addEventListener("mouseenter", show);
    point.addEventListener("focus", show);
    point.addEventListener("mouseleave", () => tooltip.classList.remove("visible"));
    point.addEventListener("blur", () => tooltip.classList.remove("visible"));
  });
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
    renderErrorFilters();
    renderErrors();
  } catch (error) {
    $("#errorFilters").hidden = true;
    $("#errorList").innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
  }
}

function renderErrorFilters() {
  const payload = state.errors;
  const container = $("#errorFilters");
  const structured = Boolean(payload?.structured);
  container.hidden = !structured;
  $("#errorViewMeta").textContent = structured ? "按板块、题型、ABC 与页码查看" : "按单元与 ABC 分级查看";
  if (!structured) {
    container.innerHTML = "";
    return;
  }

  const filters = payload.filters || {};
  container.innerHTML = `
    ${renderErrorFilterSelect("section", "板块", filters.sections || [], state.errorFilters.section)}
    ${renderErrorFilterSelect("questionType", "题型", filters.question_types || [], state.errorFilters.questionType)}
    ${renderErrorFilterSelect("page", "页码", filters.pages || [], state.errorFilters.page, (value) => `P${value}`)}
  `;
}

function renderErrorFilterSelect(filter, label, options, selected, formatter = String) {
  return `
    <label>${label}
      <select data-filter="${filter}">
        <option value="all">全部</option>
        ${options.map((option) => `
          <option value="${escapeHtml(option)}" ${String(selected) === String(option) ? "selected" : ""}>${escapeHtml(formatter(option))}</option>
        `).join("")}
      </select>
    </label>
  `;
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
      (unit.levels[level] || []).forEach((item) => {
        if (!matchesErrorFilters(item)) return;
        cards.push(renderErrorCard(item));
      });
    });
    if (cards.length) {
      html += `<div class="unit-block"><h4 class="unit-title">${escapeHtml(unit.label)}</h4>${cards.join("")}</div>`;
    }
  });
  container.innerHTML = html || '<div class="empty">当前筛选没有错题</div>';
}

function matchesErrorFilters(item) {
  if (!state.errors?.structured) return true;
  const { section, questionType, page } = state.errorFilters;
  return (section === "all" || item.section === section)
    && (questionType === "all" || item.question_type === questionType)
    && (page === "all" || String(item.page) === String(page));
}

function renderErrorCard(item) {
  if (item.book_id === "workbook_880") return renderStructuredErrorCard(item);

  const tags = [item.target_score_tier ? formatTierLabel(item.target_score_tier) : "", ...(item.required_for_scores || []).map((score) => `${score}`)]
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

function renderStructuredErrorCard(item) {
  const context = [item.section, item.question_type, item.display_id].filter(Boolean);
  return `
    <article class="error-card error-card-structured" data-question-id="${escapeHtml(item.question_id)}">
      <div>
        <div class="question-id">${escapeHtml(item.display_id)}</div>
        <span class="level-badge level-${item.level}">${item.level} 级</span>
      </div>
      <div>
        <div class="question-context">${context.map((value) => `<span>${escapeHtml(value)}</span>`).join('<i aria-hidden="true">/</i>')}</div>
        <strong>${escapeHtml(item.performance_level || "未记录")} · ${formatPercent(item.mastery)}</strong>
        <p>${escapeHtml(item.summary || "暂无错因摘要")}</p>
      </div>
      <div class="structured-card-tags">
        <span class="tag">${escapeHtml(formatTierLabel(item.target_score_tier))}</span>
        <span class="tag">P${escapeHtml(item.page)}</span>
      </div>
    </article>
  `;
}

function bindReviewControls() {
  $("#refreshReview").addEventListener("click", saveReviewSettingsAndLoad);
  $("#dailyLimit").addEventListener("change", saveReviewSettingsAndLoad);
  $("#reviewTierFilters").addEventListener("change", (event) => {
    if (event.target.matches("input[name='tier']")) saveReviewSettingsAndLoad();
  });
}

function bindGitCommit() {
  $("#gitCommitButton").addEventListener("click", runGitCommit);
}

async function runGitCommit() {
  const button = $("#gitCommitButton");
  const label = $("#gitCommitButtonLabel");
  const notice = $("#gitCommitNotice");
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  label.textContent = "提交中";
  notice.hidden = false;
  notice.classList.remove("is-error");
  notice.innerHTML = "<strong>正在提交 records</strong><span>完成前请不要关闭本地服务。</span>";
  setStatus("records 提交中");

  try {
    const result = await fetchJson("/api/git/commit", { method: "POST" });
    renderGitCommitResult(result);
    setStatus(result.ok ? "records 提交完成" : "records push 未完成");
  } catch (error) {
    notice.classList.add("is-error");
    notice.innerHTML = `
      <strong>Git 操作未完成</strong>
      <span>${escapeHtml(error.message)}</span>
      <span>请打开终端检查 records 仓库；如果已经产生本地 commit，请手动执行：</span>
      <code class="git-retry-command">git -C "/Users/y-mac/Documents/math-test_2/records" push</code>
    `;
    setStatus("Git 操作失败");
  } finally {
    button.disabled = false;
    button.removeAttribute("aria-busy");
    label.textContent = "提交 records";
  }
}

function renderGitCommitResult(result) {
  const notice = $("#gitCommitNotice");
  const repoLabels = { app: "app", records: "records" };
  const repoResults = Object.entries(result.results || {});
  const retryCommands = repoResults
    .map(([, item]) => item.retry_command)
    .filter(Boolean);

  notice.classList.toggle("is-error", !result.ok);
  notice.innerHTML = `
    <strong>${escapeHtml(result.message)}</strong>
    <div class="git-result-list">
      ${repoResults.map(([repo, item]) => `
        <span>${escapeHtml(repoLabels[repo] || repo)}：${escapeHtml(item.message)}</span>
      `).join("")}
    </div>
    ${retryCommands.length ? `
      <span>网络恢复后，请在终端执行：</span>
      ${retryCommands.map((command) => `<code class="git-retry-command">${escapeHtml(command)}</code>`).join("")}
    ` : ""}
  `;
}

function selectedTiers() {
  return $$("input[name='tier']:checked").map((input) => input.dataset.type === "number" ? Number(input.value) : input.value);
}

async function loadReview() {
  const limit = Number($("#dailyLimit").value || 10);
  const query = new URLSearchParams({ limit: String(limit) });
  if (state.review) query.set("tiers", selectedTiers().join(","));
  const [review, reviewHistory] = await Promise.all([
    fetchJson(`/api/review/today?${query.toString()}`),
    fetchJson("/api/review/history")
  ]);
  state.review = review;
  state.reviewHistory = reviewHistory;
  renderReview();
  renderReviewHistory();
}

async function saveReviewSettingsAndLoad() {
  await fetchJson("/api/review/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      daily_limit: Number($("#dailyLimit").value || 10),
      selected_tiers: selectedTiers()
    })
  });
  await loadReview();
}

function renderReview() {
  const review = state.review;
  if (!review) return;
  $("#dailyLimit").value = review.settings.daily_limit;
  renderReviewTierFilters(review.settings.tier_groups || [], review.settings.selected_tiers || []);
  $("#reviewDue").textContent = review.summary.due_total;
  $("#reviewSelected").textContent = review.summary.pending_total ?? review.summary.selected_total;
  $("#reviewOverflow").textContent = review.summary.overflow_total;
  $("#reviewTodayMeta").textContent = `${review.today} · ${review.label}`;
  renderReviewTierCounts(review.summary.book_counts || {}, review.settings.tier_groups || []);
  renderActivity(review.activity || []);
  $("#reviewQueue").innerHTML = review.queue.length
    ? review.queue.map((item) => renderReviewCard(item, true)).join("")
    : '<div class="empty">今日没有到期回滚题。</div>';
  $("#reviewDeferred").innerHTML = review.deferred.length
    ? review.deferred.map((item) => renderReviewCard(item, false)).join("")
    : '<div class="empty">没有顺延题。</div>';
  bindFeedbackButtons();
}

function renderReviewTierFilters(groups, selectedTiers) {
  $("#reviewTierFilters").innerHTML = groups.map((group) => `
    <fieldset class="tier-fieldset">
      <legend>${escapeHtml(group.label)}</legend>
      ${group.tiers.map((tier) => `
        <label>
          <input type="checkbox" name="tier" value="${escapeHtml(tier)}"
            data-type="${typeof tier === "number" ? "number" : "string"}"
            ${selectedTiers.includes(tier) ? "checked" : ""}>
          ${escapeHtml(formatTierLabel(tier))}
        </label>
      `).join("")}
    </fieldset>
  `).join("");
}

function renderReviewTierCounts(bookCounts, groups) {
  $("#reviewTierCounts").innerHTML = groups.map((group) => {
    const counts = bookCounts[group.book_id]?.tier_counts || {};
    return `
      <section class="tier-ledger-book">
        <div class="tier-ledger-label">
          <strong>${escapeHtml(group.label)}</strong>
          <span>应复盘 ${bookCounts[group.book_id]?.due_total || 0}</span>
        </div>
        <div class="tier-ledger-cells">
          ${group.tiers.map((tier) => `
            <div class="tier-cell">
              <span>${escapeHtml(formatTierLabel(tier))}</span>
              <strong>${counts[String(tier)] || 0}</strong>
            </div>
          `).join("")}
        </div>
      </section>
    `;
  }).join("");
}

function renderReviewCard(item, withActions) {
  const summary = item.summary || "暂无摘要";
  const visibleId = item.book_id === "workbook_880" ? item.display_id : item.question_id;
  const context = item.book_id === "workbook_880"
    ? `<div class="question-context review-question-context">${[item.section, item.question_type, item.display_id].filter(Boolean).map((value) => `<span>${escapeHtml(value)}</span>`).join('<i aria-hidden="true">/</i>')}</div>`
    : "";
  return `
    <article class="review-card review-level-${item.level}">
      <div class="review-stamp">
        <strong>${escapeHtml(visibleId)}</strong>
        <span class="level-badge level-${item.level}">${item.level}</span>
      </div>
      <div class="review-body">
        ${context}
        <div class="review-line">
          <span class="book-source-tag">${escapeHtml(item.book_label)}</span>
          <span>${escapeHtml(formatTierLabel(item.target_score_tier))}</span>
          <span>${item.is_new ? "新错题" : `复习 ${item.review_count} 次`}</span>
          <span>${item.overdue_days ? `逾期 ${item.overdue_days} 天` : "今日到期"}</span>
          <span>失败 ${item.fail_count} 次</span>
        </div>
        <p>${escapeHtml(summary)}</p>
        ${withActions ? `
          <div class="feedback-row" data-book-id="${escapeHtml(item.book_id)}" data-qid="${escapeHtml(item.question_id)}">
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

function renderReviewHistory() {
  const container = $("#reviewHistory");
  const history = state.reviewHistory?.history || [];
  const totalReviews = state.reviewHistory?.total_reviews || 0;
  $("#reviewHistoryTotal").textContent = `累计复盘 ${totalReviews} 题`;
  if (!history.length) {
    container.innerHTML = '<div class="empty">今天暂无复盘记录。完成一次回滚后会出现在这里。</div>';
    return;
  }
  container.innerHTML = groupHistoryByDate(history).map((group) => `
    <section class="history-day">
      <div class="history-day-label">
        <span>${escapeHtml(group.label)} · ${group.items.length} 题</span>
      </div>
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
  const tierTag = event.target_score_tier ? `<span class="history-tier">${escapeHtml(formatTierLabel(event.target_score_tier))}</span>` : "";
  const reviewTag = Number.isFinite(event.review_count) ? `<span>复习 ${event.review_count} 次</span>` : "";
  const failTag = Number.isFinite(event.fail_count) ? `<span>失败 ${event.fail_count} 次</span>` : "";
  const visibleId = event.book_id === "workbook_880" ? event.display_id : event.question_id;
  const context = event.book_id === "workbook_880"
    ? `<div class="question-context history-question-context">${[event.section, event.question_type, event.display_id].filter(Boolean).map((value) => `<span>${escapeHtml(value)}</span>`).join('<i aria-hidden="true">/</i>')}</div>`
    : "";
  return `
    <article class="history-card ${levelClass}" data-book-id="${escapeHtml(event.book_id)}" data-qid="${escapeHtml(event.question_id)}" data-index="${event.event_index}">
      <div class="history-main">
        <strong>${escapeHtml(visibleId)}</strong>
        <span class="book-source-tag">${escapeHtml(event.book_label)}</span>
        <span>${event.outcome === "pass" ? "对了" : `仍错 ${escapeHtml(event.error_level || "B")}`}</span>
        <span>下次 ${escapeHtml(event.next_due_at || "-")}</span>
        ${tierTag}
        ${reviewTag}
        ${failTag}
        ${context}
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
      if (row.dataset.submitting === "true") return;
      const payload = {
        book_id: row.dataset.bookId,
        question_id: row.dataset.qid,
        outcome: button.dataset.outcome,
        error_level: button.dataset.level || null,
        note: row.querySelector(".review-note-input")?.value.trim() || ""
      };
      const card = row.closest(".review-card");
      const originalText = button.textContent;
      row.dataset.submitting = "true";
      row.setAttribute("aria-busy", "true");
      card?.classList.add("is-submitting");
      button.classList.add("is-selected");
      button.textContent = "记录中";
      row.querySelectorAll("button").forEach((item) => { item.disabled = true; });
      setStatus(`正在记录 ${payload.question_id}`);

      try {
        await fetchJson("/api/review/feedback", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        await loadReview();
        setStatus(`已记录 ${payload.question_id}`);
      } catch (error) {
        row.dataset.submitting = "false";
        row.removeAttribute("aria-busy");
        card?.classList.remove("is-submitting");
        button.classList.remove("is-selected");
        button.textContent = originalText;
        row.querySelectorAll("button").forEach((item) => { item.disabled = false; });
        setStatus(`记录失败：${error.message}`);
      }
    });
  });
}

function bindHistorySaves() {
  $$(".history-card").forEach((card) => {
    const outcomeSelect = card.querySelector(".history-outcome");
    const levelSelect = card.querySelector(".history-level");
    levelSelect.addEventListener("change", () => {
      if (levelSelect.value) outcomeSelect.value = "wrong";
    });
    outcomeSelect.addEventListener("change", () => {
      if (outcomeSelect.value === "pass") {
        levelSelect.value = "";
      } else if (!levelSelect.value) {
        levelSelect.value = "B";
      }
    });
  });

  $$(".history-save").forEach((button) => {
    button.addEventListener("click", async () => {
      const card = button.closest(".history-card");
      let outcome = card.querySelector(".history-outcome").value;
      let level = card.querySelector(".history-level").value;
      if (level && outcome === "pass") outcome = "wrong";
      if (outcome === "wrong" && !level) level = "B";
      const payload = {
        book_id: card.dataset.bookId,
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
