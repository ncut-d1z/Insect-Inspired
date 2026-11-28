"use strict";
(() => {
  const body = document.body;
  const misc = body.dataset.page === "misc";
  const data = window.LITERATURE_INDEX;
  const status = document.getElementById("search-status");
  const search = document.getElementById("search");
  const theme = document.getElementById("theme");
  const sections = Array.from(document.querySelectorAll("section[data-theme]"));
  const size = 50;
  let page = 0;
  if (!data || data.checkpoint !== body.dataset.checkpoint || data.edition !== body.dataset.edition) {
    status.textContent = "书目资源未载入或版本不符。请将两个 HTML 文件和同版 ref-data 目录放在一起。";
    return;
  }
  const legacyMisc = /^#(?:section-U00|literature-U00|work-[0-9a-f]{14}-U00)$/;
  if (!misc && legacyMisc.test(location.hash)) {
    location.replace("misc.html" + location.hash);
    return;
  }
  function values(row) {
    const fields = [row[0], row[1], row[2], row[3], data.venues[row[4]], row[5]];
    if (misc) fields.push(row[6].map(i => data.reasons[i]).join("、"), data.actions[row[7]]);
    return fields;
  }
  function fold(value) {
    return String(value ?? "").normalize("NFKC").toLowerCase();
  }
  const rows = data.rows.map(values);
  const haystacks = rows.map(fields => fold(fields.join(" ")));
  const all = rows.map((_, i) => i);
  const sorters = new Map();
  const collator = new Intl.Collator("zh-CN", {numeric:true, sensitivity:"base"});
  function compare(a, b, order) {
    const x = rows[a][order.col], y = rows[b][order.col];
    const emptyX = x == null || x === "", emptyY = y == null || y === "";
    if (emptyX !== emptyY) return emptyX ? 1 : -1;
    const diff = order.col === 3 ? Number(x) - Number(y) : collator.compare(x || "", y || "");
    return diff * order.direction || a - b;
  }
  function makeRow(i, group) {
    const tr = document.createElement("tr");
    tr.id = "work-" + data.anchors[i] + "-" + group;
    tr.dataset.key = rows[i][0];
    rows[i].forEach((value, column) => {
      const cell = document.createElement(column ? "td" : "th");
      if (!column) cell.scope = "row";
      if (column === 5 && /^10\.\d{4,9}\/\S+$/i.test(value)) {
        const link = document.createElement("a");
        link.textContent = value;
        link.href = "https://doi.org/" + value.split("/").map(encodeURIComponent).join("/");
        cell.append(link);
      } else {
        cell.textContent = value == null || value === "" ? "—" : value;
      }
      tr.append(cell);
    });
    return tr;
  }
  function render() {
    const terms = fold(search.value).trim().split(/\s+/).filter(Boolean);
    let occurrences = 0;
    const selected = new Set();
    for (const section of sections) {
      const group = section.dataset.theme;
      section.hidden = Boolean(theme && theme.value && theme.value !== group);
      const tbody = section.querySelector("tbody");
      if (section.hidden) {
        tbody.replaceChildren();
        continue;
      }
      const members = misc ? all : data.groups[group];
      const matches = members.filter(i => terms.every(t => haystacks[i].includes(t)));
      const order = sorters.get(group);
      if (order) matches.sort((a, b) => compare(a, b, order));
      occurrences += matches.length;
      if (!misc) for (const i of matches) selected.add(i);
      let displayed = matches;
      if (misc) {
        const pages = Math.max(1, Math.ceil(matches.length / size));
        page = Math.min(page, pages - 1);
        displayed = matches.slice(page * size, (page + 1) * size);
        document.getElementById("previous").disabled = page === 0;
        document.getElementById("next").disabled = page + 1 === pages;
        document.getElementById("page-number").textContent = "第 " + (page + 1) + " / " + pages + " 页";
      }
      section.querySelector(".count").textContent = matches.length + " / " + members.length + " 篇";
      const children = document.createDocumentFragment();
      for (const i of displayed) children.append(makeRow(i, group));
      if (!displayed.length) {
        const row = document.createElement("tr"), cell = document.createElement("td");
        cell.colSpan = section.querySelectorAll("thead th").length;
        cell.textContent = members.length ? "没有匹配的文献。" : "当前快照暂无文献。";
        row.append(cell);
        children.append(row);
      }
      tbody.replaceChildren(children);
    }
    const count = misc ? occurrences : selected.size;
    status.textContent = "匹配 " + count + " / " + rows.length + " 篇文献" +
      (misc ? "。" : "，共 " + occurrences + " 条主题记录。");
  }
  function resetOrder() {
    sorters.clear();
    for (const el of document.querySelectorAll("thead th[aria-sort]")) el.removeAttribute("aria-sort");
  }
  function reveal() {
    if (!misc && legacyMisc.test(location.hash)) {
      location.replace("misc.html" + location.hash);
      return;
    }
    const match = /^#work-([0-9a-f]{14})-(L0[1-9]|U00)$/.exec(location.hash);
    if (!match) return;
    const i = data.anchors.indexOf(match[1]);
    if (i < 0 || (misc ? match[2] !== "U00" : !data.groups[match[2]]?.includes(i))) return;
    search.value = "";
    if (theme) theme.value = "";
    resetOrder();
    page = misc ? Math.floor(i / size) : 0;
    render();
    document.getElementById(location.hash.slice(1))?.scrollIntoView({block:"center"});
  }
  search.addEventListener("input", () => { page = 0; render(); });
  if (theme) theme.addEventListener("change", render);
  document.getElementById("clear").addEventListener("click", () => {
    search.value = "";
    if (theme) theme.value = "";
    page = 0;
    resetOrder();
    render();
    search.focus();
  });
  for (const section of sections) {
    section.querySelector("thead").addEventListener("click", event => {
      const button = event.target.closest("button[data-column]");
      if (!button) return;
      const group = section.dataset.theme, col = Number(button.dataset.column);
      const old = sorters.get(group);
      const direction = old?.col === col && old.direction === 1 ? -1 : 1;
      sorters.set(group, {col, direction});
      for (const el of section.querySelectorAll("th[aria-sort]")) el.removeAttribute("aria-sort");
      button.parentElement.setAttribute("aria-sort", direction === 1 ? "ascending" : "descending");
      page = 0;
      render();
    });
  }
  if (misc) {
    document.getElementById("previous").addEventListener("click", () => { page--; render(); });
    document.getElementById("next").addEventListener("click", () => { page++; render(); });
  }
  addEventListener("hashchange", reveal);
  render();
  reveal();
  body.dataset.ready = "true";
  performance.mark("bibliography-ready");
})();
