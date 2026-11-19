const TOKEN_KEY = "campus_express_token";

const STATUS = {
  pending: { label: "待接单", cls: "pending" },
  taken: { label: "已接单", cls: "taken" },
  delivering: { label: "配送中", cls: "delivering" },
  delivered: { label: "已送达", cls: "delivered" },
  signed: { label: "已签收", cls: "signed" },
  cancelled: { label: "已取消", cls: "cancelled" },
};

const STEP_LABELS = ["发布", "接单", "取件", "送达", "签收"];
const STEP_KEYS = ["pending", "taken", "delivering", "delivered", "signed"];

const ROLE_LABELS = { student: "学生", courier: "骑手", admin: "管理员" };
const FLOW_LABELS = {
  recharge: "钱包充值",
  order_pay: "订单支出",
  order_income: "配送收入",
};

const state = {
  token: localStorage.getItem(TOKEN_KEY) || "",
  user: null,
  tab: "",
  orders: [],
  available: [],
  adminOrders: [],
  stats: null,
  wallet: null,
  flows: [],
  credit: null,
  loading: false,
};

function esc(value) {
  return String(value == null ? "" : value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json" };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(path, { ...options, headers });
  let payload = null;
  try {
    payload = await response.json();
  } catch (error) {
    payload = null;
  }
  if (response.status === 401) {
    clearSession(false);
  }
  if (!response.ok || !payload || payload.code !== 0) {
    throw new Error((payload && payload.message) || "请求失败，请稍后重试");
  }
  return payload.data;
}

const get = (path) => api(path);
const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body || {}) });

function showToast(message, isError = false) {
  const node = document.getElementById("toast");
  node.textContent = message;
  node.className = `toast${isError ? " error" : ""}`;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => node.classList.add("hidden"), 2600);
}

function clearSession(notify = true) {
  state.token = "";
  state.user = null;
  state.orders = [];
  state.available = [];
  state.adminOrders = [];
  state.stats = null;
  state.wallet = null;
  state.flows = [];
  state.credit = null;
  localStorage.removeItem(TOKEN_KEY);
  document.getElementById("app-view").classList.add("hidden");
  document.getElementById("login-view").classList.remove("hidden");
  document.getElementById("user-area").classList.add("hidden");
  if (notify) showToast("登录已失效，请重新登录", true);
}

function setSession(token) {
  state.token = token;
  localStorage.setItem(TOKEN_KEY, token);
}

function statusInfo(order) {
  if (order.status === "pending" && order.expired) {
    return { label: "已超时", cls: "pending" };
  }
  return STATUS[order.status] || { label: order.status, cls: "pending" };
}

function roleLabel(role) {
  return ROLE_LABELS[role] || role;
}

function formatFlowType(type) {
  return FLOW_LABELS[type] || type;
}

function renderUserArea() {
  if (!state.user) {
    document.getElementById("user-area").classList.add("hidden");
    return;
  }
  const user = state.user;
  const initials = user.phone.slice(-2);
  document.getElementById("user-area").innerHTML = `
    <div class="user-meta">
      <strong>${esc(roleLabel(user.role))} · ${esc(user.phone)}</strong>
      <span>信用 ${esc(user.credit_score)} · 余额 ¥${esc(user.wallet)}</span>
    </div>
    <div class="user-chip">${esc(initials)}</div>
    <button class="ghost-btn" type="button" id="logout-btn">退出</button>
  `;
  document.getElementById("logout-btn").addEventListener("click", () => clearSession(false));
  document.getElementById("user-area").classList.remove("hidden");
}

function tabsForRole(role) {
  if (role === "courier") {
    return [
      { id: "available", label: "可接订单" },
      { id: "delivery", label: "我的配送" },
      { id: "wallet", label: "钱包" },
      { id: "credit", label: "信用" },
    ];
  }
  if (role === "admin") {
    return [
      { id: "overview", label: "数据概览" },
      { id: "all", label: "全部订单" },
    ];
  }
  return [
    { id: "mine", label: "我的订单" },
    { id: "publish", label: "发布订单" },
    { id: "wallet", label: "钱包" },
    { id: "credit", label: "信用" },
  ];
}

function renderSidebar() {
  if (!state.user) return;
  const tabs = tabsForRole(state.user.role);
  if (!tabs.some((tab) => tab.id === state.tab)) state.tab = tabs[0].id;
  const counts = {
    mine: state.orders.length,
    delivery: state.orders.length,
    available: state.available.length,
    all: state.adminOrders.length,
  };
  document.getElementById("sidebar-nav").innerHTML = tabs
    .map((tab) => {
      const count = counts[tab.id];
      return `<button type="button" class="nav-btn ${tab.id === state.tab ? "active" : ""}" data-tab="${tab.id}">
        <span>${esc(tab.label)}</span>
        ${count != null ? `<span class="nav-count">${count}</span>` : ""}
      </button>`;
    })
    .join("");
  document.querySelectorAll("#sidebar-nav .nav-btn").forEach((button) => {
    button.addEventListener("click", () => switchTab(button.dataset.tab));
  });
}

function switchTab(tab) {
  state.tab = tab;
  renderSidebar();
  refreshCurrentTab();
}

async function refreshAll() {
  if (!state.user) return;
  state.loading = true;
  try {
    const role = state.user.role;
    if (role === "student") {
      const [orders, wallet, flows, credit] = await Promise.all([
        get("/api/orders?scope=mine"),
        get("/api/wallet"),
        get("/api/flows"),
        get("/api/credit"),
      ]);
      state.orders = orders.items;
      state.wallet = wallet.wallet;
      state.flows = flows;
      state.credit = credit;
    } else if (role === "courier") {
      const [available, orders, wallet, flows, credit] = await Promise.all([
        get("/api/orders?scope=available"),
        get("/api/orders?scope=courier"),
        get("/api/wallet"),
        get("/api/flows"),
        get("/api/credit"),
      ]);
      state.available = available.items;
      state.orders = orders.items;
      state.wallet = wallet.wallet;
      state.flows = flows;
      state.credit = credit;
    } else {
      const [stats, orders] = await Promise.all([
        get("/api/admin/stats"),
        get("/api/admin/orders"),
      ]);
      state.stats = stats;
      state.adminOrders = orders.items;
    }
    renderCurrentTab();
    renderSidebar();
    renderUserArea();
  } catch (error) {
    showToast(error.message, true);
  } finally {
    state.loading = false;
  }
}

async function refreshCurrentTab() {
  if (state.loading) return;
  state.loading = true;
  renderCurrentTab(true);
  try {
    const role = state.user.role;
    if (state.tab === "mine") {
      state.orders = (await get("/api/orders?scope=mine")).items;
    } else if (state.tab === "available") {
      state.available = (await get("/api/orders?scope=available")).items;
    } else if (state.tab === "delivery") {
      state.orders = (await get("/api/orders?scope=courier")).items;
    } else if (state.tab === "wallet") {
      const [wallet, flows] = await Promise.all([get("/api/wallet"), get("/api/flows")]);
      state.wallet = wallet.wallet;
      state.flows = flows;
    } else if (state.tab === "credit") {
      state.credit = await get("/api/credit");
    } else if (state.tab === "overview") {
      state.stats = await get("/api/admin/stats");
    } else if (state.tab === "all") {
      state.adminOrders = (await get("/api/admin/orders")).items;
    }
    renderCurrentTab();
    renderSidebar();
    renderUserArea();
  } catch (error) {
    showToast(error.message, true);
  } finally {
    state.loading = false;
  }
}

function emptyState(title, hint) {
  return `<div class="empty"><strong>${esc(title)}</strong>${esc(hint)}</div>`;
}

function orderCard(order) {
  const info = statusInfo(order);
  const time = order.created_at || "";
  return `
    <article class="order-card" data-open-order="${order.id}">
      <div class="order-main">
        <div class="order-title-row">
          <strong>${esc(order.title)}</strong>
          <span class="status-pill status-${info.cls}">${esc(info.label)}</span>
        </div>
        <p class="order-route">${esc(order.pickup)} → ${esc(order.dropoff)}</p>
        <p class="order-sub">${esc(order.order_no)}　${esc(time)}　超时 ${esc(order.timeout_minutes)} 分钟</p>
      </div>
      <div class="order-side">
        <div class="order-fee">¥${esc(order.fee)}<span> 跑腿费</span></div>
        <div class="order-arrow">›</div>
      </div>
    </article>
  `;
}

function orderList(orders, emptyTitle, emptyHint) {
  if (!orders || !orders.length) return emptyState(emptyTitle, emptyHint);
  return `<div class="order-list">${orders.map(orderCard).join("")}</div>`;
}

function pageHeader(kicker, title, actions = "") {
  document.getElementById("page-kicker").textContent = kicker;
  document.getElementById("page-title").textContent = title;
  document.getElementById("page-actions").innerHTML = actions;
}

function renderCurrentTab(loading = false) {
  if (!state.user) return;
  const content = document.getElementById("tab-content");
  if (!content) return;
  if (loading) {
    content.innerHTML = `<div class="panel"><div class="empty"><strong>正在读取数据</strong>请稍候…</div></div>`;
    return;
  }

  const role = state.user.role;
  if (state.tab === "mine") {
    pageHeader("学生工作台", "我的订单", `<button class="primary-btn" type="button" data-go-tab="publish">发布代取</button>`);
    content.innerHTML = `<div class="overview-grid">
      <div class="stat-card"><span class="label">钱包余额</span><span class="value">¥${esc(state.wallet || "0.00")}</span><span class="hint">签收后从余额结算</span></div>
      <div class="stat-card"><span class="label">信用分</span><span class="value">${esc(state.credit ? state.credit.credit_score : "--")}</span><span class="hint">评价会影响信用</span></div>
      <div class="stat-card"><span class="label">进行中</span><span class="value">${state.orders.filter((o) => ["pending", "taken", "delivering", "delivered"].includes(o.status)).length}</span><span class="hint">未签收的订单</span></div>
      <div class="stat-card"><span class="label">已完成</span><span class="value">${state.orders.filter((o) => o.status === "signed").length}</span><span class="hint">已签收订单</span></div>
    </div>
    <div class="panel">
      <div class="panel-head"><h3>订单记录</h3><span>点击订单查看时间线与存证</span></div>
      ${orderList(state.orders, "还没有发布过代取订单", "点右上角“发布代取”，填写取件点、送达点和跑腿费。")}
    </div>`;
  } else if (state.tab === "publish") {
    pageHeader("学生工作台", "发布代取", "");
    content.innerHTML = `<div class="panel">
      <div class="panel-head"><h3>填写代取需求</h3><span>发布后进入接单大厅</span></div>
      <form id="publish-form" class="auth-form" style="padding-top:0">
        <div class="form-grid">
          <div class="field full"><label for="order-title">物品描述</label><input id="order-title" maxlength="30" placeholder="例如：中通快递一件，纸箱包装" required><span class="help">2-30 个字，写清物品和数量</span></div>
          <div class="field"><label for="order-pickup">取件地点</label><input id="order-pickup" maxlength="50" placeholder="例如：菜鸟驿站（1 号门）" required></div>
          <div class="field"><label for="order-dropoff">送达地点</label><input id="order-dropoff" maxlength="50" placeholder="例如：3 栋 201" required></div>
          <div class="field"><label for="order-fee">跑腿费（元）</label><input id="order-fee" type="number" min="1" max="500" step="0.01" value="5" required><span class="help">1-500 元，签收后结算给骑手</span></div>
          <div class="field"><label for="order-timeout">超时时间（分钟）</label><input id="order-timeout" type="number" min="10" max="180" step="1" value="60" required><span class="help">10-180 分钟</span></div>
        </div>
        <div class="form-row"><button class="primary-btn" type="submit">发布到接单大厅</button><span class="help">发布时不会立即扣款；下单人签收后才结算。</span></div>
        <p id="publish-error" class="form-error"></p>
      </form>
    </div>`;
    document.getElementById("publish-form").addEventListener("submit", submitOrder);
  } else if (state.tab === "available") {
    pageHeader("骑手工作台", "可接订单", `<button class="ghost-btn" type="button" data-refresh>刷新</button>`);
    content.innerHTML = `<div class="panel">
      <div class="panel-head"><h3>待接单</h3><span>接单后请按状态推进配送</span></div>
      ${orderList(state.available, "接单大厅暂时没有订单", "学生发布代取需求后，会出现在这里。")}
    </div>`;
  } else if (state.tab === "delivery") {
    pageHeader("骑手工作台", "我的配送", `<button class="ghost-btn" type="button" data-refresh>刷新</button>`);
    content.innerHTML = `<div class="overview-grid">
      <div class="stat-card"><span class="label">钱包余额</span><span class="value">¥${esc(state.wallet || "0.00")}</span><span class="hint">签收后到账</span></div>
      <div class="stat-card"><span class="label">信用分</span><span class="value">${esc(state.credit ? state.credit.credit_score : "--")}</span><span class="hint">评价会影响信用</span></div>
      <div class="stat-card"><span class="label">配送中</span><span class="value">${state.orders.filter((o) => o.status === "delivering").length}</span><span class="hint">已取件、未送达</span></div>
      <div class="stat-card"><span class="label">已接单</span><span class="value">${state.orders.filter((o) => o.status === "taken").length}</span><span class="hint">待取件</span></div>
    </div>
    <div class="panel">
      <div class="panel-head"><h3>我接的订单</h3><span>在详情里操作取件和送达</span></div>
      ${orderList(state.orders, "还没有接过订单", "去“可接订单”看看有没有顺路的单子。")}
    </div>`;
  } else if (state.tab === "wallet") {
    pageHeader("账户", "钱包", `<button class="ghost-btn" type="button" data-refresh>刷新</button>`);
    content.innerHTML = `<div class="overview-grid">
      <div class="stat-card"><span class="label">可用余额</span><span class="value">¥${esc(state.wallet || "0.00")}</span><span class="hint">充值 1-1000 元</span></div>
      <div class="stat-card"><span class="label">流水笔数</span><span class="value">${state.flows.length}</span><span class="hint">充值与订单结算</span></div>
    </div>
    <div class="panel">
      <div class="panel-head"><h3>充值</h3><span>演示环境，不接真实支付</span></div>
      <form id="recharge-form" class="form-row">
        <div class="field" style="flex:1;max-width:260px"><label for="recharge-amount">充值金额（元）</label><input id="recharge-amount" type="number" min="1" max="1000" step="0.01" value="50" required></div>
        <button class="primary-btn" type="submit">确认充值</button>
      </form>
      <p id="recharge-error" class="form-error"></p>
    </div>
    <div class="panel">
      <div class="panel-head"><h3>钱包流水</h3><span>按下单时间倒序</span></div>
      ${flowList(state.flows)}
    </div>`;
    document.getElementById("recharge-form").addEventListener("submit", rechargeWallet);
  } else if (state.tab === "credit") {
    pageHeader("账户", "信用", `<button class="ghost-btn" type="button" data-refresh>刷新</button>`);
    content.innerHTML = `<div class="panel">
      <div class="panel-head"><h3>当前信用分</h3><span>初始 100 分</span></div>
      <div class="credit-score">${esc(state.credit ? state.credit.credit_score : "--")}<span>分</span></div>
      <p class="hero-copy" style="margin-top:8px;font-size:12px">订单签收后可以评价骑手：4-5 星加 1 分，1-2 星减 1 分。信用记录会写进 credit_logs 表。</p>
    </div>
    <div class="panel">
      <div class="panel-head"><h3>变动记录</h3><span>最近优先</span></div>
      ${creditList(state.credit ? state.credit.logs : [])}
    </div>`;
  } else if (state.tab === "overview") {
    pageHeader("管理员工作台", "数据概览", `<button class="ghost-btn" type="button" data-refresh>刷新</button>`);
    content.innerHTML = renderStats();
  } else if (state.tab === "all") {
    pageHeader("管理员工作台", "全部订单", `<button class="ghost-btn" type="button" data-refresh>刷新</button>`);
    content.innerHTML = `<div class="panel">
      <div class="panel-head"><h3>订单列表</h3><span>共 ${state.adminOrders.length} 条</span></div>
      ${adminTable(state.adminOrders)}
    </div>`;
  } else {
    content.innerHTML = emptyState("页面不存在", "请从左侧选择功能。");
  }

  bindTabActions();
}

function flowList(flows) {
  if (!flows || !flows.length) return emptyState("还没有流水", "充值或订单签收后，这里会出现记录。");
  return `<div class="flow-list">${flows
    .map((flow) => {
      const amount = Number(flow.amount);
      const cls = amount >= 0 ? "plus" : "minus";
      const sign = amount >= 0 ? "+" : "";
      return `<div class="flow-row">
        <div><div class="flow-name">${esc(formatFlowType(flow.type))}</div><div class="flow-time">${esc(flow.ref)}　${esc(flow.created_at)}</div></div>
        <div class="flow-amount ${cls}">${sign}¥${Math.abs(amount).toFixed(2)}</div>
      </div>`;
    })
    .join("")}</div>`;
}

function creditList(logs) {
  if (!logs || !logs.length) return emptyState("还没有信用变动", "完成一次订单评价后，这里会出现记录。");
  return logs
    .map(
      (log) => `<div class="credit-log">
        <span>${esc(log.reason)} · ${esc(log.ref)}</span>
        <span>${log.change_value > 0 ? "+" : ""}${esc(log.change_value)} 分　${esc(log.created_at)}</span>
      </div>`,
    )
    .join("");
}

function renderStats() {
  const stats = state.stats || {};
  const statuses = stats.orders_by_status || {};
  const totalOrders = Object.values(statuses).reduce((sum, item) => sum + item.count, 0);
  return `<div class="overview-grid">
    <div class="stat-card"><span class="label">注册用户</span><span class="value">${stats.users || 0}</span><span class="hint">学生、骑手和管理员</span></div>
    <div class="stat-card"><span class="label">订单总数</span><span class="value">${totalOrders}</span><span class="hint">全部状态</span></div>
    <div class="stat-card"><span class="label">已支付订单</span><span class="value">${stats.paid_orders || 0}</span><span class="hint">签收后生成支付流水</span></div>
    <div class="stat-card"><span class="label">存证记录</span><span class="value">${stats.chain_records || 0}</span><span class="hint">订单事件哈希链</span></div>
  </div>
  <div class="panel">
    <div class="panel-head"><h3>订单状态分布</h3><span>按状态汇总</span></div>
    ${Object.keys(statuses).length ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>状态</th><th>订单数</th><th>跑腿费合计</th></tr></thead><tbody>
      ${Object.entries(statuses)
        .map(([status, item]) => `<tr><td>${esc((STATUS[status] || { label: status }).label)}</td><td>${item.count}</td><td>¥${esc(item.fee)}</td></tr>`)
        .join("")}
    </tbody></table></div>` : emptyState("还没有订单", "学生发布订单后，这里会出现统计数据。")}
  </div>`;
}

function adminTable(orders) {
  if (!orders || !orders.length) return emptyState("还没有订单", "系统里还没有任何订单。");
  return `<div class="table-wrap"><table class="data-table"><thead><tr><th>订单号</th><th>标题</th><th>路线</th><th>金额</th><th>状态</th><th>创建时间</th><th></th></tr></thead><tbody>
    ${orders
      .map((order) => {
        const info = statusInfo(order);
        return `<tr>
          <td>${esc(order.order_no)}</td>
          <td>${esc(order.title)}</td>
          <td>${esc(order.pickup)} → ${esc(order.dropoff)}</td>
          <td>¥${esc(order.fee)}</td>
          <td><span class="status-pill status-${info.cls}">${esc(info.label)}</span></td>
          <td>${esc(order.created_at)}</td>
          <td><button class="action-btn" type="button" data-open-order="${order.id}">查看</button></td>
        </tr>`;
      })
      .join("")}
  </tbody></table></div>`;
}

function bindTabActions() {
  document.querySelectorAll("[data-go-tab]").forEach((button) => {
    button.addEventListener("click", () => switchTab(button.dataset.goTab));
  });
  document.querySelectorAll("[data-refresh]").forEach((button) => {
    button.addEventListener("click", () => refreshCurrentTab());
  });
  document.querySelectorAll("[data-open-order]").forEach((node) => {
    node.addEventListener("click", () => openOrder(node.dataset.openOrder));
  });
}

async function submitOrder(event) {
  event.preventDefault();
  const errorNode = document.getElementById("publish-error");
  errorNode.textContent = "";
  const button = event.currentTarget.querySelector("button[type=submit]");
  button.disabled = true;
  try {
    await post("/api/orders", {
      title: document.getElementById("order-title").value.trim(),
      pickup: document.getElementById("order-pickup").value.trim(),
      dropoff: document.getElementById("order-dropoff").value.trim(),
      fee: document.getElementById("order-fee").value,
      timeout_minutes: Number(document.getElementById("order-timeout").value),
    });
    showToast("订单已发布，等待骑手接单");
    state.tab = "mine";
    await refreshAll();
  } catch (error) {
    errorNode.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function rechargeWallet(event) {
  event.preventDefault();
  const errorNode = document.getElementById("recharge-error");
  errorNode.textContent = "";
  const button = event.currentTarget.querySelector("button[type=submit]");
  button.disabled = true;
  try {
    const data = await post("/api/wallet/recharge", { amount: document.getElementById("recharge-amount").value });
    showToast(`充值成功，当前余额 ¥${data.wallet}`);
    await refreshCurrentTab();
  } catch (error) {
    errorNode.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

function stepIndex(status) {
  return STEP_KEYS.indexOf(status);
}

function renderSteps(order) {
  if (order.status === "cancelled") {
    return `<div class="route-line">订单已取消，未进入配送流程。</div>`;
  }
  const index = stepIndex(order.status);
  return `<div class="steps">${STEP_KEYS.map((key, i) => `<div class="step ${i <= index ? "done" : ""}">${STEP_LABELS[i]}</div>`).join("")}</div>`;
}

function actionButtons(order) {
  if (!state.user) return "";
  const role = state.user.role;
  const isRequester = order.requester_id === state.user.id;
  const isCourier = order.courier_id === state.user.id;
  const buttons = [];
  if (role === "courier" && order.status === "pending" && !isRequester) {
    buttons.push(`<button class="action-btn solid" type="button" data-order-action="take" data-order-id="${order.id}">接单</button>`);
  }
  if (role === "courier" && isCourier && order.status === "taken") {
    buttons.push(`<button class="action-btn solid" type="button" data-order-action="pickup" data-order-id="${order.id}">确认取件</button>`);
  }
  if (role === "courier" && isCourier && order.status === "delivering") {
    buttons.push(`<button class="action-btn solid" type="button" data-order-action="deliver" data-order-id="${order.id}">标记送达</button>`);
  }
  if (role === "student" && isRequester && order.status === "pending") {
    buttons.push(`<button class="action-btn warn" type="button" data-order-action="cancel" data-order-id="${order.id}">取消订单</button>`);
  }
  if (role === "student" && isRequester && order.status === "delivered") {
    buttons.push(`<button class="action-btn solid" type="button" data-order-action="sign" data-order-id="${order.id}">确认签收并结算</button>`);
  }
  return buttons.join("");
}

function timelineHtml(timeline) {
  const names = {
    created: "发布订单",
    taken: "骑手接单",
    picked: "已取件",
    delivered: "已送达",
    signed: "已签收",
    cancelled: "取消订单",
    reviewed: "订单评价",
  };
  if (!timeline.length) return emptyState("还没有时间线", "订单事件会记录在这里。");
  return timeline
    .map((item) => {
      const payload = item.payload || {};
      return `<div class="timeline-item">
        <div class="timeline-dot"></div>
        <div class="timeline-body">
          <div class="timeline-event">${esc(names[item.event] || item.event)}</div>
          <div class="timeline-meta">${esc(item.created_at)}　${esc(item.record_hash.slice(0, 12))}…</div>
          <div class="timeline-payload">订单号 ${esc(payload.order_no || "")} · 状态 ${esc((STATUS[payload.status] || { label: payload.status }).label || "")} · 金额 ¥${esc(payload.fee || "")}</div>
        </div>
      </div>`;
    })
    .join("");
}

async function openOrder(orderId) {
  const modal = document.getElementById("modal");
  const body = document.getElementById("modal-body");
  modal.classList.remove("hidden");
  body.innerHTML = `<div class="empty"><strong>正在读取订单</strong>请稍候…</div>`;
  try {
    const [order, timeline, verify] = await Promise.all([
      get(`/api/orders/${orderId}`),
      get(`/api/orders/${orderId}/timeline`),
      get(`/api/orders/${orderId}/verify`),
    ]);
    const info = statusInfo(order);
    const buttons = actionButtons(order);
    body.innerHTML = `
      <div class="detail-head">
        <h3>${esc(order.title)}</h3>
        <div class="detail-sub">${esc(order.order_no)}　<span class="status-pill status-${info.cls}">${esc(info.label)}</span></div>
      </div>
      <div class="route-line">${esc(order.pickup)} → ${esc(order.dropoff)}</div>
      <div class="detail-grid">
        <div class="detail-item"><span class="k">跑腿费</span><span class="v">¥${esc(order.fee)}</span></div>
        <div class="detail-item"><span class="k">超时时间</span><span class="v">${esc(order.timeout_minutes)} 分钟</span></div>
        <div class="detail-item"><span class="k">下单人 ID</span><span class="v">${esc(order.requester_id)}</span></div>
        <div class="detail-item"><span class="k">骑手 ID</span><span class="v">${esc(order.courier_id || "待接单")}</span></div>
      </div>
      ${renderSteps(order)}
      ${buttons ? `<div class="action-bar">${buttons}</div>` : ""}
      ${order.status === "signed" && order.requester_id === state.user.id && !order.review_rating ? `
        <div class="panel" style="margin-top:16px;padding:16px;background:#f8fbf9">
          <div class="panel-head"><h3>评价骑手</h3><span>签收后可以评价一次</span></div>
          <div class="form-row">
            <select id="review-rating" style="border:1px solid #d9e2dc;border-radius:9px;padding:9px 10px;background:#fff">
              <option value="5">5 星 · 很好</option><option value="4">4 星 · 不错</option><option value="3">3 星 · 一般</option><option value="2">2 星 · 较差</option><option value="1">1 星 · 很差</option>
            </select>
            <input id="review-comment" maxlength="100" placeholder="补充评价（可不填）" style="border:1px solid #d9e2dc;border-radius:9px;padding:9px 10px;background:#fff;flex:1">
            <button class="action-btn" type="button" data-review-submit="${order.id}">提交评价</button>
          </div>
        </div>` : ""}
      ${order.review_rating ? `<div class="route-line" style="margin-top:12px">已评价 ${esc(order.review_rating)} 星：${esc(order.review_comment || "无补充")}</div>` : ""}
      <div class="timeline">
        <div class="timeline-title"><h4>订单时间线</h4><span class="verify-line">存证校验：${verify.valid ? `<span class="ok">通过（${verify.checked} 条）</span>` : `<span class="bad">未通过（断点 ${verify.broken_at}）</span>`}</span></div>
        ${timelineHtml(timeline)}
      </div>
    `;
    body.querySelectorAll("[data-order-action]").forEach((button) => {
      button.addEventListener("click", () => runOrderAction(button.dataset.orderId, button.dataset.orderAction));
    });
    const reviewButton = body.querySelector("[data-review-submit]");
    if (reviewButton) {
      reviewButton.addEventListener("click", () => {
        const rating = Number(document.getElementById("review-rating").value);
        const comment = document.getElementById("review-comment").value.trim();
        runOrderAction(reviewButton.dataset.reviewSubmit, "review", { rating, comment });
      });
    }
  } catch (error) {
    body.innerHTML = emptyState("订单读取失败", error.message);
  }
}

async function runOrderAction(orderId, action, extra = {}) {
  try {
    await post(`/api/orders/${orderId}/${action}`, extra);
    document.getElementById("modal").classList.add("hidden");
    showToast("操作成功");
    await refreshAll();
  } catch (error) {
    showToast(error.message, true);
  }
}

function bindAuth() {
  document.getElementById("tab-login").addEventListener("click", () => switchAuthTab("login"));
  document.getElementById("tab-register").addEventListener("click", () => switchAuthTab("register"));

  document.getElementById("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const errorNode = document.getElementById("login-error");
    errorNode.textContent = "";
    const button = event.currentTarget.querySelector("button[type=submit]");
    button.disabled = true;
    try {
      const data = await post("/api/login", {
        phone: document.getElementById("login-phone").value.trim(),
        password: document.getElementById("login-password").value,
      });
      setSession(data.token);
      await startApp();
    } catch (error) {
      errorNode.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });

  document.getElementById("register-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const errorNode = document.getElementById("register-error");
    errorNode.textContent = "";
    const button = event.currentTarget.querySelector("button[type=submit]");
    button.disabled = true;
    try {
      const data = await post("/api/register", {
        phone: document.getElementById("register-phone").value.trim(),
        password: document.getElementById("register-password").value,
      });
      setSession(data.token);
      await startApp();
    } catch (error) {
      errorNode.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });

  document.querySelectorAll(".demo-btn").forEach((button) => {
    button.addEventListener("click", async () => {
      const errorNode = document.getElementById("login-error");
      errorNode.textContent = "";
      button.disabled = true;
      try {
        const data = await post("/api/login", {
          phone: button.dataset.phone,
          password: button.dataset.password,
        });
        setSession(data.token);
        await startApp();
      } catch (error) {
        errorNode.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    });
  });

  document.querySelectorAll("[data-close-modal]").forEach((node) => {
    node.addEventListener("click", () => document.getElementById("modal").classList.add("hidden"));
  });
}

function switchAuthTab(tab) {
  const isLogin = tab === "login";
  document.getElementById("tab-login").classList.toggle("active", isLogin);
  document.getElementById("tab-register").classList.toggle("active", !isLogin);
  document.getElementById("login-form").classList.toggle("hidden", !isLogin);
  document.getElementById("register-form").classList.toggle("hidden", isLogin);
}

async function startApp() {
  const user = await get("/api/me");
  state.user = user;
  document.getElementById("login-view").classList.add("hidden");
  document.getElementById("app-view").classList.remove("hidden");
  state.tab = tabsForRole(user.role)[0].id;
  renderUserArea();
  renderSidebar();
  await refreshAll();
}

async function boot() {
  bindAuth();
  if (!state.token) {
    document.getElementById("login-view").classList.remove("hidden");
    return;
  }
  try {
    await startApp();
  } catch (error) {
    clearSession(false);
  }
}

document.addEventListener("DOMContentLoaded", boot);
