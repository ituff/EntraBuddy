/* EntraBuddy Web GUI */

const ROLE_LABEL = {
  active: "当前登录",
  licensed: "许可证",
  sync: "同步账户",
  profile: "浏览器配置",
  cached: "身份缓存",
  trace: "设备策略",
};

const KIND_LABEL = { org: "工作 / 学校账户", msa: "个人账户", unknown: "未知类型" };
const CLOUD_LABEL = { global: "Microsoft 全球云", china: "世纪互联" };
const STATUS_MARK = { ok: "✓", fail: "✕", warn: "!", unknown: "?" };

const STATE = {
  data: null,
  selected: null,
  query: "",
  tab: "accounts",
  backups: [],
  cleanupOpened: false,
  batchOpened: false,
};

/* ---------- DOM 辅助 ---------- */
function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key === "style") node.setAttribute("style", value);
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function icon(pathData, size = 12) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", pathData);
  path.setAttribute("fill", "none");
  path.setAttribute("stroke", "currentColor");
  path.setAttribute("stroke-width", "1.4");
  path.setAttribute("stroke-linecap", "round");
  path.setAttribute("stroke-linejoin", "round");
  svg.append(path);
  return svg;
}

function badge(text, cls) {
  return h("span", { class: `badge ${cls}`, text });
}

/* ---------- 格式化 ---------- */
function relTime(iso) {
  if (!iso) return "从未";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const min = Math.round((Date.now() - t) / 60000);
  if (min < 1) return "刚刚";
  if (min < 60) return `${min} 分钟前`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr} 小时前`;
  const day = Math.round(hr / 24);
  if (day < 30) return `${day} 天前`;
  const mon = Math.round(day / 30);
  if (mon < 12) return `${mon} 个月前`;
  return `${Math.round(mon / 12)} 年前`;
}

function absTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function bytes(n) {
  if (!n) return "0 B";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function initials(upn) {
  const local = (upn || "?").split("@")[0];
  return local.slice(0, 1).toUpperCase() || "?";
}

/* ---------- 接口 ---------- */
async function getJSON(path) {
  const res = await fetch(path, { cache: "no-store" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

async function postJSON(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-EntraBuddy": "1" },
    body: JSON.stringify(body || {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

/* ---------- 路由 ---------- */
function parseRoute() {
  const raw = decodeURIComponent((location.hash || "").slice(1));
  if (!raw) return { tab: "accounts", account: null, action: null };
  const [tab, account, action] = raw.split("/");
  return {
    tab: ["accounts", "device", "changes"].includes(tab) ? tab : "accounts",
    account: account || null,
    action: action || null,
  };
}

function setRoute(tab, account) {
  const parts = [tab];
  if (tab === "accounts" && account) parts.push(encodeURIComponent(account));
  history.replaceState(null, "", `#${parts.join("/")}`);
}

function switchTab(tab, sync = true) {
  STATE.tab = tab;
  document.querySelectorAll(".tab").forEach((el) => {
    el.classList.toggle("active", el.dataset.tab === tab);
  });
  document.querySelectorAll(".tab-panel").forEach((el) => {
    el.classList.toggle("active", el.id === `tab-${tab}`);
  });
  if (sync) setRoute(tab, tab === "accounts" ? STATE.selected : null);
  if (tab === "changes") loadBackups();
}

/* ---------- 渲染：指标 ---------- */
function renderStats(data) {
  const s = data.summary;
  const cards = [
    { label: "账户总数", value: s.total, cls: "accent" },
    { label: "企业账户", value: s.org },
    { label: "个人账户", value: s.msa },
    { label: "世纪互联", value: s.china, cls: s.china === 0 ? "dim" : "" },
    { label: "今日活跃", value: s.active_today },
    { label: "残留缓存", value: s.stale ?? 0, cls: (s.stale ?? 0) === 0 ? "dim" : "" },
  ];
  document.getElementById("stats").replaceChildren(
    ...cards.map((c) =>
      h(
        "div",
        { class: `stat ${c.cls || ""}` },
        h("div", { class: "stat-label", text: c.label }),
        h("div", { class: "stat-value" }, String(c.value))
      )
    )
  );
}

/* ---------- 渲染：诊断 ---------- */
function renderInsights(data) {
  const host = document.getElementById("insights");
  if (!data.warnings || !data.warnings.length) {
    host.hidden = true;
    return;
  }
  host.hidden = false;
  host.replaceChildren(
    h("h3", {}, icon("M8 1.6 15 14H1L8 1.6Z", 13), "需要注意"),
    h("ul", {}, ...data.warnings.map((w) => h("li", { text: w })))
  );
}

/* ---------- 渲染：账户列表 ---------- */
function renderListTools() {
  const host = document.getElementById("list-tools");
  const stale = STATE.data.accounts.filter((a) => a.is_stale);
  if (!stale.length) {
    host.replaceChildren();
    return;
  }
  host.replaceChildren(
    h(
      "button",
      { class: "btn btn-sm btn-danger tool-btn", type: "button", onclick: openBatchCleanup },
      `批量清理残留（${stale.length}）`
    )
  );
}

function accountMatches(account, query) {
  if (!query) return true;
  const q = query.toLowerCase();
  return [account.upn, account.display_name, account.tenant_name, account.tenant_id, account.object_id]
    .filter(Boolean)
    .some((v) => String(v).toLowerCase().includes(q));
}

function renderList() {
  const data = STATE.data;
  const host = document.getElementById("account-list");
  const list = data.accounts.filter((a) => accountMatches(a, STATE.query));

  document.getElementById("account-count").textContent =
    list.length === data.accounts.length
      ? `${data.accounts.length} 个`
      : `${list.length} / ${data.accounts.length}`;

  if (!list.length) {
    host.replaceChildren(h("li", { class: "empty-state", text: "没有匹配的账户" }));
    return;
  }

  host.replaceChildren(
    ...list.map((account) =>
      h(
        "li",
        {
          class: account.key === STATE.selected ? "active" : "",
          onclick: () => selectAccount(account.key),
        },
        h("div", { class: `avatar ${account.kind}`, text: initials(account.upn) }),
        h(
          "div",
          { class: "acct-main" },
          h("div", { class: "acct-upn", text: account.upn }),
          h(
            "div",
            { class: "acct-sub" },
            account.is_active_today ? h("span", { class: "live", title: "今日活跃" }) : null,
            h("span", { text: account.kind === "org" ? "企业" : account.kind === "msa" ? "个人" : "未知" }),
            h("span", { class: "dot" }),
            h("span", { text: account.tenant_name || (account.kind === "msa" ? "Microsoft 账户" : "无租户") }),
            account.is_stale ? h("span", { class: "dot" }) : null,
            account.is_stale ? h("span", { class: "stale-tag", text: "残留" }) : null
          )
        )
      )
    )
  );
}

/* ---------- 渲染：详情 ---------- */
function propRow(label, value, opts = {}) {
  if (!value) return null;
  const dd = h("dd", { class: opts.mono === false ? "plain" : "" }, String(value));
  if (opts.copy) {
    const btn = h(
      "button",
      {
        class: "copy",
        title: "复制",
        onclick: (event) => {
          event.stopPropagation();
          navigator.clipboard?.writeText(String(value));
          btn.replaceChildren(icon("M5.5 5.5h7v7h-7z M9 3h3.5v3.5", 12));
          setTimeout(() => btn.replaceChildren(icon("M5.5 5.5h7v7h-7z M9 3h3.5v3.5", 12)), 900);
        },
      },
      icon("M5.5 5.5h7v7h-7z M9 3h3.5v3.5", 12)
    );
    dd.append(btn);
  }
  return [h("dt", { text: label }), dd];
}

const FRESH_LABEL = { fresh: "新鲜", aging: "偏旧", stale: "陈旧", unknown: "未知" };

function renderCredential(account) {
  const cred = account.credential || {};
  const rows = [];

  if (cred.cache_age_days !== null && cred.cache_age_days !== undefined) {
    const days = cred.cache_age_days;
    const text = days < 1 ? "今天更新过" : `${Math.floor(days)} 天前更新`;
    rows.push(
      h(
        "div",
        { class: "cred-row" },
        h("span", { class: "cred-label", text: "缓存新鲜度" }),
        h(
          "span",
          { class: "cred-value" },
          h("span", { class: `fresh-dot ${cred.freshness || "unknown"}` }),
          `${FRESH_LABEL[cred.freshness] || "未知"} · ${text}`
        )
      )
    );
  }

  if (cred.license) {
    const lic = cred.license;
    const days = lic.days_left;
    const level = days <= 7 ? "danger" : days <= 30 ? "warn" : "ok";
    let pct = 100;
    if (lic.not_before && lic.not_after) {
      const total = (new Date(lic.not_after) - new Date(lic.not_before)) / 86400000;
      if (total > 0) pct = Math.max(0, Math.min(100, (days / total) * 100));
    }
    rows.push(
      h(
        "div",
        { class: "cred-row" },
        h("span", { class: "cred-label", text: "Office 许可证" }),
        h("span", { class: "cred-value", text: `${lic.not_after} 到期 · 剩余 ${days} 天` })
      ),
      h("div", { class: `bar ${level}` }, h("i", { style: `width:${pct.toFixed(1)}%` }))
    );
  }

  if (!rows.length) return null;
  return h(
    "div",
    {},
    h("div", { class: "block-title", text: "凭据" }),
    h("div", { class: "cred" }, ...rows)
  );
}

function renderDetail() {
  const host = document.getElementById("detail");
  const account = STATE.data.accounts.find((a) => a.key === STATE.selected);
  if (!account) {
    host.replaceChildren(h("div", { class: "empty-state", text: "选择左侧账户查看详情" }));
    return;
  }

  const badges = [
    badge(KIND_LABEL[account.kind] || "未知", account.kind),
    badge(CLOUD_LABEL[account.cloud] || account.cloud, account.cloud),
    account.is_active_today ? badge("今日活跃", "ok") : null,
    account.is_stale ? badge("残留缓存", "muted") : null,
    account.link_confidence === "low" ? badge("关联置信度低", "warn") : null,
    account.link_confidence === "medium" ? badge("关联为推断", "muted") : null,
  ].filter(Boolean);

  const props = [
    propRow("租户名称", account.tenant_name, { mono: false }),
    propRow("租户 ID", account.tenant_id, { copy: true }),
    propRow("对象 ID", account.object_id, { copy: true }),
    propRow("CID", account.cid, { copy: true }),
    propRow("注册地", account.location),
    propRow(
      "最后活跃",
      account.last_seen ? `${absTime(account.last_seen)}（${relTime(account.last_seen)}）` : "—",
      { mono: false }
    ),
  ].filter(Boolean);

  const appRows = account.apps.length
    ? account.apps.map((app) =>
        h(
          "div",
          { class: "app-row" },
          h("span", { class: "app-name", text: app.app_name }),
          h("span", { class: "app-detail", text: app.details.join("；") }),
          h(
            "span",
            { class: "roles" },
            ...app.roles.map((r) => h("span", { class: `role ${r}`, text: ROLE_LABEL[r] || r }))
          )
        )
      )
    : [h("div", { class: "app-empty", text: "没有应用在使用这个身份" })];

  const evidence = account.evidence.map((ev) =>
    h(
      "div",
      { class: "ev-item" },
      h("div", { class: "ev-source", text: ev.source }),
      ev.detail ? h("div", { class: "ev-detail", text: ev.detail }) : null,
      ev.path ? h("div", { class: "ev-path", text: ev.path }) : null,
      ev.timestamp ? h("div", { class: "ev-time", text: absTime(ev.timestamp) }) : null
    )
  );

  host.replaceChildren(
    h(
      "div",
      { class: "detail-inner" },
      h(
        "div",
        { class: "detail-head" },
        h("div", { class: `avatar ${account.kind}`, text: initials(account.upn) }),
        h(
          "div",
          { class: "detail-title" },
          h("h2", { text: account.upn }),
          account.display_name
            ? h("div", { class: "sub", text: account.display_name })
            : h("div", { class: "sub", text: account.tenant_name || "Microsoft 账户" }),
          h("div", { class: "badges" }, ...badges)
        ),
        h(
          "button",
          {
            class: "btn btn-sm btn-danger head-action",
            type: "button",
            title: "先备份再移除，可回滚",
            onclick: () => openCleanup(account),
          },
          "清理缓存"
        )
      ),
      h("div", {}, h("div", { class: "block-title", text: "属性" }), h("dl", { class: "props" }, ...props)),
      renderCredential(account),
      h(
        "div",
        {},
        h("div", { class: "block-title", text: "使用此身份的应用" }),
        h("div", { class: "app-rows" }, ...appRows)
      ),
      h("div", {}, h("div", { class: "block-title", text: "证据链" }), h("div", { class: "evidence" }, ...evidence)),
      account.notes.length
        ? h(
            "div",
            {},
            h("div", { class: "block-title", text: "备注" }),
            h("div", { class: "notes" }, ...account.notes.map((n) => h("div", { class: "note", text: n })))
          )
        : null
    )
  );
}

/* ---------- 渲染：应用 ---------- */
function renderApps() {
  const host = document.getElementById("app-grid");
  const IDENTITY_KINDS = new Set(["office", "browser", "sync", "chat", "mdm", "assistant"]);
  const apps = STATE.data.apps.filter(
    (a) => a.accounts.length || (a.installed && IDENTITY_KINDS.has(a.kind))
  );

  host.replaceChildren(
    ...apps.map((app) => {
      const card = h(
        "div",
        { class: `app-card ${app.installed ? "" : "missing"}` },
        h(
          "div",
          { class: "app-card-head" },
          h("span", { class: "app-card-title", text: app.name }),
          h("span", {
            class: "app-card-meta",
            text: app.installed ? `${app.accounts.length} 个身份` : "未安装 · 仅残留",
          })
        )
      );
      if (app.accounts.length) {
        card.append(
          h(
            "div",
            { class: "app-accounts" },
            ...app.accounts.map((acc) =>
              h(
                "div",
                {
                  class: "app-account",
                  onclick: () => selectAccount(acc.key),
                  title: acc.details.join("；"),
                },
                h("span", { class: "upn", text: acc.upn }),
                h(
                  "span",
                  { class: "roles" },
                  ...acc.roles.map((r) => h("span", { class: `role ${r}`, text: ROLE_LABEL[r] || r }))
                )
              )
            )
          )
        );
      } else {
        card.append(h("div", { class: "app-empty", text: "没有绑定任何账户" }));
      }
      return card;
    })
  );
}

/* ---------- 渲染：设备 ---------- */
function renderDevice(device) {
  if (!device) return;

  const id = device.identity || {};
  const rows = [
    ["主机名", id.hostname, false],
    ["型号", id.model, false],
    ["芯片", id.chip, false],
    ["序列号", id.serial, true],
    ["系统版本", id.os_version ? `macOS ${id.os_version} (${id.os_build || ""})` : null, false],
  ].filter(([, v]) => v);

  document.getElementById("device-identity").replaceChildren(
    ...rows.map(([k, v, mono]) =>
      h(
        "div",
        { class: "kv-row" },
        h("span", { class: "kv-key", text: k }),
        h("span", { class: `kv-val ${mono ? "" : "plain"}`, text: String(v) })
      )
    )
  );

  const enr = device.enrollment || {};
  const entra = enr.entra || {};
  const mdm = enr.mdm || {};
  const ad = enr.ad || {};

  const stateRow = (status, title, detail, value) =>
    h(
      "div",
      { class: "state-row" },
      h("div", { class: `state-icon ${status}`, text: STATUS_MARK[status] || "?" }),
      h(
        "div",
        { class: "state-text" },
        h("div", { class: "state-title", text: title }),
        h("div", { class: "state-detail", text: detail })
      ),
      h("div", { class: "state-value", text: value })
    );

  const enrHost = document.getElementById("device-enrollment");
  enrHost.replaceChildren(
    stateRow(
      entra.registered ? "ok" : "fail",
      "Entra ID 设备注册",
      entra.registered
        ? "检测到 Company Portal 或设备证书"
        : "未找到 Company Portal、设备证书或 broker 缓存",
      entra.registered ? "已注册" : "未注册"
    ),
    stateRow(
      mdm.enrolled ? "ok" : "fail",
      "MDM 注册",
      mdm.enrolled ? "设备受移动设备管理" : "未注册，Intune 无法下发策略",
      mdm.enrolled ? "已注册" : "未注册"
    ),
    stateRow(
      ad.joined ? "warn" : "unknown",
      "Active Directory 绑定",
      ad.joined ? `已绑定域 ${ad.domain}` : "未加入传统 AD 域",
      ad.joined ? "已绑定" : "未绑定"
    ),
    h("p", { class: "card-foot", text: entra.note || "" })
  );

  const comp = device.compliance || {};
  const score = comp.score || 0;
  document.getElementById("compliance-score").replaceChildren(
    h("span", { text: `${comp.passed}/${comp.total} 项通过` }),
    h(
      "div",
      { class: "score-ring", style: `--pct:${score}%` },
      h("span", { text: `${score}` })
    )
  );

  document.getElementById("compliance-list").replaceChildren(
    ...(comp.checks || []).map((c) =>
      h(
        "div",
        { class: "check-row" },
        h("div", { class: `state-icon ${c.status}`, text: STATUS_MARK[c.status] || "?" }),
        h(
          "div",
          { class: "check-body" },
          h("div", { class: "check-label", text: `${c.label} · ${c.value}` }),
          h("div", { class: "check-detail", text: c.detail })
        )
      )
    )
  );
  document.getElementById("compliance-note").textContent = device.note || "";
}

/* ---------- 渲染：变更 ---------- */
function renderChanges() {
  const data = STATE.data;
  const host = document.getElementById("changes-diff");
  const payload = data.changes || {};
  const diff = payload.diff;

  if (!diff) {
    host.replaceChildren(h("div", { class: "diff-empty", text: payload.hint || "暂无对比数据" }));
  } else if (!diff.has_changes) {
    host.replaceChildren(
      h("div", { class: "diff-empty", text: `与 ${absTime(diff.from.saved_at)} 的快照相比没有变化。` })
    );
  } else {
    const groups = [];
    if (diff.added.length) {
      groups.push(
        h(
          "div",
          { class: "diff-group" },
          h("div", { class: "diff-title", text: `新增 ${diff.added.length}` }),
          ...diff.added.map((a) =>
            h(
              "div",
              { class: "diff-item added" },
              h("span", { class: "upn", text: a.upn }),
              h("span", { class: "diff-change", text: a.tenant || (a.kind === "msa" ? "个人账户" : "") })
            )
          )
        )
      );
    }
    if (diff.removed.length) {
      groups.push(
        h(
          "div",
          { class: "diff-group" },
          h("div", { class: "diff-title", text: `消失 ${diff.removed.length}` }),
          ...diff.removed.map((a) =>
            h(
              "div",
              { class: "diff-item removed" },
              h("span", { class: "upn", text: a.upn }),
              h("span", { class: "diff-change", text: a.tenant || "" })
            )
          )
        )
      );
    }
    if (diff.changed.length) {
      groups.push(
        h(
          "div",
          { class: "diff-group" },
          h("div", { class: "diff-title", text: `变化 ${diff.changed.length}` }),
          ...diff.changed.map((c) =>
            h(
              "div",
              { class: "diff-item changed" },
              h("span", { class: "upn", text: c.upn }),
              h(
                "span",
                { class: "diff-change" },
                c.changes.map((f) => `${f.field} ${f.from} → ${f.to}`).join("；")
              )
            )
          )
        )
      );
    }
    host.replaceChildren(
      h("div", { class: "summary-line" }, `对比基准：${absTime(diff.from.saved_at)}`),
      ...groups
    );
  }

  const snaps = (payload.snapshots || []).slice(0, 12);
  document.getElementById("snapshot-count").textContent = `${(payload.snapshots || []).length} 个`;
  const snapHost = document.getElementById("snapshot-list");
  if (!snaps.length) {
    snapHost.replaceChildren(h("div", { class: "diff-empty", text: "还没有快照，扫描会自动记录" }));
  } else {
    snapHost.replaceChildren(
      ...snaps.map((s) =>
        h(
          "div",
          { class: "list-row" },
          h("span", { class: "grow", text: absTime(s.saved_at) }),
          h("span", { class: "mono", text: `${s.account_count} 账户` }),
          h("span", { class: "mono", text: s.id })
        )
      )
    );
  }
}

async function loadBackups() {
  try {
    const data = await getJSON("/api/backups");
    STATE.backups = data.backups || [];
  } catch {
    STATE.backups = [];
  }
  const host = document.getElementById("backup-list");
  document.getElementById("backup-count").textContent = `${STATE.backups.length} 个`;
  if (!STATE.backups.length) {
    host.replaceChildren(h("div", { class: "diff-empty", text: "还没有清理备份" }));
    return;
  }
  host.replaceChildren(
    ...STATE.backups.map((b) =>
      h(
        "div",
        { class: "list-row" },
        h(
          "span",
          { class: "grow" },
          h("div", { text: b.account || "未知账户" }),
          h("div", { class: "mono", text: `${b.file_count} 个文件 · ${b.display_path}` })
        ),
        h("span", { class: "time", text: relTime(b.created_at) }),
        h(
          "button",
          {
            class: "btn btn-sm",
            type: "button",
            onclick: (event) => restoreBackup(b.id, event.target),
          },
          "恢复"
        )
      )
    )
  );
}

async function restoreBackup(id, btn) {
  btn.disabled = true;
  try {
    const res = await postJSON("/api/cleanup/restore", { id });
    btn.textContent = `已恢复 ${res.restored}`;
    await load(true);
  } catch (err) {
    btn.textContent = "失败";
    btn.title = err.message;
  } finally {
    setTimeout(() => {
      btn.disabled = false;
      btn.textContent = "恢复";
    }, 2200);
  }
}

/* ---------- 清理弹窗 ---------- */
function closeModal() {
  document.getElementById("modal-root").replaceChildren();
  document.removeEventListener("keydown", onModalKey);
}

function onModalKey(event) {
  if (event.key === "Escape") closeModal();
}

async function openCleanup(account) {
  const root = document.getElementById("modal-root");
  root.replaceChildren(
    h(
      "div",
      { class: "modal-overlay", onclick: (e) => e.target.classList.contains("modal-overlay") && closeModal() },
      h(
        "div",
        { class: "modal" },
        h("div", { class: "modal-head" }, h("h2", { text: "正在生成清理计划…" })),
        h("div", { class: "modal-body" }, h("div", { class: "diff-empty", text: "读取账户缓存文件…" }))
      )
    )
  );
  document.addEventListener("keydown", onModalKey);

  let plan;
  try {
    plan = await postJSON("/api/cleanup/plan", { upn: account.upn });
  } catch (err) {
    renderModalError(err.message);
    return;
  }

  if (!plan.file_count) {
    root.replaceChildren(
      h(
        "div",
        { class: "modal-overlay", onclick: (e) => e.target.classList.contains("modal-overlay") && closeModal() },
        h(
          "div",
          { class: "modal" },
          h("div", { class: "modal-head" }, h("h2", { text: "没有可清理的缓存" }), h("p", { text: account.upn })),
          h("div", { class: "modal-body" }, h("div", { class: "diff-empty", text: "该账户没有独立的身份缓存文件。" })),
          h("div", { class: "modal-foot" }, h("button", { class: "btn", type: "button", onclick: closeModal }, "关闭"))
        )
      )
    );
    return;
  }

  const activeWarning = account.is_active_today
    ? h(
        "div",
        { class: "modal-warn" },
        h("strong", { text: "这个账户今天仍在使用" }),
        "清理后对应应用需要重新登录。如果只想清掉历史残留，建议先切换到其它账户。"
      )
    : null;

  const fileRows = plan.files.map((f) =>
    h(
      "div",
      { class: "file-row" },
      h("span", { class: "fname", text: f.name }),
      h("span", { class: "freason", text: f.reason }),
      h("span", { class: "fsize", text: bytes(f.size) })
    )
  );

  const confirmBtn = h(
    "button",
    {
      class: "btn btn-danger",
      type: "button",
      onclick: async () => {
        confirmBtn.disabled = true;
        confirmBtn.textContent = "正在备份并清理…";
        try {
          const res = await postJSON("/api/cleanup/run", {
            upn: account.upn,
            expected: plan.file_count,
            confirm: "yes",
          });
          renderCleanupResult(res, account.upn);
          await load(true);
        } catch (err) {
          renderModalError(err.message);
        }
      },
    },
    "确认清理并备份"
  );

  root.replaceChildren(
    h(
      "div",
      { class: "modal-overlay", onclick: (e) => e.target.classList.contains("modal-overlay") && closeModal() },
      h(
        "div",
        { class: "modal" },
        h(
          "div",
          { class: "modal-head" },
          h("h2", { text: "清理账户缓存" }),
          h("p", { text: account.upn })
        ),
        h(
          "div",
          { class: "modal-body" },
          activeWarning,
          h(
            "div",
            { class: "modal-warn" },
            h("strong", { text: "操作前会自动备份" }),
            "所有文件会先复制到 ~/Library/Application Support/EntraBuddy/backups，"
              + "备份校验通过后才删除。可在「变更」页恢复。"
          ),
          h(
            "div",
            { class: "summary-line" },
            h("span", { text: `${plan.file_count} 个文件` }),
            h("span", { text: bytes(plan.total_bytes) }),
            h("span", { text: plan.root })
          ),
          ...fileRows,
          ...(plan.warnings || []).map((w) => h("p", { class: "card-foot", text: `· ${w}` }))
        ),
        h(
          "div",
          { class: "modal-foot" },
          h("button", { class: "btn", type: "button", onclick: closeModal }, "取消"),
          confirmBtn
        )
      )
    )
  );
}

async function openBatchCleanup() {
  const stale = STATE.data.accounts.filter((a) => a.is_stale);
  if (!stale.length) return;

  const root = document.getElementById("modal-root");
  root.replaceChildren(
    h(
      "div",
      { class: "modal-overlay" },
      h(
        "div",
        { class: "modal" },
        h("div", { class: "modal-head" }, h("h2", { text: "正在生成批量清理计划…" })),
        h("div", { class: "modal-body" }, h("div", { class: "diff-empty", text: "统计残留账户的缓存文件…" }))
      )
    )
  );
  document.addEventListener("keydown", onModalKey);

  let plan;
  try {
    plan = await postJSON("/api/cleanup/batch-plan", { upns: stale.map((a) => a.upn) });
  } catch (err) {
    renderModalError(err.message);
    return;
  }

  const checks = [];
  const rows = plan.accounts.map((acc) => {
    const cb = h("input", { type: "checkbox", value: acc.upn });
    cb.checked = acc.file_count > 0;
    cb.disabled = acc.file_count === 0;
    cb.addEventListener("change", () => updateTotal());
    checks.push(cb);
    return h(
      "label",
      { class: "pick-row" },
      cb,
      h(
        "span",
        { class: "pick-main" },
        h("div", { class: "pick-upn", text: acc.upn }),
        h("div", {
          class: "pick-sub",
          text: `${acc.tenant_name || "Microsoft 账户"} · ${acc.file_count} 个文件 · ${bytes(acc.bytes)}`,
        })
      )
    );
  });

  const totalLine = h("div", { class: "summary-line" });

  function selected() {
    return checks.filter((c) => c.checked).map((c) => c.value);
  }

  function updateTotal() {
    const picked = new Set(selected());
    const chosen = plan.accounts.filter((a) => picked.has(a.upn));
    const count = chosen.reduce((sum, a) => sum + a.file_count, 0);
    const size = chosen.reduce((sum, a) => sum + a.bytes, 0);
    totalLine.replaceChildren(
      h("span", { text: `已选 ${picked.size} 个账户` }),
      h("span", { text: `${count} 个文件 · ${bytes(size)}` })
    );
  }
  updateTotal();

  const confirmBtn = h(
    "button",
    { class: "btn btn-danger", type: "button" },
    "清理所选账户"
  );
  confirmBtn.addEventListener("click", async () => {
    const upns = selected();
    if (!upns.length) return;
    confirmBtn.disabled = true;
    confirmBtn.textContent = "正在备份并清理…";
    try {
      const fresh = await postJSON("/api/cleanup/batch-plan", { upns });
      if (!fresh.file_count) {
        closeModal();
        return;
      }
      const res = await postJSON("/api/cleanup/batch-run", {
        upns,
        expected: fresh.file_count,
        confirm: "yes",
      });
      renderCleanupResult(res, `${upns.length} 个账户`);
      await load(true);
    } catch (err) {
      renderModalError(err.message);
    }
  });

  root.replaceChildren(
    h(
      "div",
      { class: "modal-overlay", onclick: (e) => e.target.classList.contains("modal-overlay") && closeModal() },
      h(
        "div",
        { class: "modal" },
        h(
          "div",
          { class: "modal-head" },
          h("h2", { text: "批量清理残留账户" }),
          h("p", { text: "勾选要移除缓存的账户，全部文件会先备份再删除" })
        ),
        h(
          "div",
          { class: "modal-body" },
          h(
            "div",
            { class: "modal-warn" },
            h("strong", { text: "这些账户今天都没有活跃" }),
            "清理只影响本地身份缓存，不会吊销令牌。如果之后还要用这些账户，需要重新登录。"
          ),
          h("div", { class: "pick-list" }, ...rows),
          totalLine,
          ...(plan.warnings || []).map((w) => h("p", { class: "card-foot", text: `· ${w}` }))
        ),
        h(
          "div",
          { class: "modal-foot" },
          h("button", { class: "btn", type: "button", onclick: closeModal }, "取消"),
          confirmBtn
        )
      )
    )
  );
}

function renderCleanupResult(res, label) {
  const root = document.getElementById("modal-root");
  root.replaceChildren(
    h(
      "div",
      { class: "modal-overlay", onclick: (e) => e.target.classList.contains("modal-overlay") && closeModal() },
      h(
        "div",
        { class: "modal" },
        h("div", { class: "modal-head" }, h("h2", { text: "清理完成" }), h("p", { text: label })),
        h(
          "div",
          { class: "modal-body" },
          h(
            "div",
            { class: `result-box ${res.ok ? "ok" : "err"}` },
            h("div", { text: res.message }),
            res.backup_display ? h("div", { class: "path", text: `备份位置：${res.backup_display}` }) : null,
            res.failed && res.failed.length
              ? h("div", { class: "path", text: `失败文件：${res.failed.join(", ")}` })
              : null
          ),
          h("p", { class: "card-foot", text: "可在「变更」页的清理备份列表中一键恢复。" })
        ),
        h(
          "div",
          { class: "modal-foot" },
          h("button", { class: "btn btn-primary", type: "button", onclick: closeModal }, "完成")
        )
      )
    )
  );
}

function renderModalError(message) {
  document.getElementById("modal-root").replaceChildren(
    h(
      "div",
      { class: "modal-overlay", onclick: (e) => e.target.classList.contains("modal-overlay") && closeModal() },
      h(
        "div",
        { class: "modal" },
        h("div", { class: "modal-head" }, h("h2", { text: "操作失败" })),
        h("div", { class: "modal-body" }, h("div", { class: "result-box err", text: message })),
        h(
          "div",
          { class: "modal-foot" },
          h("button", { class: "btn", type: "button", onclick: closeModal }, "关闭")
        )
      )
    )
  );
}

/* ---------- 交互 ---------- */
function selectAccount(key) {
  STATE.selected = key;
  setRoute("accounts", key);
  renderList();
  renderDetail();
  document.getElementById("detail").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function renderAll() {
  const data = STATE.data;
  renderStats(data);
  renderInsights(data);

  const route = parseRoute();
  if (route.account && data.accounts.some((a) => a.key === route.account.toLowerCase())) {
    STATE.selected = route.account.toLowerCase();
  } else if (!STATE.selected && data.accounts.length) {
    STATE.selected = data.accounts[0].key;
  }

  renderList();
  renderListTools();
  renderDetail();
  renderApps();
  renderDevice(data.device);
  renderChanges();

  // 深链接：#accounts/<upn>/cleanup 打开单账户清理，#accounts//batch 打开批量清理
  if (route.action === "cleanup" && !STATE.cleanupOpened) {
    const target = data.accounts.find((a) => a.key === STATE.selected);
    if (target) {
      STATE.cleanupOpened = true;
      openCleanup(target);
    }
  }
  if ((route.action === "batch" || route.account === "batch") && !STATE.batchOpened) {
    STATE.batchOpened = true;
    openBatchCleanup();
  }

  const src = data.sources || {};
  document.getElementById("source-line").textContent =
    `OneAuth ${src.oneauth?.file_count ?? 0} 个缓存文件 · Edge ${src.edge?.profiles ?? 0} 个配置 · `
    + `OneDrive ${src.onedrive?.accounts ?? 0} 个账户 · 扫描耗时 ${data.duration_ms} ms`;
}

async function load(force = false) {
  const btn = document.getElementById("rescan");
  btn.disabled = true;
  btn.classList.add("spinning");
  try {
    STATE.data = await getJSON("/api/scan");
    document.getElementById("scan-time").textContent = `扫描于 ${absTime(STATE.data.generated_at)}`;
    renderAll();
    if (STATE.tab === "changes") loadBackups();
  } catch (err) {
    document.getElementById("detail").replaceChildren(
      h("div", { class: "empty-state", text: `扫描失败：${err.message}` })
    );
  } finally {
    btn.disabled = false;
    btn.classList.remove("spinning");
  }
}

/* ---------- 启动 ---------- */
document.getElementById("rescan").addEventListener("click", () => load(true));
document.getElementById("search").addEventListener("input", (event) => {
  STATE.query = event.target.value.trim();
  renderList();
});
document.getElementById("tabs").addEventListener("click", (event) => {
  const tab = event.target.closest(".tab");
  if (tab) switchTab(tab.dataset.tab);
});
document.getElementById("save-snapshot").addEventListener("click", async (event) => {
  const btn = event.target;
  btn.disabled = true;
  try {
    await postJSON("/api/snapshot", {});
    await load(true);
    btn.textContent = "已记录";
  } catch (err) {
    btn.textContent = "失败";
  } finally {
    setTimeout(() => {
      btn.disabled = false;
      btn.textContent = "记录当前快照";
    }, 1800);
  }
});
window.addEventListener("hashchange", () => {
  const route = parseRoute();
  switchTab(route.tab, false);
  if (route.account && STATE.data?.accounts.some((a) => a.key === route.account.toLowerCase())) {
    selectAccount(route.account.toLowerCase());
  }
});

(async function init() {
  const route = parseRoute();
  switchTab(route.tab, false);
  await load();
})();
