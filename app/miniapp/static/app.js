/* JAC Parts — витрина в Telegram. Без сборки и библиотек: экраны рисуются функциями ниже.
   Данные с сервера вставляются только как текст (textContent) — никакого HTML из базы. */
"use strict";

const tg = window.Telegram && window.Telegram.WebApp;
const app = document.getElementById("app");
const footer = document.getElementById("footer");
const tabsEl = document.getElementById("tabs");
const toastEl = document.getElementById("toast");

const state = { me: null, t: {}, cart: 0, catalog: null, stack: [], tab: "catalog", query: "" };

// ---------- значки (свои, статичные) ----------
const ICON = {
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
  chev: '<svg class="chev" viewBox="0 0 8 13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m1.5 1.5 5 5-5 5"/></svg>',
  service: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M12 3.5c3 3.6 5.5 6.9 5.5 10a5.5 5.5 0 0 1-11 0c0-3.1 2.5-6.4 5.5-10Z"/><path d="M9.5 14.5a2.5 2.5 0 0 0 2.5 2.5"/></svg>',
  body: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"><path d="M3.5 15.5V12l2.2-4.4A2 2 0 0 1 7.5 6.5h9a2 2 0 0 1 1.8 1.1l2.2 4.4v3.5a1 1 0 0 1-1 1h-15a1 1 0 0 1-1-1Z"/><path d="M3.5 12h17"/><circle cx="7.5" cy="16.5" r="1.8"/><circle cx="16.5" cy="16.5" r="1.8"/></svg>',
  brakes: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="3"/><circle cx="12" cy="6.5" r=".9" fill="currentColor"/><circle cx="17.2" cy="13.7" r=".9" fill="currentColor"/><circle cx="6.8" cy="13.7" r=".9" fill="currentColor"/></svg>',
  electric: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M13 2.8 5.5 13.5H11l-1 7.7 7.5-10.7H12l1-7.7Z"/></svg>',
  tools: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"><path d="M14.5 4.2a4.5 4.5 0 0 0 5.3 5.3l-9.6 9.6a2.2 2.2 0 0 1-3.1-3.1l9.6-9.6a4.5 4.5 0 0 1-2.2-2.2Z"/><path d="m16.8 7.2 2.6-2.6"/></svg>',
  other: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M12 3 20 7.5v9L12 21l-8-4.5v-9L12 3Z"/><path d="m4 7.5 8 4.5 8-4.5M12 12v9"/></svg>',
  plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
  route: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M12 21s-6.5-6-6.5-11a6.5 6.5 0 0 1 13 0c0 5-6.5 11-6.5 11Z"/><circle cx="12" cy="10" r="2.3"/></svg>',
  call: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M5 4h3.5l1.7 4.3-2.2 1.4a11 11 0 0 0 6.3 6.3l1.4-2.2L20 15.5V19a1 1 0 0 1-1 1A16 16 0 0 1 4 5a1 1 0 0 1 1-1Z"/></svg>',
  catalog: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"><rect x="3.5" y="3.5" width="7" height="7" rx="1.8"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.8"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.8"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.8"/></svg>',
  cart: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round" stroke-linecap="round"><path d="M5 8h14l-1.2 11.1a1 1 0 0 1-1 .9H7.2a1 1 0 0 1-1-.9L5 8Z"/><path d="M9 10.5V7a3 3 0 0 1 6 0v3.5"/></svg>',
  orders: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round" stroke-linecap="round"><path d="M6 3.5h12v17l-3-2-3 2-3-2-3 2v-17Z"/><path d="M9 8.5h6M9 12.5h6"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>',
  alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5v5.5M12 16.5v.2"/></svg>',
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
const icon = (name, cls) => h("span", { class: cls || null, html: ICON[name] || ICON.other, "aria-hidden": "true" });

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
function toast(text) {
  toastEl.textContent = text;
  toastEl.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toastEl.hidden = true; }, 2200);
}

class ApiError extends Error {
  constructor(code, data) { super(code); this.code = code; this.data = data; }
}

async function api(path, body) {
  let res;
  try {
    res = await fetch(path, {
      method: body ? "POST" : "GET",
      headers: { "X-Telegram-Init-Data": tg.initData, ...(body ? { "Content-Type": "application/json" } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (e) { throw new ApiError("network"); }
  const data = await res.json().catch(() => ({}));
  if (res.status === 409) throw new ApiError("conflict", data);
  if (!res.ok) throw new ApiError(res.status === 401 ? "expired" : data.error || "error", data);
  return data;
}

function tagEl(number, extra) {
  return h("span", { class: "tag" + (extra ? " " + extra : ""), "aria-label": `${t("number")} ${number}` }, number);
}

function thumb(photo) {
  const box = h("div", { class: "thumb" });
  if (photo) {
    const img = h("img", { src: photo, alt: "", loading: "lazy" });
    img.addEventListener("error", () => { img.remove(); box.append(icon("other")); });
    box.append(img);
  } else box.append(icon("other"));
  return box;
}

function stateEl(item) {
  if (item.status === "stock") {
    return h("span", { class: "state stock" }, item.dealers > 1 ? t("in_stock_n", { n: item.dealers }) : t("in_stock"));
  }
  if (item.status === "preorder") return h("span", { class: "state preorder" }, t("preorder_short", { days: item.days }));
  return h("span", { class: "state none" }, t("not_here"));
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
  footer.replaceChildren();
  document.body.classList.toggle("no-tabs", Boolean(screen.noTabs));
  document.body.classList.remove("with-footer");
  tabsEl.hidden = Boolean(screen.noTabs);
  renderTabs();
  if (state.stack.length > 1) tg.BackButton.show(); else tg.BackButton.hide();
  app.replaceChildren(h("div", { class: "skeleton" }), h("div", { class: "skeleton" }), h("div", { class: "skeleton" }));
  try {
    const node = await screen.draw(current.params);
    if (state.stack[state.stack.length - 1] !== current) return; // пока грузили, ушли на другой экран
    app.replaceChildren(node);
    if (!current.keepScroll) window.scrollTo(0, 0);
  } catch (e) {
    app.replaceChildren(errorView(e));
  }
}

function setFooter(...nodes) {
  footer.replaceChildren(...nodes);
  document.body.classList.toggle("with-footer", nodes.length > 0 && !document.body.classList.contains("no-tabs"));
}

function renderTabs() {
  const items = [["catalog", "tab_catalog"], ["cart", "tab_cart"], ["orders", "tab_orders"]];
  tabsEl.replaceChildren(...items.map(([key, label]) => {
    const current = state.tab === key;
    const btn = h("button", { type: "button", "aria-current": current ? "page" : null, onclick: () => setTab(key) },
      icon(key), t(label));
    if (key === "cart" && state.cart > 0) btn.append(h("span", { class: "badge", id: "cart-badge" }, state.cart));
    return btn;
  }));
}

function setCart(n, bump) {
  state.cart = n;
  renderTabs();
  if (bump) {
    const badge = document.getElementById("cart-badge");
    if (badge) badge.classList.add("bump");
  }
}

function errorView(e) {
  const code = e && e.code;
  const key = { register: "register", blocked: "blocked", expired: "expired" }[code] || "error";
  const retry = key === "error";
  return h("div", { class: "empty" },
    h("div", { class: "mark", html: ICON.alert }),
    h("p", {}, t(key)),
    h("button", { class: "cta secondary", type: "button", onclick: () => (retry ? render() : tg.close()) },
      retry ? t("retry") : t("close")));
}

// ---------- каталог ----------
screens.home = {
  async draw() {
    if (!state.catalog) state.catalog = await api("/api/catalog");
    const me = state.me;
    const root = h("div", {});
    root.append(h("header", { class: "top" },
      h("h1", {}, "JAC Parts"),
      h("div", { class: "sub" }, me.full ? `${t("all_models")}, ${me.region}` : `${me.car || ""}, ${me.region}`)));

    const results = h("div", {});
    const categories = h("div", {});
    const input = h("input", { type: "text", inputmode: "search", placeholder: t("search"), value: state.query, enterkeyhint: "search",
      autocomplete: "off", "aria-label": t("search") });
    const clear = h("button", { class: "clear", type: "button", "aria-label": t("close"), hidden: !state.query }, "×");
    root.append(h("div", { class: "search" }, h("label", {}, icon("search"), input, clear)));
    root.append(results, categories);

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
    if (!models.length) {
      categories.append(emptyView("other", me.car ? t("empty_region") : t("no_car")));
    }
    for (const model of models) {
      const title = model.other ? h("div", { class: "group-title" }, model.name, h("small", {}, t("other_hint")))
        : h("div", { class: "group-title" }, model.mine ? t("categories") : model.name);
      categories.append(title, h("div", { class: "group" }, model.nodes.map((node) =>
        h("button", { class: "row", type: "button", onclick: () => show("parts", { model, node }) },
          h("span", { class: "ico", html: ICON[node.icon] || ICON.other, "aria-hidden": "true" }),
          h("span", { class: "grow name" }, node.name),
          h("span", { class: "count" }, node.count),
          h("span", { html: ICON.chev, "aria-hidden": "true" })))));
    }
    if (!me.full && models.length) categories.append(h("p", { class: "car-hint" }, t("change_car_hint")));
    if (state.query.length >= 2) run();
    return root;
  },
};

function resultsView(data) {
  if (!data.items.length) {
    return h("div", { class: "empty" },
      h("div", { class: "mark", html: ICON.search }),
      h("h2", {}, t("nothing", { q: data.q })),
      h("p", {}, t("nothing_hint")));
  }
  return h("div", {},
    h("div", { class: "group-title" }, t("results", { n: data.items.length })),
    partList(data.items));
}

function partList(items) {
  return h("div", { class: "group" }, items.map((item) =>
    h("button", { class: "row item", type: "button", onclick: () => show("part", { id: item.id }) },
      thumb(item.photo),
      h("div", { class: "grow" },
        h("div", { class: "name" }, item.name),
        tagEl(item.number),
        h("div", { class: "price-line" },
          item.price ? h("span", { class: "price" }, item.status === "stock" && item.dealers > 1
            ? t("from", { price: item.price }) : item.price) : null,
          stateEl(item))))));
}

screens.parts = {
  async draw({ model, node }) {
    const data = await api(`/api/parts?model_id=${model.id}&node_id=${node.id}`);
    const root = h("div", {},
      h("header", { class: "top" }, h("h1", {}, node.name), h("div", { class: "sub" }, model.name)));
    const list = partList(data.items);
    root.append(list);
    let offset = data.items.length;
    if (offset < data.total) {
      const more = h("button", { class: "cta secondary", type: "button" }, t("more"));
      more.addEventListener("click", async () => {
        more.disabled = true;
        const next = await api(`/api/parts?model_id=${model.id}&node_id=${node.id}&offset=${offset}`);
        offset += next.items.length;
        for (const row of partList(next.items).children) list.append(row);
        more.disabled = false;
        if (offset >= next.total) more.remove();
      });
      root.append(h("div", { class: "group-title" }), more);
    }
    return root;
  },
};

// ---------- карточка детали ----------
screens.part = {
  async draw({ id }) {
    const p = await api(`/api/part/${id}`);
    const root = h("div", {});
    if (p.photo) {
      const img = h("img", { src: p.photo, alt: p.name });
      const box = h("div", { class: "photo" }, img);
      img.addEventListener("error", () => box.replaceWith(heroTag(p.number)));
      root.append(box);
    } else {
      root.append(heroTag(p.number));
    }
    root.append(h("div", { class: "part-head" },
      h("h1", { class: "part-title" }, p.name),
      h("div", { class: "part-sub" }, `${p.model}, ${p.node}`),
      p.photo ? tagEl(p.number, "on-page") : null,
      p.description ? h("p", { class: "desc" }, p.description) : null));

    if (p.offers.length) root.append(...offersView(p));
    else if (p.preorder) root.append(...preorderView(p));
    else {
      root.append(h("div", { class: "group-title" }),
        h("div", { class: "group offer" },
          h("div", { class: "state none" }, t("not_here")),
          p.elsewhere ? h("p", { class: "note" }, t("elsewhere", { n: p.elsewhere })) : null));
    }
    return root;
  },
};

function heroTag(number) {
  return h("div", { class: "hero-tag", "aria-hidden": "true" },
    h("span", { class: "string" }),
    h("span", { class: "tag big" }, h("small", {}, t("number")), h("span", {}, number)));
}

function dealerBlock(dealer, label) {
  return h("div", { class: "dealer" },
    label ? h("div", { class: "label" }, label) : null,
    h("div", { class: "dname" }, dealer.name),
    dealer.address ? h("div", { class: "addr" }, dealer.address) : null,
    linksView(dealer));
}

function linksView(dealer) {
  if (!dealer.map && !dealer.phone) return null;
  return h("div", { class: "links" },
    dealer.map ? h("a", { class: "chip", href: dealer.map, onclick: (ev) => { ev.preventDefault(); openLink(dealer.map); } },
      icon("route"), t("route")) : null,
    dealer.phone ? h("a", { class: "chip", href: "tel:" + dealer.phone.replace(/[^\d+]/g, "") }, icon("call"), t("call")) : null);
}

function openLink(url) {
  try { tg.openLink(url); } catch (e) { window.open(url, "_blank", "noopener"); }
}

async function addToCart(stockId, dealerId, onDone) {
  try {
    const res = await api("/api/cart/add", { stock_id: stockId, dealer_id: dealerId || null });
    if (res.ok) {
      haptic("success");
      setCart(res.cart, true);
      toast(t("added"));
    } else {
      haptic("error");
      toast(t("limit"));
    }
    if (onDone) onDone(res);
  } catch (e) {
    haptic("error");
    toast(t("error"));
  }
}

function offersView(p) {
  const [best, ...rest] = p.offers;
  const nodes = [h("div", { class: "group-title" }),
    h("div", { class: "group offer" },
      h("div", { class: "big-price" }, best.price),
      h("div", { class: "state stock" }, p.offers.length > 1 ? t("in_stock_n", { n: p.offers.length }) : t("in_stock")),
      dealerBlock(best.dealer, p.offers.length > 1 ? t("best", { region: p.region }) : t("pickup_at")))];
  if (rest.length) {
    nodes.push(h("div", { class: "group-title" }, t("other_dealers")),
      h("div", { class: "group" }, rest.map((o) => dealerRow(o))));
  }
  setFooter(cartCta(best.price, () => best.in_cart, () => best.stock_id, () => null, (qty) => { best.in_cart = qty; }));
  return nodes;
}

/* Главная кнопка карточки: «В корзину · цена». Уже в корзине — «Перейти в корзину · N шт.» */
function cartCta(price, inCart, stockId, dealerId, onAdded) {
  const label = h("span", {});
  const side = h("span", { class: "p" });
  const cta = h("button", { class: "cta", type: "button" }, label, side);
  const paint = () => {
    const n = inCart();
    label.textContent = n ? t("go_cart") : t("add");
    side.textContent = n ? t("pieces", { n }) : price;
  };
  cta.addEventListener("click", () => {
    if (inCart()) { setTab("cart"); return; }
    if (cta.disabled) return;
    addToCart(stockId(), dealerId(), (res) => { if (res.ok) { onAdded(res.qty); paint(); } });
  });
  paint();
  return cta;
}

function dealerRow(o) {
  const btn = h("button", { class: "add-mini" + (o.in_cart ? " has" : ""), type: "button", "aria-label": `${t("add")} — ${o.dealer.name}`,
    html: o.in_cart ? null : ICON.plus });
  if (o.in_cart) btn.textContent = o.in_cart;
  btn.addEventListener("click", () => addToCart(o.stock_id, null, (res) => {
    if (res.ok) { o.in_cart = res.qty; btn.className = "add-mini has"; btn.textContent = res.qty; }
  }));
  return h("div", { class: "row plain dealer-row" },
    h("div", { class: "grow" },
      h("div", { class: "name" }, o.dealer.name),
      o.dealer.address ? h("div", { class: "addr meta" }, o.dealer.address) : null),
    h("div", { class: "side" }, h("div", { class: "price" }, o.price), h("div", { class: "meta" }, t("pieces", { n: o.qty }))),
    btn);
}

function preorderView(p) {
  const pre = p.preorder;
  let chosen = pre.dealers.length === 1 ? pre.dealers[0].id : null;
  const nodes = [h("div", { class: "group-title" }),
    h("div", { class: "group offer" },
      h("div", { class: "big-price" }, pre.price),
      h("div", { class: "state preorder" }, t("preorder_title")),
      h("p", { class: "note" }, t("preorder_note", { days: pre.days })))];
  const rows = pre.dealers.map((d) => {
    const row = h("button", { class: "row pick", type: "button", role: "radio", "aria-checked": String(d.id === chosen) },
      h("span", { class: "radio", "aria-hidden": "true" }),
      h("span", { class: "grow" }, h("div", { class: "name" }, d.name), d.address ? h("div", { class: "meta" }, d.address) : null));
    row.addEventListener("click", () => {
      chosen = d.id;
      haptic("tap");
      for (const r of rows) r.setAttribute("aria-checked", String(r === row));
      cta.disabled = false;
    });
    return row;
  });
  nodes.push(h("div", { class: "group-title" }, t("pickup")), h("div", { class: "group", role: "radiogroup" }, rows));
  const cta = cartCta(pre.price, () => pre.in_cart, () => pre.stock_id, () => chosen, (qty) => { pre.in_cart = qty; });
  cta.disabled = !chosen && !pre.in_cart;
  setFooter(cta);
  return nodes;
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
    return emptyView("cart", t("cart_empty"), t("cart_empty_hint"), [t("open_catalog"), () => setTab("catalog")]);
  }
  const root = h("div", {}, h("header", { class: "top" }, h("h1", {}, t("tab_cart"))));
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
  root.append(h("div", { class: "group" }, data.items.map((item) =>
    h("div", { class: "row line" },
      thumb(item.photo),
      h("div", { class: "grow" },
        h("div", { class: "name" }, item.name),
        tagEl(item.number),
        h("div", { class: "where" + (item.preorder ? " preorder" : "") },
          item.preorder ? `${t("preorder_short", { days: item.days })}: ${item.dealer}` : item.dealer),
        !item.available ? h("div", { class: "warn" }, t("unavailable"))
          : item.qty > item.max ? h("div", { class: "warn" }, t("only_n", { n: item.max })) : null,
        h("div", { class: "bottom" },
          h("span", { class: "price" }, item.available ? item.subtotal : item.price),
          h("span", { class: "stepper" },
            h("button", { type: "button", "aria-label": item.qty > 1 ? "−1" : t("remove"),
              onclick: () => update("/api/cart/change", { item_id: item.id, delta: -1 }) }, "−"),
            h("span", {}, item.qty),
            h("button", { type: "button", "aria-label": "+1", disabled: item.qty >= item.max || !item.available,
              onclick: () => update("/api/cart/change", { item_id: item.id, delta: 1 }) }, "+"))))))));
  root.append(h("div", { class: "total" }, h("span", {}, t("total")), h("span", { class: "price" }, data.total)));
  if (data.orders > 1) root.append(h("p", { class: "small-note" }, t("split", { n: data.orders })));
  const cta = h("button", { class: "cta", type: "button", disabled: !data.orders },
    h("span", {}, t("checkout")), h("span", { class: "p" }, data.total));
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
    const root = h("div", { class: "empty done" },
      h("div", { class: "mark", html: ICON.check }),
      h("h2", {}, orders.length > 1 ? t("done_many", { n: orders.length }) : t("done")),
      h("div", { class: "nums" }, orders.map((o) => tagEl(String(o.id), "on-page"))),
      h("p", {}, t("done_hint")));
    setFooter(h("button", { class: "cta secondary", type: "button", onclick: () => setTab("orders") }, t("my_orders")));
    return root;
  },
};

// ---------- заказы ----------
screens.orders = {
  async draw() {
    const data = await api("/api/orders");
    if (!data.orders.length) {
      return emptyView("orders", t("orders_empty"), t("cart_empty_hint"), [t("open_catalog"), () => setTab("catalog")]);
    }
    return h("div", {},
      h("header", { class: "top" }, h("h1", {}, t("tab_orders"))),
      h("div", { class: "group" }, data.orders.map(orderView)));
  },
};

function orderView(o) {
  const items = o.items.map((i) => (i.qty > 1 ? `${i.name} × ${i.qty}` : i.name)).join(", ");
  const finished = o.status === "COMPLETED" || o.status === "CANCELLED";
  return h("div", { class: "order" },
    h("div", { class: "head" }, h("span", { class: "num" }, t("order_n", { id: o.id })), h("span", { class: "price" }, o.total)),
    h("div", { class: "when" }, o.date),
    h("div", { class: "what" }, items),
    o.preorder && !finished ? h("div", { class: "state preorder" }, t("preorder_short", { days: o.days })) : null,
    o.steps.length ? h("div", { class: "steps", "aria-hidden": "true" }, o.steps.map((s) => h("i", { class: s.state }))) : null,
    h("div", { class: "now" + (o.status === "CANCELLED" ? " cancel" : "") }, o.status_text),
    !finished ? h("div", { class: "pickup" },
      h("div", {}, o.dealer.name),
      o.dealer.address ? h("div", { class: "addr" }, o.dealer.address) : null,
      linksView(o.dealer)) : null);
}

function emptyView(iconName, title, text, action) {
  return h("div", { class: "empty" },
    h("div", { class: "mark", html: ICON[iconName] || ICON.other }),
    h("h2", {}, title),
    text ? h("p", {}, text) : null,
    action ? h("button", { class: "cta secondary", type: "button", onclick: action[1] }, action[0]) : null);
}

// ---------- запуск ----------
function applyScheme() {
  document.documentElement.dataset.scheme = tg && tg.colorScheme === "dark" ? "dark" : "light";
}

async function start() {
  if (!tg || !tg.initData) { // открыли в обычном браузере
    state.t = {};
    app.replaceChildren(h("div", { class: "empty" },
      h("div", { class: "mark", html: ICON.cart }),
      h("h2", {}, "JAC Parts"),
      h("p", {}, "Откройте витрину из Telegram-бота. Do‘konni Telegram-botdan oching. Open the shop from the Telegram bot.")));
    return;
  }
  tg.ready();
  tg.expand();
  applyScheme();
  tg.onEvent("themeChanged", applyScheme);
  tg.BackButton.onClick(back);
  try { tg.setHeaderColor("secondary_bg_color"); tg.setBackgroundColor("secondary_bg_color"); } catch (e) { /* старые версии */ }
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
