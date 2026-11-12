/* JAC Parts — витрина в Telegram. Без сборки и библиотек: экраны рисуются функциями ниже.
   Данные с сервера вставляются только как текст (textContent) — никакого HTML из базы. */
"use strict";

const tg = window.Telegram && window.Telegram.WebApp;
const app = document.getElementById("app");
const footer = document.getElementById("footer");
const tabsEl = document.getElementById("tabs");
const toastEl = document.getElementById("toast");

const state = { me: null, t: {}, cart: 0, catalog: null, stack: [], tab: "catalog", query: "" };

// ---------- значки (свои, статичные; толщину линии задаёт CSS) ----------
const ICON = {
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
  service: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M12 3.5c3 3.6 5.5 6.9 5.5 10a5.5 5.5 0 0 1-11 0c0-3.1 2.5-6.4 5.5-10Z"/></svg>',
  body: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"><path d="M3.5 15.5V12l2.2-4.4A2 2 0 0 1 7.5 6.5h9a2 2 0 0 1 1.8 1.1l2.2 4.4v3.5a1 1 0 0 1-1 1h-15a1 1 0 0 1-1-1Z"/><path d="M3.5 12h17"/><circle cx="7.5" cy="16.5" r="1.8"/><circle cx="16.5" cy="16.5" r="1.8"/></svg>',
  brakes: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="3"/></svg>',
  electric: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M13 2.8 5.5 13.5H11l-1 7.7 7.5-10.7H12l1-7.7Z"/></svg>',
  tools: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"><path d="M14.5 4.2a4.5 4.5 0 0 0 5.3 5.3l-9.6 9.6a2.2 2.2 0 0 1-3.1-3.1l9.6-9.6a4.5 4.5 0 0 1-2.2-2.2Z"/></svg>',
  other: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M12 3 20 7.5v9L12 21l-8-4.5v-9L12 3Z"/><path d="m4 7.5 8 4.5 8-4.5M12 12v9"/></svg>',
  catalog: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linejoin="round"><rect x="4" y="4" width="6.5" height="6.5" rx="1"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1"/></svg>',
  cart: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linejoin="round" stroke-linecap="round"><path d="M5 8h14l-1.2 11.1a1 1 0 0 1-1 .9H7.2a1 1 0 0 1-1-.9L5 8Z"/><path d="M9 10.5V7a3 3 0 0 1 6 0v3.5"/></svg>',
  orders: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linejoin="round" stroke-linecap="round"><path d="M6 3.5h12v17l-3-2-3 2-3-2-3 2v-17Z"/><path d="M9 8.5h6M9 12.5h6"/></svg>',
  profile: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linejoin="round" stroke-linecap="round"><circle cx="12" cy="8.5" r="3.8"/><path d="M4.8 20c.9-3.6 3.8-5.8 7.2-5.8s6.3 2.2 7.2 5.8"/></svg>',
  camera: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"><path d="M3.5 8.5a1.5 1.5 0 0 1 1.5-1.5h2.6l1.6-2.2h5.6L16.4 7H19a1.5 1.5 0 0 1 1.5 1.5v9.5A1.5 1.5 0 0 1 19 19.5H5A1.5 1.5 0 0 1 3.5 18V8.5Z"/><circle cx="12" cy="13" r="3.6"/></svg>',
  chev: '<svg viewBox="0 0 8 13" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="m1.5 1.5 5 5-5 5"/></svg>',
};

// ---------- помощники ----------
function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "html") el.innerHTML = v; // только наши статичные значки из ICON
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
const icon = (name) => h("span", { html: ICON[name] || ICON.other, "aria-hidden": "true" });

function t(key, params) {
  let s = state.t[key] || key;
  for (const [k, v] of Object.entries(params || {})) s = s.split(`{${k}}`).join(v);
  return s;
}

function haptic(kind) {
  try {
    if (kind === "tap") tg.HapticFeedback.selectionChanged();
    else tg.HapticFeedback.notificationOccurred(kind);
  } catch (e) { /* не в Telegram или старая версия */ }
}

let toastTimer;
function toast(text, ms) {
  toastEl.textContent = text;
  toastEl.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toastEl.hidden = true; }, ms || 2200);
}

class ApiError extends Error {
  constructor(code, data) { super(code); this.code = code; this.data = data; }
}

async function api(path, body) {
  let res;
  const form = body instanceof FormData; // фото уходит как файл, остальное — JSON
  try {
    res = await fetch(path, {
      method: body ? "POST" : "GET",
      headers: { "X-Telegram-Init-Data": tg.initData, ...(body && !form ? { "Content-Type": "application/json" } : {}) },
      body: body ? (form ? body : JSON.stringify(body)) : undefined,
    });
  } catch (e) { throw new ApiError("network"); }
  const data = await res.json().catch(() => ({}));
  if (res.status === 409) throw new ApiError("conflict", data);
  if (!res.ok) throw new ApiError(res.status === 401 ? "expired" : data.error || "error", data);
  return data;
}

/* Серая подложка: фото детали (если задано в панели) или её схематичный рисунок (pics.js) */
const CATEGORY_PIC = { service: "oil_filter", body: "door", brakes: "brake_disc", electric: "headlamp", tools: "tools", other: "part" };
const PICS = window.PICS || {};

function picture(key) {
  const inner = PICS[key] || PICS.part;
  return inner ? `<svg class="pic" viewBox="0 0 120 90" aria-hidden="true">${inner}</svg>` : ICON.other; // свои статичные рисунки
}

function shot(photo, pic, cls) {
  const box = h("div", { class: "shot" + (cls ? " " + cls : ""), html: picture(pic) });
  if (photo) {
    const img = h("img", { src: photo, alt: "", loading: "lazy" });
    img.addEventListener("load", () => { box.querySelector("svg")?.remove(); });
    img.addEventListener("error", () => img.remove());
    box.append(img);
  }
  return box;
}

function statusEl(item) {
  if (item.status === "stock") return h("div", { class: "status stock" }, t("in_stock"));
  if (item.status === "preorder") return h("div", { class: "status preorder" }, t("preorder_short", { days: item.days }));
  return h("div", { class: "status" }, t("not_here"));
}

// ---------- навигация: экраны в стеке, кнопка «Назад» Telegram ----------
const screens = {};

function show(name, params, opts) {
  if (opts && opts.root) state.stack = [];
  state.stack.push({ name, params: params || {} });
  render();
}

function back() {
  if (state.stack.length > 1) {
    state.stack.pop();
    render();
  }
}

function setTab(tab) {
  state.tab = tab;
  haptic("tap");
  show(tab === "catalog" ? "home" : tab, {}, { root: true });
}

async function render() {
  const current = state.stack[state.stack.length - 1];
  const screen = screens[current.name];
  toastEl.hidden = true;
  setFooter();
  renderTabs();
  if (state.stack.length > 1) tg.BackButton.show(); else tg.BackButton.hide();
  app.replaceChildren(h("div", { class: "skeleton" }), h("div", { class: "skeleton" }));
  try {
    const node = await screen.draw(current.params);
    if (state.stack[state.stack.length - 1] !== current) return; // пока грузили, ушли на другой экран
    app.replaceChildren(node);
    window.scrollTo(0, 0);
  } catch (e) {
    app.replaceChildren(errorView(e));
  }
}

function setFooter(...nodes) {
  footer.replaceChildren(...nodes);
  document.body.classList.toggle("with-footer", nodes.length > 0);
}

function renderTabs() {
  const items = [["catalog", "tab_catalog"], ["cart", "tab_cart"], ["orders", "tab_orders"], ["profile", "tab_profile"]];
  tabsEl.hidden = false;
  tabsEl.replaceChildren(...items.map(([key, label]) => {
    const btn = h("button", { type: "button", "aria-current": state.tab === key ? "page" : null, onclick: () => setTab(key) },
      icon(key), t(label));
    if (key === "cart" && state.cart > 0) btn.append(h("span", { class: "badge" }, state.cart));
    return btn;
  }));
}

function setCart(n) {
  state.cart = n;
  renderTabs();
}

function errorView(e) {
  const code = e && e.code;
  const key = { register: "register", blocked: "blocked", expired: "expired" }[code] || "error";
  const retry = key === "error";
  return h("div", { class: "empty" },
    h("p", {}, t(key)),
    h("button", { class: "cta ghost", type: "button", onclick: () => (retry ? render() : tg.close()) },
      retry ? t("retry") : t("close")));
}

function emptyView(title, text, action) {
  return h("div", { class: "empty" },
    h("h2", {}, title),
    text ? h("p", {}, text) : null,
    action ? h("button", { class: "cta ghost", type: "button", onclick: action[1] }, action[0]) : null);
}

// ---------- каталог ----------
screens.home = {
  async draw() {
    if (!state.catalog) state.catalog = await api("/api/catalog");
    const me = state.me;
    const root = h("div", {},
      h("header", { class: "hero" },
        h("h1", {}, me.full ? t("all_models") : (me.car_model || me.car || "JAC")),
        h("p", {}, t("hero_sub", { region: me.region }))));
    if (me.car_photo) root.append(h("img", { class: "hero-photo", src: me.car_photo, alt: me.car_model || "" }));

    const results = h("div", {});
    const categories = h("div", {});
    const input = h("input", { type: "text", inputmode: "search", placeholder: t("search"), value: state.query,
      enterkeyhint: "search", autocomplete: "off", "aria-label": t("search") });
    const clear = h("button", { class: "clear", type: "button", hidden: !state.query }, t("clear"));
    root.append(h("div", { class: "search" }, h("label", {}, icon("search"), input, clear)), results, categories);

    let timer;
    const run = async () => {
      const q = input.value.trim();
      state.query = q;
      clear.hidden = !q;
      categories.hidden = q.length >= 2;
      if (q.length < 2) { results.replaceChildren(); return; }
      try {
        const data = await api("/api/search?q=" + encodeURIComponent(q));
        if (input.value.trim() !== q) return;
        results.replaceChildren(resultsView(data));
      } catch (e) { results.replaceChildren(errorView(e)); }
    };
    input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 300); });
    input.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { input.blur(); run(); } });
    clear.addEventListener("click", () => { input.value = ""; run(); input.focus(); });

    const models = state.catalog.models;
    if (!models.length) categories.append(emptyView(me.car ? t("empty_region") : t("no_car")));
    for (const model of models) {
      categories.append(
        model.other ? h("h2", { class: "section" }, model.name, h("small", {}, t("other_hint")))
          : h("h2", { class: "section" }, model.mine ? t("categories") : model.name),
        h("div", { class: "tiles" }, model.nodes.map((node) =>
          h("button", { class: "tile", type: "button", onclick: () => show("parts", { model, node }) },
            shot(null, CATEGORY_PIC[node.icon] || "part"),
            h("div", { class: "label" }, node.name),
            h("div", { class: "count" }, t("parts_n", { n: node.count }))))));
    }
    if (state.query.length >= 2) run();
    return root;
  },
};

function resultsView(data) {
  if (!data.items.length) {
    return h("div", { class: "empty inline-empty" }, h("h2", {}, t("nothing", { q: data.q })), h("p", {}, t("nothing_hint")));
  }
  return h("div", {}, h("h2", { class: "section" }, t("results", { n: data.items.length })), productGrid(data.items));
}

function productGrid(items) {
  return h("div", { class: "grid" }, items.map((item) =>
    h("button", { class: "product", type: "button", onclick: () => show("part", { id: item.id }) },
      shot(item.photo, item.pic),
      h("div", { class: "pname" }, item.name),
      h("div", { class: "pnum" }, item.number),
      item.price ? h("div", { class: "pprice" }, item.status === "stock" && item.dealers > 1
        ? t("from", { price: item.price }) : item.price) : null,
      statusEl(item))));
}

screens.parts = {
  async draw({ model, node }) {
    const data = await api(`/api/parts?model_id=${model.id}&node_id=${node.id}`);
    const grid = productGrid(data.items);
    const root = h("div", {},
      h("header", { class: "page-title" }, h("h1", {}, node.name), h("p", {}, model.name)), grid);
    let offset = data.items.length;
    if (offset < data.total) {
      const more = h("button", { class: "cta ghost more", type: "button" }, t("more"));
      more.addEventListener("click", async () => {
        more.disabled = true;
        const next = await api(`/api/parts?model_id=${model.id}&node_id=${node.id}&offset=${offset}`);
        offset += next.items.length;
        for (const el of [...productGrid(next.items).children]) grid.append(el);
        more.disabled = false;
        if (offset >= next.total) more.remove();
      });
      root.append(more);
    }
    return root;
  },
};

// ---------- карточка детали: выбор дилера, как выбор комплектации ----------
screens.part = {
  async draw({ id }) {
    const p = await api(`/api/part/${id}`);
    const root = h("div", {},
      shot(p.photo, p.pic, "part-shot"),
      h("header", { class: "part-head" },
        h("h1", {}, p.name),
        h("div", { class: "sub" }, `${p.model}, ${p.node}`),
        p.offers.length || p.preorder ? h("div", { class: "price" },
          p.offers.length ? p.offers[0].price : p.preorder.price) : null,
        h("div", { class: "num" }, `${t("number")} ${p.number}`)),
      p.description ? h("p", { class: "part-desc" }, p.description) : null);

    if (p.offers.length) root.append(...stockOptions(p));
    else if (p.preorder) root.append(...preorderOptions(p));
    else {
      root.append(h("h2", { class: "section" }, t("not_here")),
        p.elsewhere ? h("p", { class: "lead" }, t("elsewhere", { n: p.elsewhere })) : null);
    }
    return root;
  },
};

function dealerLinks(dealer) {
  if (!dealer.map && !dealer.phone) return null;
  return h("div", { class: "olinks" },
    dealer.map ? h("a", { href: dealer.map, onclick: (ev) => { ev.preventDefault(); ev.stopPropagation(); openLink(dealer.map); } },
      t("route")) : null,
    dealer.phone ? h("a", { href: "tel:" + dealer.phone.replace(/[^\d+]/g, ""), onclick: (ev) => ev.stopPropagation() },
      t("call")) : null);
}

function openLink(url) {
  try { tg.openLink(url); } catch (e) { window.open(url, "_blank", "noopener"); }
}

/* Список выбора: одна рамка — один вариант; выбранный обведён синим */
function optionList(items, chosenKey, onPick) {
  const buttons = items.map((it) => {
    const btn = h("button", { class: "option", type: "button", role: "radio", "aria-checked": String(it.key === chosenKey) },
      it.photo !== undefined ? carMedia(it.photo, "ophoto") : null,
      h("div", { class: "top" },
        h("span", { class: "oname" }, it.hex ? h("span", { class: "swatch", "data-hex": it.hex }) : null, it.title),
        it.price ? h("span", { class: "oprice" }, it.price) : null),
      it.address ? h("div", { class: "oaddr" }, it.address) : null,
      it.meta ? h("div", { class: "ometa" }, it.meta) : null,
      dealerLinks(it.dealer));
    btn.addEventListener("click", () => {
      haptic("tap");
      for (const b of buttons) b.setAttribute("aria-checked", String(b === btn));
      onPick(it);
    });
    return btn;
  });
  return h("div", { class: "options" + (items.some((it) => it.photo !== undefined) ? " cars" : ""), role: "radiogroup" }, buttons);
}

/* Фото модели JAC (если есть) или схематичная машина */
function carMedia(photo, cls) {
  if (!photo) return h("div", { class: cls, html: picture("car") });
  return h("div", { class: cls }, h("img", { src: photo, alt: "", loading: "lazy" }));
}

function stockOptions(p) {
  let chosen = p.offers[0];
  const items = p.offers.map((o) => ({ key: o.stock_id, title: o.dealer.name, address: o.dealer.address, price: o.price,
    meta: t("in_stock_qty", { n: o.qty }), dealer: o.dealer, offer: o }));
  const cta = cartButton(() => chosen.in_cart, () => ({ stock_id: chosen.stock_id }), (qty) => { chosen.in_cart = qty; });
  setFooter(cta.el);
  return [h("h2", { class: "section" }, t("where_buy")),
    optionList(items, chosen.stock_id, (it) => { chosen = it.offer; cta.paint(); })];
}

function preorderOptions(p) {
  const pre = p.preorder;
  let chosen = pre.dealers.length === 1 ? pre.dealers[0].id : null;
  const items = pre.dealers.map((d) => ({ key: d.id, title: d.name, address: d.address, dealer: d }));
  const cta = cartButton(() => pre.in_cart, () => chosen && { stock_id: pre.stock_id, dealer_id: chosen },
    (qty) => { pre.in_cart = qty; });
  setFooter(cta.el);
  return [h("h2", { class: "section" }, t("preorder_title"), h("small", {}, t("preorder_note", { days: pre.days }))),
    h("p", { class: "lead" }, t("pickup")),
    optionList(items, chosen, (it) => { chosen = it.key; cta.paint(); })];
}

/* Главная кнопка: «Добавить в корзину»; уже добавили — «Перейти в корзину» */
function cartButton(inCart, payload, onAdded) {
  const el = h("button", { class: "cta", type: "button" });
  const paint = () => {
    el.textContent = inCart() ? t("go_cart") : t("add");
    el.disabled = !inCart() && !payload();
  };
  el.addEventListener("click", async () => {
    if (inCart()) { setTab("cart"); return; }
    const body = payload();
    if (!body) return;
    el.disabled = true;
    try {
      const res = await api("/api/cart/add", { dealer_id: null, ...body });
      if (res.ok) {
        haptic("success");
        setCart(res.cart);
        onAdded(res.qty);
        toast(t("added"));
      } else {
        haptic("error");
        toast(t("limit"));
      }
    } catch (e) { haptic("error"); toast(t("error")); }
    paint();
  });
  paint();
  return { el, paint };
}

// ---------- корзина ----------
screens.cart = {
  async draw() {
    const data = await api("/api/cart");
    setCart(data.count);
    return cartView(data);
  },
};

function cartView(data) {
  if (!data.items.length) {
    return emptyView(t("cart_empty"), t("cart_empty_hint"), [t("continue"), () => setTab("catalog")]);
  }
  const update = async (path, body) => {
    try {
      const fresh = await api(path, body);
      if (path.endsWith("change") && !fresh.ok) { haptic("error"); toast(t("limit")); } else haptic("tap");
      setCart(fresh.count);
      const top = window.scrollY;
      app.replaceChildren(cartView(fresh));
      window.scrollTo(0, top);
    } catch (e) { toast(t("error")); }
  };
  const root = h("div", {}, h("header", { class: "page-title" }, h("h1", {}, t("tab_cart"))));
  root.append(h("div", { class: "lines" }, data.items.map((item) =>
    h("div", { class: "line" },
      shot(item.photo, item.pic),
      h("div", {},
        h("div", { class: "lname" }, item.name),
        h("div", { class: "lnum" }, item.number),
        h("div", { class: "where" }, item.preorder ? `${t("preorder_short", { days: item.days })}, ${item.dealer}` : item.dealer),
        !item.available ? h("div", { class: "warn" }, t("unavailable"))
          : item.qty > item.max ? h("div", { class: "warn" }, t("only_n", { n: item.max })) : null,
        h("div", { class: "row" },
          h("span", { class: "qty" },
            h("button", { type: "button", "aria-label": item.qty > 1 ? "−1" : t("remove"),
              onclick: () => update("/api/cart/change", { item_id: item.id, delta: -1 }) }, "−"),
            h("span", {}, item.qty),
            h("button", { type: "button", "aria-label": "+1", disabled: item.qty >= item.max || !item.available,
              onclick: () => update("/api/cart/change", { item_id: item.id, delta: 1 }) }, "+")),
          h("span", { class: "lprice" }, item.available ? item.subtotal : item.price)))))));
  root.append(h("div", { class: "summary" },
    h("div", { class: "stotal" }, h("span", {}, t("total")), h("span", {}, data.total)),
    data.orders > 1 ? h("p", { class: "note" }, t("split", { n: data.orders })) : null));
  const cta = h("button", { class: "cta", type: "button", disabled: !data.orders }, t("checkout"));
  cta.addEventListener("click", () => confirmCheckout(data, cta));
  setFooter(cta);
  return root;
}

function confirmCheckout(data, cta) {
  const text = t("confirm", { total: data.total, phone: data.phone || "" });
  const go = async (ok) => {
    if (!ok) return;
    cta.disabled = true;
    try {
      const res = await api("/api/checkout", {});
      haptic("success");
      setCart(0);
      state.tab = "orders";
      show("done", { orders: res.orders }, { root: true });
    } catch (e) {
      cta.disabled = false;
      if (e.code === "conflict" && e.data && e.data.problems) {
        haptic("error");
        const after = () => render();
        try { tg.showAlert(e.data.problems, after); } catch (x) { window.alert(e.data.problems); after(); }
      } else toast(t("error"));
    }
  };
  try { tg.showConfirm(text, go); } catch (e) { go(window.confirm(text)); }
}

screens.done = {
  async draw({ orders }) {
    setFooter(h("button", { class: "cta ghost", type: "button", onclick: () => setTab("orders") }, t("my_orders")));
    return h("div", { class: "empty" },
      h("h2", {}, orders.length > 1 ? t("done_many", { n: orders.length }) : t("done")),
      h("div", { class: "nums" }, orders.map((o) => t("order_n", { id: o.id })).join(", ")),
      h("p", {}, t("done_hint")));
  },
};

// ---------- заказы ----------
screens.orders = {
  async draw() {
    const data = await api("/api/orders");
    if (!data.orders.length) {
      return emptyView(t("orders_empty"), t("cart_empty_hint"), [t("continue"), () => setTab("catalog")]);
    }
    return h("div", {},
      h("header", { class: "page-title" }, h("h1", {}, t("tab_orders"))),
      h("div", { class: "orders" }, data.orders.map(orderView)));
  },
};

function orderView(o) {
  const items = o.items.map((i) => (i.qty > 1 ? `${i.name} × ${i.qty}` : i.name)).join(", ");
  const finished = o.status === "COMPLETED" || o.status === "CANCELLED";
  const d = o.dealer;
  return h("div", { class: "order" },
    h("div", { class: "head" }, h("span", { class: "num" }, t("order_n", { id: o.id })), h("span", { class: "total" }, o.total)),
    h("div", { class: "when" }, o.date),
    h("div", { class: "what" }, items),
    o.steps.length ? h("div", { class: "track", "aria-hidden": "true" }, o.steps.map((s) => h("i", { class: s.state }))) : null,
    h("div", { class: "now" }, o.status_text.replace(/^\S+\s/, "")), // без эмодзи-кружка: статус и так виден на шкале
    o.preorder && !finished ? h("div", { class: "status preorder" }, t("preorder_short", { days: o.days })) : null,
    !finished ? h("div", { class: "pickup" },
      h("b", {}, d.name), d.address || null,
      d.map || d.phone ? h("div", {},
        d.map ? h("a", { href: d.map, onclick: (ev) => { ev.preventDefault(); openLink(d.map); } }, t("route")) : null,
        d.phone ? h("a", { href: "tel:" + d.phone.replace(/[^\d+]/g, "") }, t("call")) : null) : null) : null);
}

// ---------- профиль: то же, что «👤 Профиль» в боте ----------
async function refreshMe() {
  state.me = await api("/api/me");
  state.t = state.me.t;
  state.cart = state.me.cart;
  state.catalog = null; // язык, регион или автомобиль поменялись — каталог другой
  document.documentElement.lang = state.me.lang;
}

/* +998901112233 → +998 90 111 22 33 (узбекские номера), остальные — как есть */
function phoneText(phone) {
  const m = /^\+998(\d{2})(\d{3})(\d{2})(\d{2})$/.exec(phone || "");
  return m ? `+998 ${m[1]} ${m[2]} ${m[3]} ${m[4]}` : phone || "";
}

function settingRow(label, value, onClick, extra) {
  return h("button", { class: "setting", type: "button", onclick: onClick },
    h("span", { class: "slabel" }, label, extra ? h("small", {}, extra) : null),
    value ? h("span", { class: "svalue" }, value) : null,
    icon("chev"));
}

screens.profile = {
  async draw() {
    const p = await api("/api/profile");
    const root = h("div", {},
      h("header", { class: "page-title" }, h("h1", {}, p.name || t("tab_profile")), h("p", {}, phoneText(p.phone))));
    if (p.staff_dealer) root.append(h("p", { class: "lead" }, t("staff_of", { dealer: p.staff_dealer })));
    if (!p.staff_dealer) {
      const car = p.car;
      root.append(h("h2", { class: "section" }, t("car")),
        h("button", { class: "car-card", type: "button", onclick: () => show("pickModel", { current: car && car.model }) },
          carMedia(car && car.photo, "car-pic"),
          h("div", { class: "car-info" },
            h("div", { class: "car-model" }, car ? car.model : t("choose_car")),
            car ? h("div", { class: "car-meta" },
              car.hex ? h("span", { class: "swatch small", "data-hex": car.hex }) : null,
              [car.mod_name, car.color_name].filter(Boolean).join(", ")) : null,
            h("div", { class: "car-change" }, car ? t("change") : t("choose_car")))),
        h("div", { class: "settings vin-row" },
          settingRow(t("vin"), p.vin ? h("span", { class: "vin-value" }, p.vin) : h("span", { class: "accent" }, t("vin_add")),
            () => show("vin", { vin: p.vin }))));
    }
    root.append(h("h2", { class: "section" }, t("settings")),
      h("div", { class: "settings" },
        settingRow(t("region"), p.region.name, () => show("pickRegion", { current: p.region.id })),
        settingRow(t("language"), (p.languages.find((l) => l.code === p.lang) || {}).name, () => show("pickLanguage", { p })),
        settingRow(t("phone"), phoneText(p.phone) || "—", sharePhone)),
      h("h2", { class: "section" }, t("help")),
      h("div", { class: "settings" }, settingRow(t("support"), null, () => tg.close(), t("support_hint"))));
    paintSwatches(root);
    return root;
  },
};

/* Цвет машины задаём через style из своего справочника (не из HTML) */
function paintSwatches(root) {
  for (const el of root.querySelectorAll("[data-hex]")) el.style.background = el.dataset.hex;
}

function sharePhone() {
  // Номер берёт сам Telegram и отправляет боту контактом — бот проверяет, что номер свой, и сохраняет
  if (!tg.requestContact || !tg.isVersionAtLeast || !tg.isVersionAtLeast("6.9")) { toast(t("phone_old")); return; }
  tg.requestContact((shared) => {
    if (!shared) return;
    toast(t("phone_sent"));
    setTimeout(() => { if (state.stack.at(-1)?.name === "profile") render(); }, 2500);
  });
}

async function saveProfile(path, body) {
  try {
    await api(path, body);
    await refreshMe();
    haptic("success");
    state.tab = "profile";
    show("profile", {}, { root: true });
    toast(t("saved"));
  } catch (e) { haptic("error"); toast(t("error")); }
}

function pickScreen(title, note, items, chosenKey, onPick) {
  return h("div", {},
    h("header", { class: "page-title" }, h("h1", {}, title), note ? h("p", {}, note) : null),
    optionList(items, chosenKey, onPick));
}

screens.pickRegion = {
  async draw({ current }) {
    const data = await api("/api/regions");
    return pickScreen(t("region"), t("region_note"), data.regions.map((r) => ({ key: r.id, title: r.name, dealer: {} })), current,
      (it) => saveProfile("/api/profile/region", { region_id: it.key }));
  },
};

screens.pickLanguage = {
  async draw({ p }) {
    return pickScreen(t("language"), null, p.languages.map((l) => ({ key: l.code, title: l.name, dealer: {} })), p.lang,
      (it) => saveProfile("/api/profile/language", { code: it.key }));
  },
};

// автомобиль: модель → комплектация (если их несколько) → цвет
screens.pickModel = {
  async draw({ current }) {
    const data = await api("/api/cars");
    return pickScreen(t("choose_model"), t("car_note"),
      data.cars.map((c) => ({ key: c.model, title: c.model, photo: c.photo, dealer: {} })),
      current, (it) => {
        const car = data.cars.find((c) => c.model === it.key);
        if (car.mods.length > 1) show("pickMod", { car });
        else show("pickColor", { car, mod: "" });
      });
  },
};

screens.pickMod = {
  async draw({ car }) {
    return pickScreen(car.model, t("choose_mod"),
      car.mods.map((m) => ({ key: m.key, title: m.name, photo: m.photo, dealer: {} })), null,
      (it) => show("pickColor", { car, mod: it.key }));
  },
};

screens.pickColor = {
  async draw({ car, mod }) {
    const colors = car.colors[mod] || [];
    const modName = (car.mods.find((m) => m.key === mod) || {}).name;
    const root = pickScreen(car.model, [modName, t("choose_color")].filter(Boolean).join(". "),
      colors.map((c) => ({ key: c.key, title: c.name, hex: c.hex, dealer: {} })), null,
      (it) => saveProfile("/api/profile/car", { model: car.model, mod: mod || null, color: it.key }));
    const photo = (car.mods.find((m) => m.key === mod) || {}).photo || car.photo;
    if (photo) root.insertBefore(h("img", { class: "color-photo", src: photo.replace("-s.webp", ".webp"), alt: "" }), root.children[1]);
    paintSwatches(root);
    return root;
  },
};

// ---------- VIN: фото номера → сервер читает → клиент сверяет и сохраняет ----------
const VIN_OK = /^[A-HJ-NPR-Z0-9]{13}[0-9]{4}$/;

/* Как на сервере: заглавные, без пробелов; I → 1, O и Q → 0 (этих букв в VIN не бывает) */
function vinClean(text) {
  return (text || "").toUpperCase().replace(/I/g, "1").replace(/[OQ]/g, "0").replace(/[^A-Z0-9]/g, "").slice(0, 17);
}

/* Снимок с камеры — до 2000 px по большей стороне и JPEG: грузится за секунду, номер читается так же */
async function shrinkPhoto(file) {
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    const k = Math.min(1, 2000 / Math.max(img.naturalWidth, img.naturalHeight));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(img.naturalWidth * k);
    canvas.height = Math.round(img.naturalHeight * k);
    canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
    return (await new Promise((done) => canvas.toBlob(done, "image/jpeg", 0.9))) || file;
  } catch (e) {
    return file; // не смогли уменьшить — отправим как есть (сервер примет до 10 МБ)
  } finally {
    URL.revokeObjectURL(url);
  }
}

screens.vin = {
  async draw({ vin }) {
    const saved = vin || "";
    const input = h("input", { id: "vin-input", class: "vin-input", type: "text", maxlength: "20", autocomplete: "off",
      autocapitalize: "characters", autocorrect: "off", spellcheck: "false", enterkeyhint: "done",
      placeholder: t("vin_placeholder"), "aria-describedby": "vin-help" });
    input.value = saved;
    const count = h("span", { class: "vin-count", "aria-hidden": "true" });
    const help = h("p", { class: "vin-help", id: "vin-help" });
    const status = h("p", { class: "vin-status", role: "status" });
    const shot = h("div", { class: "vin-shot", hidden: true });
    const save = h("button", { class: "cta", type: "button", onclick: () => saveVin(input.value) }, t("save"));

    function refresh() {
      const v = input.value;
      const ok = VIN_OK.test(v);
      count.textContent = `${v.length}/17`;
      help.textContent = v.length === 17 && !ok ? t("vin_bad") : t("vin_where");
      help.classList.toggle("bad", v.length === 17 && !ok);
      save.disabled = !ok || v === saved;
    }
    input.addEventListener("input", () => {
      const clean = vinClean(input.value);
      if (clean !== input.value) {
        const pos = Math.min(clean.length, input.selectionStart || clean.length);
        input.value = clean;
        input.setSelectionRange(pos, pos);
      }
      status.textContent = "";
      refresh();
    });
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") input.blur(); });

    async function scan(file) {
      if (!file) return;
      const blob = await shrinkPhoto(file);
      shot.replaceChildren(); // фото показываем, пока сервер читает номер, — видно, что сняли
      const url = URL.createObjectURL(blob);
      const img = h("img", { src: url, alt: "" });
      img.addEventListener("load", () => URL.revokeObjectURL(url), { once: true });
      shot.append(img);
      shot.hidden = false;
      shot.classList.add("busy");
      status.className = "vin-status";
      status.textContent = t("vin_scanning");
      const form = new FormData();
      form.append("photo", blob, "vin.jpg");
      try {
        const r = await api("/api/vin/scan", form);
        if (r.vin) {
          input.value = r.vin;
          status.className = r.check_ok ? "vin-status ok" : "vin-status warn";
          status.textContent = r.check_ok ? t("vin_found") : t("vin_found_check");
          haptic(r.check_ok ? "success" : "warning");
        } else {
          status.className = "vin-status warn";
          status.textContent = t("vin_not_found");
          haptic("error");
        }
      } catch (e) {
        status.className = "vin-status warn";
        status.textContent = e.code === "too_many" ? t("vin_too_many") : e.code === "expired" ? t("error") : t("vin_scan_error");
        haptic("error");
      } finally {
        shot.classList.remove("busy");
        refresh();
      }
    }

    // два поля выбора файла: камера сразу (capture) и галерея — если техпаспорт уже сфотографирован
    const camera = h("input", { type: "file", accept: "image/*", capture: "environment", hidden: true });
    const gallery = h("input", { type: "file", accept: "image/*", hidden: true });
    for (const el of [camera, gallery]) {
      el.addEventListener("change", () => { const f = el.files[0]; el.value = ""; scan(f); });
    }

    refresh();
    setFooter(save);
    return h("div", { class: "vin" },
      h("header", { class: "page-title" }, h("h1", {}, t("vin_title")), h("p", {}, t("vin_why"))),
      h("button", { class: "vin-scan", type: "button", onclick: () => camera.click() },
        icon("camera"),
        h("span", {}, h("b", {}, t("vin_scan")), h("small", {}, t("vin_scan_hint")))),
      h("button", { class: "link", type: "button", onclick: () => gallery.click() }, t("vin_gallery")),
      camera, gallery, shot, status,
      h("label", { class: "vin-label", for: "vin-input" }, t("vin_or")),
      h("div", { class: "vin-field" }, input, count),
      help,
      saved ? h("button", { class: "link danger", type: "button", onclick: () => saveVin("") }, t("vin_remove")) : null);
  },
};

async function saveVin(value) {
  try {
    const p = await api("/api/profile/vin", { vin: value });
    haptic(!value || p.vin_check ? "success" : "warning");
    state.tab = "profile";
    show("profile", {}, { root: true });
    if (!value) toast(t("vin_removed"));
    else if (p.vin_check) toast(t("saved"));
    else toast(t("vin_check_warn"), 5000); // номер возможен, но контрольная цифра не сошлась — пусть сверит ещё раз
  } catch (e) {
    haptic("error");
    toast(e.code === "bad_vin" ? t("vin_bad") : t("error"));
  }
}

// ---------- запуск ----------
function applyScheme() {
  const dark = tg && tg.colorScheme === "dark";
  document.documentElement.dataset.scheme = dark ? "dark" : "light";
  const color = dark ? "#171a20" : "#ffffff"; // шапка и фон Telegram — в цвет страницы
  try { tg.setHeaderColor(color); tg.setBackgroundColor(color); tg.setBottomBarColor(color); } catch (e) { /* старые версии */ }
}

async function start() {
  if (!tg || !tg.initData) { // открыли в обычном браузере
    app.replaceChildren(h("div", { class: "empty" },
      h("h2", {}, "JAC Parts"),
      h("p", {}, "Откройте витрину из Telegram-бота. Do‘konni Telegram-botdan oching. Open the shop from the Telegram bot.")));
    return;
  }
  tg.ready();
  tg.expand();
  applyScheme();
  tg.onEvent("themeChanged", applyScheme);
  tg.BackButton.onClick(back);
  try {
    state.me = await api("/api/me");
  } catch (e) {
    app.replaceChildren(errorView(e));
    return;
  }
  state.t = state.me.t;
  state.cart = state.me.cart;
  document.documentElement.lang = state.me.lang;
  show("home", {}, { root: true });
}

start();
