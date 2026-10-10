const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
const levelTag = (level) => ["A", "B", "C"].includes(level) ? `<span class="level level-${level}">${level}</span>` : "";
function context(item) {
  return item.book_id === "workbook_880" ? `<p class="context">${[item.section, item.question_type].filter(Boolean).map(esc).join(" / ")}</p>` : "";
}
function card(item, backlog) {
  const tags = [item.target_score_tier == null ? "" : (typeof item.target_score_tier === "number" ? `${item.target_score_tier} 分必做` : item.target_score_tier),
    item.is_new ? "新错题" : `复习 ${item.review_count} 次`, backlog ? "遗留中" : "今日到期", `失败 ${item.fail_count} 次`];
  const special = [item.is_starved ? "饿死" : "", item.is_final_review ? "最后一次复习" : "", item.is_maintenance ? "毕业维护" : ""];
  return `<article class="card"><div class="card-heading"><h3>${esc(item.display_id)}</h3><span class="book-tag">${esc(item.book_label)}</span>${levelTag(item.level)}</div>${context(item)}<div class="tags">${tags.filter(Boolean).map(tag => `<span>${esc(tag)}</span>`).join("")}${special.filter(Boolean).map(tag => `<span class="special">${esc(tag)}</span>`).join("")}</div>${item.summary ? `<p class="summary">${esc(item.summary)}</p>` : ""}${item.note ? `<p class="note">${esc(item.note)}</p>` : ""}</article>`;
}
function heatLevel(day) {
  if (day.ratio == null) return day.count > 0 ? "unknown" : 0;
  return day.completed <= 0 ? 0 : day.ratio < .25 ? 1 : day.ratio < .5 ? 2 : day.ratio < 1 ? 3 : 4;
}
function render(data) {
  $("date").textContent = data.date;
  const timestamp = new Date(data.updated_at);
  const stale = Date.now() - timestamp.getTime() > 2 * 3600000;
  $("updated").textContent = `上次更新：${timestamp.toLocaleString("zh-CN", {hour12:false, timeZone:"Asia/Shanghai"})}${stale ? " · 暂未更新" : ""}`;
  $("updated").classList.toggle("is-stale", stale);
  const today = data.activity.find(day => day.date === data.date);
  const metrics = [["应复盘",data.summary.due_total],["待复盘",data.summary.pending_total],["超出上限",data.summary.overflow_total],["每日上限",data.summary.daily_limit],["今日复盘",today?.count ?? 0]];
  $("metrics").innerHTML = metrics.map(([label,count]) => `<div class="metric"><span>${label}</span><strong>${esc(count)}</strong></div>`).join("");
  $("heatmap").innerHTML = data.activity.map(day => {
    const title = `${day.date} · ${day.count} 次复盘${day.ratio == null ? "" : ` · ${day.completed}/${day.planned} 题 · ${Math.round(day.ratio * 100)}%`}`;
    return `<span class="heat-cell heat-${heatLevel(day)}" tabindex="0" title="${esc(title)}" aria-label="${esc(title)}"></span>`;
  }).join("");
  $("activityMeta").textContent = `近 ${data.activity.length} 天 · ${data.activity.reduce((sum, day) => sum + day.count,0)} 次`;
  $("books").innerHTML = data.books.map(book => `<span>${esc(book.label)} · 应复盘 ${esc(book.due_total)} · 待复盘 ${esc(book.pending_total)}</span>`).join("");
  $("tiers").innerHTML = data.books.map(book => `<div class="tier-group"><strong>${esc(book.label)}</strong>${Object.entries(book.tier_counts).map(([tier,count]) => `<span>${esc(tier)} · ${esc(count)}</span>`).join("")}</div>`).join("");
  for (const key of ["queue", "backlog"]) {
    $(key).innerHTML = data[key].map(item => card(item,key === "backlog")).join("") || '<p class="empty">暂无题目</p>';
    $(`${key}Count`).textContent = data[key].length;
  }
  $("queueMeta").textContent = `${data.date} · ${data.books.map(book => book.label).join(" + ")}`;
  $("backlogMeta").textContent = `暂存 ${data.backlog.length} 题`;
  $("total").textContent = `累计复盘 ${data.total_reviews} 题`;
  const days = [...new Set(data.history.map(event => event.reviewed_at.slice(0,10)))].sort().reverse();
  $("history").innerHTML = days.map(day => {
    const events = data.history.filter(event => event.reviewed_at.startsWith(day));
    return `<details class="history-day" ${day === data.date ? "open" : ""}><summary>${esc(day)} · ${events.length} 题</summary>${events.map(event => `<article class="history-item"><strong>${esc(event.display_id)}</strong><span class="book-tag">${esc(event.book_label)}</span>${context(event)}<span>${event.outcome === "pass" ? "对了" : "仍错"}</span>${levelTag(event.error_level)}<span>复习 ${esc(event.review_count)} 次</span><span>失败 ${esc(event.fail_count)} 次</span><span>下次 ${esc(event.next_due_at)}</span>${event.note ? `<div class="history-note">${esc(event.note)}</div>` : ""}</article>`).join("")}</details>`;
  }).join("") || '<p class="empty">近两日暂无复盘记录</p>';
}
function loadSnapshot() { return fetch("/snapshot.json", {cache:"no-store"}).then(response => {
  if (!response.ok) throw new Error("快照暂不可用");
  return response.json();
}).then(render); }
loadSnapshot().catch(() => { $("updated").textContent = "数据加载失败，请稍后刷新"; });
$("refreshButton").addEventListener("click", async () => {
  const button = $("refreshButton");
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  $("refreshStatus").textContent = "正在更新…";
  try {
    const response = await fetch("/refresh", {method:"POST"});
    const result = await response.json();
    if (!response.ok) throw new Error(result.message);
    await loadSnapshot();
    $("refreshStatus").textContent = result.message;
  } catch (error) {
    $("refreshStatus").textContent = error.message || "更新暂未完成，请稍后重试";
  } finally {
    button.disabled = false;
    button.removeAttribute("aria-busy");
  }
});
