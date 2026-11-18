"use strict";
// Публична страница на портала, сервирана от Home Assistant интеграцията.
//
// Същата адаптивна страница като в add-on-а (текстовете зависят от артефактите:
// документи / снимки / файлове, търсене, QR, SHA-256, изтегляне с ключ), но заявките
// минават през fail-closed моста на интеграцията (`/api/hapi_enterprise/v1/p/<id>`).
//
// Сигурност: ключът на портала НЕ влиза в адреса на заявката — държи се във фрагмента
// на страницата (`#token=…`) и се праща само като `X-Portal-Key`. ДАННИТЕ никога не минават
// през `innerHTML`: всичко от API-то се вмъква с `textContent`. Единственото `innerHTML` е
// `svg.innerHTML = paths[…]` — фиксиран SVG път от константна карта в този файл, без данни.
// `tests/portal-variants.cjs` пази точно това правило (и в двете копия на страницата).

const $ = (id) => document.getElementById(id);

// ── Език на страницата (PP-14) ───────────────────────────────────────────────
// Речникът е СЪЩИЯТ файл като в add-on портала (`portal-i18n.js`, BG/EN/DE), сервиран от
// интеграцията като asset — едни текстове за двете страници, без втори речник. Езикът идва
// от адреса (`?lang=en`), после от запазения избор на посетителя, иначе от `lang` на самата
// страница (български). Без речник (стар кеш) остават българските текстове от HTML —
// страницата НЕ показва ключове вместо думи.
const I18N = globalThis.HapiPortalI18n || null;
const LANG_KEY = "hapi.portalLang";
function resolveLang() {
  const fromUrl = new URL(location.href).searchParams.get("lang");
  if (I18N && I18N.isLang(fromUrl)) return I18N.pick(fromUrl);
  try {
    const saved = localStorage.getItem(LANG_KEY);
    if (I18N && I18N.isLang(saved)) return I18N.pick(saved);
  } catch {
    // Няма хранилище (частен режим) — остава езикът от адреса или подразбирането.
  }
  const html = document.documentElement && document.documentElement.getAttribute("lang");
  return I18N ? I18N.pick(html) : "bg";
}
let LANG = resolveLang();
/**
 * Текст по ключ със заместители (`{n}`, `{what}`, `{name}`, `{status}`). Без речник
 * (стар кеш) връща ключа — тогава `applyLanguage()` не пипа статичния HTML, който е на
 * български, а съобщенията от кода остават видими като ключове, не като празни места.
 */
const T = (key, vars) => (I18N ? I18N.t(LANG, key, vars) : key);

/**
 * Прилага езика: статичните текстове (`data-i18n*` в HTML) и — ако данните вече са
 * заредени — преизвежда заглавието, изречението за съдържанието и списъка, за да не
 * остане екранът на стария език до презареждане.
 */
function applyLanguage() {
  if (I18N) I18N.apply(document, LANG);
  else if (document.documentElement) document.documentElement.setAttribute("lang", LANG);
  const select = $("lang");
  if (select) select.value = LANG;
  if (!portal) return;
  // Профилът се строи НАНОВО: съществителните („файл/файла“, „Datei/Dateien“) идват от
  // речника, тоест зависят от езика — иначе броячите остават на стария език.
  prof = buildProfile(allFiles, portal);
  paintPortal(portal);
  applyWording(prof);
  paint(qValue());
}

// Ключът на портала от адреса: /api/hapi_enterprise/portal/<id или slug>.
const PORTAL_PATH = /^\/api\/hapi_enterprise\/portal\/([^/]+)\/?$/;
const key = decodeURIComponent((location.pathname.match(PORTAL_PATH) || [])[1] || "").trim();
// Ключът за достъп идва само от фрагмента — не се изпраща като query параметър,
// за да не попада в логове, Referer или история на прокси.
const token = new URLSearchParams(location.hash.slice(1)).get("token") || "";
const apiBase = "/api/hapi_enterprise/v1/p/" + encodeURIComponent(key);
const authHeaders = (extra) => Object.assign(token ? { "X-Portal-Key": token } : {}, extra || {});
// Адресът, който се копира/кодира в QR — същият изглед, с ключ във фрагмента.
const pageUrl = () =>
  location.origin + "/api/hapi_enterprise/portal/" + encodeURIComponent(key) +
  (token ? "#token=" + encodeURIComponent(token) : "");

const MAX_LISTED = 500;
// Състояние на режим „папка“: съдържанието на СОБСТВЕНАТА папка на портала — това, до
// което води QR кодът. `null` значи „показвай регистрираните файлове“.
let folderRel = null;
let folderFiles = [];
let folderSubs = [];
// Дървото на портала (зарежда се веднъж) и дали списъкът показва ВСИЧКИ нива.
let treeRoot = null;
let treeCurrent = "";
let treePending = null;
let showAll = false;
let portal = null;
let allFiles = [];
// Профил на съдържанието — всички текстове на страницата се извеждат от него.
let prof = null;
// Дали бързата лента е вързана (веднъж за живота на страницата).
let barWired = false;

// Стойността на търсенето — празна, когато страницата няма поле за търсене.
const qValue = () => {
  const q = $("q");
  return q ? q.value : "";
};

// Единствената точка, която пише в лентата за състояние. Липсващият възел (страница на отказ,
// файл, 410) не е грешка на данните — тогава просто няма къде да се пише, а не се пада.
const setStatus = (text, kind) => {
  const el = $("status");
  if (!el) return;
  el.textContent = text || "";
  el.hidden = !text;
  el.dataset.kind = kind || "";
};

/** Кратък адрес за шифър/идентификатор, с пълната стойност в title. */
const short = (value, keep) => {
  const s = String(value || "");
  return s.length > keep ? s.slice(0, keep) + "…" : s;
};

const fmtSize = (n) => {
  const v = Number(n) || 0;
  if (v < 1024) return v + " B";
  if (v < 1048576) return (v / 1024).toFixed(1).replace(".0", "") + " KB";
  if (v < 1073741824) return (v / 1048576).toFixed(1).replace(".0", "") + " MB";
  return (v / 1073741824).toFixed(2) + " GB";
};

const fmtDate = (iso) => {
  const d = iso ? new Date(iso) : null;
  if (!d || Number.isNaN(d.getTime())) return "";
  const p = (x) => String(x).padStart(2, "0");
  return p(d.getDate()) + "." + p(d.getMonth() + 1) + "." + d.getFullYear();
};

/** Вид на артефакта по разширение — определя как се нарича съдържанието на портала. */
const KIND_BY_EXT = {
  pdf: "doc", doc: "doc", docx: "doc", odt: "doc", rtf: "doc", txt: "doc", md: "doc",
  xls: "doc", xlsx: "doc", ods: "doc", csv: "doc", ppt: "doc", pptx: "doc", odp: "doc",
  jpg: "image", jpeg: "image", png: "image", gif: "image", webp: "image", svg: "image",
  bmp: "image", tif: "image", tiff: "image", heic: "image", avif: "image",
  mp3: "media", wav: "media", ogg: "media", m4a: "media", mp4: "media", mov: "media",
  mkv: "media", webm: "media", avi: "media",
  zip: "archive", rar: "archive", "7z": "archive", tar: "archive", gz: "archive",
};
const kindOf = (name) => {
  const ext = String(name || "").split(".").pop().toLowerCase();
  return KIND_BY_EXT[ext] || "file";
};

/** Резервни съществителни, ако речникът не се е заредил (стар кеш): страницата остава
 * четима на български. Иначе формите идват от `portal-i18n.js` — за всеки вид и език. */
const NOUNS = {
  file: { one: "файл", many: "файла", capMany: "Файлове", for: "файлове" },
};
const nounOf = (kind) => (I18N ? I18N.nouns(LANG)[kind] || I18N.nouns(LANG).file : NOUNS.file);
const nounFor = (n, noun) => (n === 1 ? noun.one : noun.many);

/**
 * Профил на съдържанието: какви артефакти има в портала и какво може да се прави с тях.
 * От него зависят всички текстове — не се показват упътвания за липсващи неща
 * (напр. „сверявай SHA-256“, когато нито един файл няма отпечатък).
 */
function buildProfile(files, data) {
  const kinds = new Map();
  let hasHash = false,
    hasKey = false,
    hasDisabled = false,
    hasTax = false,
    hasTags = false,
    hasVersion = false,
    newest = 0;
  for (const f of files) {
    const kind = kindOf(f.name);
    kinds.set(kind, (kinds.get(kind) || 0) + 1);
    if (f.sha256) hasHash = true;
    if (f.accessMode === "KEY_REQUIRED") hasKey = true;
    if (f.accessMode === "DISABLED") hasDisabled = true;
    if (f.topic || f.category || f.group) hasTax = true;
    if ((f.tags || []).length) hasTags = true;
    if (Number(f.version) > 1) hasVersion = true;
    const t = Date.parse(f.uploadedAt || "");
    if (t > newest) newest = t;
  }
  const total = files.length;
  // Един вид артефакти → назоваваме го точно; документи + снимки → двете; иначе общо „файлове“.
  let key = "file";
  if (total && kinds.size === 1) key = [...kinds.keys()][0];
  else if (total && kinds.size === 2 && kinds.has("doc") && kinds.has("image")) key = "mixed";
  return {
    total,
    key,
    noun: nounOf(key),
    kinds,
    hasHash,
    allHash: total > 0 && files.every((f) => f.sha256),
    hasKey,
    hasDisabled,
    allDisabled: total > 0 && files.every((f) => f.accessMode === "DISABLED"),
    hasTax,
    hasTags,
    hasVersion,
    newest: newest ? new Date(newest) : null,
    isPublic: Boolean(data && data.visibility === "public"),
  };
}

/** Прилага текстовете според профила на съдържанието (след като данните са заредени). */
function applyWording(p) {
  const noun = p.noun;
  const hasFiles = p.total > 0;

  $("visibility").textContent = hasFiles
    ? T("visibility.for", { what: noun.for })
    : p.isPublic
      ? T("visibility.public")
      : T("visibility.private");
  $("files-title").textContent = hasFiles ? noun.capMany : T("files.title.other");

  // Прескачането към списъка има смисъл само когато има списък.
  const skip = $("skip");
  skip.textContent = hasFiles ? T("nav.skip.files", { what: noun.for }) : T("nav.skip.content");
  skip.hidden = !hasFiles;

  // Търсенето се показва само когато има какво да се търси, а подсказката —
  // само по полетата, които наистина съществуват в тези файлове.
  $("toolbar").hidden = p.total <= 3;
  const qEl = $("q");
  if (qEl) {
    qEl.placeholder = p.hasTags
      ? T("files.search.placeholder.tags")
      : p.hasTax
        ? T("files.search.placeholder.tax")
        : T("files.search.placeholder.plain");
    const label = $("q-label");
    if (label) label.textContent = qEl.placeholder;
  }

  // QR кодът НЕ се показва на самата страница: посетителят вече е тук, а кодът води точно
  // до тази страница. За споделяне има бутон „Копирай адреса“, който дава същия адрес.

  const details = [];
  if (hasFiles) details.push(T("summary.chip.files", { n: p.total }));
  if (p.newest) details.push(T("footer.updated", { date: fmtDate(p.newest.toISOString()) }));
  details.push(T("footer.owner"));
  const strong = document.createElement("strong");
  strong.textContent = "hAPI Enterprise";
  $("foot-note").replaceChildren(
    document.createTextNode(T("footer.served")),
    strong,
    document.createTextNode(" · " + details.join(" · ") + "."),
  );
}

/** Копиране с резервен вариант за стари браузъри/несигурен контекст. */
async function copy(value, okText) {
  try {
    if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(value);
    else {
      const ta = document.createElement("textarea");
      ta.value = value;
      ta.setAttribute("readonly", "");
      ta.className = "sr-only";
      document.body.append(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    setStatus(okText || T("copy.ok"), "ok");
  } catch {
    setStatus(T("copy.blocked"), "err");
  }
}

/** Малка икона (вграден SVG — без шрифт-икони и без мрежови заявки). */
function icon(name) {
  const paths = {
    download: '<path d="M12 3.5v11"/><path d="M7.5 10L12 14.5 16.5 10"/><path d="M4.5 20h15"/>',
    copy: '<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 5.5h-9a2 2 0 0 0-2 2v9"/>',
    lock: '<rect x="4.6" y="10.6" width="14.8" height="9.4" rx="2"/><path d="M8.2 10.6V7.6a3.8 3.8 0 0 1 7.6 0v3"/>',
    file: '<path d="M6 3.4h8.2l3.8 3.8v13.4H6z"/><path d="M14 3.6v3.8h3.8"/>',
    folder: '<path d="M3.6 7.2a2 2 0 0 1 2-2h3.8l2 2.4h7a2 2 0 0 1 2 2v8.6a2 2 0 0 1-2 2H5.6a2 2 0 0 1-2-2z"/>',
    shield: '<path d="M12 3.2l7.4 3v6.1c0 4-3 7.4-7.4 8.5-4.4-1.1-7.4-4.5-7.4-8.5V6.2z"/><path d="M8.8 12.2l2.4 2.4 4-4"/>',
  };
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "ico");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  svg.innerHTML = paths[name] || paths.file;
  return svg;
}

/** Един ред „етикет: стойност“ в метаданните на файла. */
function metaItem(label, value, opts) {
  const li = document.createElement("li");
  if (opts && opts.mono) li.className = "mono";
  li.textContent = label ? label + ": " + value : value;
  if (opts && opts.title) li.title = opts.title;
  return li;
}

/** SHA-256 на байтовете, които реално ще получи потребителят. `crypto.subtle` съществува само
 * в защитен контекст (HTTPS или localhost), затова викащият проверява преди да го ползва. */
async function sha256Hex(buffer) {
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/** Изтегляне: FREE → директно; KEY_REQUIRED → с ключ в X-File-Key. */
async function downloadFile(file, key) {
  setStatus(T("file.status.downloading", { name: file.name }));
  try {
    const headers = authHeaders(key ? { "X-File-Key": key } : {});
    const url = apiBase + "/files/" + encodeURIComponent(file.id) + "/download";
    const res = await fetch(url, { headers, referrerPolicy: "no-referrer" });
    if (res.status === 403) {
      setStatus(key ? T("file.status.badKey") : T("file.status.needKey"), "err");
      return;
    }
    if (!res.ok) {
      setStatus(T("file.status.http", { status: res.status }), "err");
      return;
    }
    const blob = await res.blob();
    // Сверката е върху СЪЩИТЕ байтове, които се записват: ако хешът не съвпада, файлът НЕ се
    // запазва. Дотук страницата само ПОКАЗВАШЕ SHA-256 — тоест обещание без проверка (DEF-03).
    const expected = String(file.sha256 || "").toLowerCase();
    let verdict = "none";
    if (expected) {
      if (crypto && crypto.subtle && crypto.subtle.digest) {
        if ((await sha256Hex(await blob.arrayBuffer())) !== expected) {
          setStatus(T("file.status.mismatch"), "err");
          return;
        }
        verdict = "ok";
      } else {
        verdict = "noVerify";
      }
    }
    const link = document.createElement("a");
    const objectUrl = URL.createObjectURL(blob);
    link.href = objectUrl;
    link.download = file.name;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 30000);
    if (verdict === "ok") setStatus(T("file.status.verified"), "ok");
    else if (verdict === "noVerify") setStatus(T("file.status.noVerify"));
    else setStatus(T("file.status.started", { name: file.name }), "ok");
  } catch {
    setStatus(T("file.status.offline"), "err");
  }
}

/** Карта на един файл: име, метаданни, SHA-256 и действие според политиката. */
function fileCard(file) {
  const li = document.createElement("li");
  li.className = "file";
  if (file.accessMode === "DISABLED") li.classList.add("is-disabled");

  const head = document.createElement("div");
  head.className = "file-head";
  const glyph = document.createElement("span");
  glyph.className = "file-glyph";
  glyph.append(icon("file"));
  const title = document.createElement("h3");
  title.className = "file-name";
  title.textContent = file.name;
  head.append(glyph, title);
  li.append(head);

  const meta = document.createElement("ul");
  meta.className = "file-meta";
  const tax = [file.topic, file.category, file.group].filter(Boolean).join(" / ");
  if (tax) meta.append(metaItem("", tax));
  meta.append(metaItem(T("files.col.size"), fmtSize(file.size)));
  if (Number(file.version) > 1) meta.append(metaItem("v", String(file.version)));
  const date = fmtDate(file.uploadedAt);
  if (date) meta.append(metaItem(T("files.col.changed"), date));
  if (file.encrypted) meta.append(metaItem("", T("file.meta.encrypted")));
  if (file.accessMode === "KEY_REQUIRED") meta.append(metaItem("", T("file.meta.key")));
  li.append(meta);

  if (file.sha256) {
    const hash = document.createElement("p");
    hash.className = "file-hash";
    hash.title = T("file.sha.title", { full: file.sha256 });
    const label = document.createElement("span");
    label.className = "mono";
    label.textContent = T("file.sha.label", { short: short(file.sha256, 8) });
    const copyBtn = document.createElement("button");
    copyBtn.type = "button";
    copyBtn.className = "icon-btn";
    copyBtn.title = T("file.sha.copy");
    copyBtn.setAttribute("aria-label", T("file.sha.copyFor", { name: file.name }));
    copyBtn.append(icon("copy"));
    copyBtn.addEventListener("click", () => copy(file.sha256, T("file.sha.copied")));
    hash.append(label, copyBtn);
    li.append(hash);
  }

  const actions = document.createElement("div");
  actions.className = "file-actions";
  if (file.accessMode === "DISABLED") {
    const blocked = document.createElement("span");
    blocked.className = "chip chip-warn";
    blocked.textContent = T("file.disabled");
    actions.append(blocked);
  } else if (file.accessMode === "KEY_REQUIRED") {
    const input = document.createElement("input");
    input.type = "password";
    input.autocomplete = "off";
    input.className = "key-input";
    input.placeholder = T("file.key.placeholder");
    input.setAttribute("aria-label", T("file.key.aria", { name: file.name }));
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-primary";
    btn.append(icon("lock"), document.createTextNode(T("file.download.key")));
    btn.addEventListener("click", () => downloadFile(file, input.value.trim()));
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") downloadFile(file, input.value.trim());
    });
    actions.append(input, btn);
  } else {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-primary";
    btn.append(icon("download"), document.createTextNode(T("file.download")));
    btn.addEventListener("click", () => downloadFile(file, ""));
    actions.append(btn);
  }
  if (file.accessMode !== "DISABLED") {
    // Същото съдържание като лист: подробности и сверка на отпечатъка без сваляне.
    const infoBtn = document.createElement("button");
    infoBtn.type = "button";
    infoBtn.className = "btn btn-ghost btn-sm";
    infoBtn.title = T("fileinfo.title");
    infoBtn.setAttribute("aria-label", T("fileinfo.openFor", { name: file.name }));
    infoBtn.append(icon("file"), document.createTextNode(" " + T("fileinfo.open")));
    infoBtn.addEventListener("click", () => openFileInfo(file));
    actions.append(infoBtn);
  }
  li.append(actions);
  return li;
}

// ── Режим „папка“ (0.69.147) ─────────────────────────────────────────────
// Порталът е QR кодът, който води до ФАЙЛОВЕТЕ. Затова страницата има бутон, който
// показва съдържанието на собствената папка на портала. Заявките минават през
// key-защитения канал (`/api/hapi_enterprise/v1/p/<slug>/tree`), а ключът се носи в
// заглавие `X-Portal-Key` — НЕ в адреса: адресът се споделя, ключът не.

/** Подпапка: бутон, който влиза в нея (страницата не дава линкове). */
function folderRow(sub) {
  const li = document.createElement("li");
  li.className = "file";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "file-name file-folder";
  btn.textContent = "\uD83D\uDCC1 " + sub.name;
  btn.addEventListener("click", () => { void openFolder(sub.path); });
  li.append(btn);
  return li;
}

/** Файл от папката: име, размер, дата и бутон за сваляне по ПЪТ. */
function folderFileCard(file) {
  const li = document.createElement("li");
  li.className = "file";
  const head = document.createElement("div");
  head.className = "file-head";
  const glyph = document.createElement("span");
  glyph.className = "file-glyph";
  glyph.append(icon("file"));
  const title = document.createElement("h3");
  title.className = "file-name";
  title.textContent = file.name;
  head.append(glyph, title);
  li.append(head);

  const meta = document.createElement("ul");
  meta.className = "file-meta";
  meta.append(metaItem(T("files.col.size"), fmtSize(file.size)));
  const date = fmtDate(file.modifiedAt);
  if (date) meta.append(metaItem(T("files.col.changed"), date));
  li.append(meta);

  const actions = document.createElement("div");
  actions.className = "file-actions";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "btn btn-primary";
  btn.append(icon("download"), document.createTextNode(T("file.download")));
  btn.addEventListener("click", () => { void downloadFolderFile(file.path); });
  actions.append(btn);
  li.append(actions);
  return li;
}

/** Зарежда папка от портала. `rel` е относителна на корена на портала. */
async function loadFolder(rel) {
  setStatus(T("folder.loading"));
  try {
    const res = await fetch(apiBase + "/tree?path=" + encodeURIComponent("/" + rel), {
      headers: authHeaders(),
      referrerPolicy: "no-referrer",
    });
    if (!res.ok) {
      setStatus(T("file.status.http", { status: res.status }), "err");
      return false;
    }
    const data = await res.json().catch(() => null);
    if (!data || !Array.isArray(data.files)) {
      setStatus(T("folder.error"), "err");
      return false;
    }
    folderRel = String(rel || "");
    folderFiles = data.files.map((f) => ({ name: f.name, path: f.path, size: f.size, modifiedAt: f.modifiedAt }));
    folderSubs = Array.isArray(data.folders) ? data.folders.map((f) => ({ name: f.name, path: f.path })) : [];
    treeCurrent = String(rel || "");
    // Ново ниво: режимът „всичко“ се изключва, но зареденото дърво остава — секцията
    // „Структура на портала“ не бива да губи редовете и маркировката при навигация.
    showAll = false;
    const allBtn = $("tree-all");
    if (allBtn) {
      allBtn.hidden = false;
      allBtn.textContent = T("tree.all");
    }
    const head = $("files-title");
    if (head) head.textContent = T("folder.title", { path: "/" + (folderRel ? folderRel + "/" : "") });
    paint(qValue());
    setStatus("");
    return true;
  } catch {
    setStatus(T("file.status.offline"), "err");
    return false;
  }
}

/** Влиза в подпапка (същата страница, без смяна на адреса). */
async function openFolder(rel) {
  await loadFolder(rel);
}

/** Сваля файл от папката по ПЪТ (регистрираните файлове се свалят по id). */
async function downloadFolderFile(rel) {
  setStatus(T("file.status.downloading", { name: rel }));
  try {
    const res = await fetch(apiBase + "/tree/file?path=" + encodeURIComponent("/" + rel), {
      headers: authHeaders(),
      referrerPolicy: "no-referrer",
    });
    if (res.status === 403) {
      setStatus(T("file.locked"), "err");
      return;
    }
    if (!res.ok) {
      setStatus(T("file.status.http", { status: res.status }), "err");
      return;
    }
    const blob = await res.blob();
    const name = String(rel).split("/").pop() || "file";
    const link = document.createElement("a");
    const objectUrl = URL.createObjectURL(blob);
    link.href = objectUrl;
    link.download = name;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 30000);
    setStatus(T("file.status.started", { name }), "ok");
  } catch {
    setStatus(T("file.status.offline"), "err");
  }
}

/**
 * Копчето „Отвори папката“: превключва между папката на портала и регистрираните файлове.
 * Показва се само когато порталът НАИСТИНА има собствена папка (сървърът го обявява в
 * `urls.folders`), защото `/tree` за портал в общото хранилище отговаря 403.
 */
async function toggleFolder() {
  const btn = $("folder-open");
  const allBtn = $("tree-all");
  if (folderRel !== null) {
    folderRel = null;
    folderFiles = [];
    folderSubs = [];
    // Няма папка → няма и дърво за разгъване.
    treeRoot = null;
    showAll = false;
    if (allBtn) allBtn.hidden = true;
    if (btn) btn.textContent = T("header.folder");
    const head = $("files-title");
    if (head) head.textContent = prof && prof.total ? prof.noun.capMany : T("files.title.other");
    paint(qValue());
    return;
  }
  const ok = await loadFolder("");
  if (ok && btn) btn.textContent = T("folder.registered");
}

// ── Цялото дърво на портала (0.69.209) ────────────────────────────────────
// Порталът може да има папки в папки. За да не се рови папка по папка, дървото се обхожда
// с едни и същи заявки (`/tree?path=`) до дълбочината, която сървърът разрешава (3 нива),
// и се показва наведнъж, групирано по папка.

/** Обхожда дървото от корена на портала. Пази се веднъж — повторното натискане не пита. */
async function loadWholeTree() {
  if (treeRoot) return treeRoot;
  const MAX_DEPTH = 3; // договорът на сървъра: корен + 3 подпапки
  const fetchFolder = async (rel) => {
    const res = await fetch(apiBase + "/tree?path=" + encodeURIComponent("/" + rel), {
      headers: authHeaders(),
      referrerPolicy: "no-referrer",
    });
    if (!res.ok) return null;
    const data = await res.json().catch(() => null);
    if (!data || !Array.isArray(data.files)) return null;
    return {
      path: rel,
      files: data.files.map((f) => ({ name: f.name, path: f.path, size: f.size, modifiedAt: f.modifiedAt })),
      folders: (data.folders || []).map((f) => ({
        name: f.name,
        path: String(f.path || "").replace(/^\/+/, ""),
        files: [],
        folders: [],
      })),
    };
  };
  const walk = async (node, depth) => {
    if (depth >= MAX_DEPTH || !node.folders.length) return;
    for (const child of node.folders) {
      const full = await fetchFolder(child.path);
      if (!full) continue;
      child.files = full.files;
      child.folders = full.folders;
      await walk(child, depth + 1);
    }
  };
  const root = await fetchFolder("");
  if (!root) return null;
  await walk(root, 0);
  treeRoot = root;
  return treeRoot;
}

/** Файловете от ЦЯЛОТО дърво (за брояча в режим „покажи всичко“). */
function treeFilesAll(node) {
  const root = node || treeRoot;
  if (!root) return [];
  const out = [];
  const walk = (n) => {
    for (const f of n.files || []) out.push(f);
    for (const child of n.folders || []) walk(child);
  };
  walk(root);
  return out;
}

/** Редовете на „покажи всичко“: заглавие на папка, после файловете в нея. */
/**
 * Дървото на портала (секция „Структура на портала“): един ред на папка с броя файлове в
 * нея. Клик върху папка сменя текущия път на списъка — без отделна страница.
 */
function paintTree() {
  const list = $("tree-list");
  const panel = $("tree-panel");
  if (!list || !panel || !treeRoot) return;
  panel.hidden = false;
  list.replaceChildren();
  const active = treeCurrent;
  const row = (node, depth, isRoot) => {
    const li = document.createElement("li");
    li.className = "ptree-row";
    li.dataset.depth = String(depth);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-ghost ptree-btn";
    btn.title = node.path ? "/" + node.path : T("tree.root");
    btn.append(icon("folder"), document.createTextNode(isRoot ? T("tree.root") : node.name));
    const count = (node.files || []).length;
    if (count) {
      const badge = document.createElement("span");
      badge.className = "count";
      badge.textContent = String(count);
      btn.append(badge);
    }
    if (active === node.path) btn.classList.add("is-current");
    btn.addEventListener("click", () => void openTreeFolder(node.path));
    li.append(btn);
    list.append(li);
    for (const child of node.folders || []) row(child, depth + 1, false);
  };
  row(treeRoot, 0, true);
}

/** Зарежда цялото дърво (веднъж) и го рисува в секцията. `force` презарежда от сървъра. */
async function ensureTree(force) {
  const panel = $("tree-panel");
  if (!panel) return null;
  if (force) treeRoot = null;
  // Второ викане, докато първото още тече, чака СЪЩИЯ резултат — иначе дървото се строи два пъти.
  if (treePending) return treePending;
  const status = $("tree-status");
  if (status) {
    status.hidden = false;
    status.textContent = T("tree.loading");
  }
  treePending = (async () => {
    const root = await loadWholeTree();
    if (status) status.hidden = true;
    if (root) paintTree();
    return root;
  })().finally(() => {
    treePending = null;
  });
  return treePending;
}

/** Клик върху папка в дървото: показва съдържанието ѝ в секцията „Файлове“. */
async function openTreeFolder(rel) {
  const ok = await loadFolder(rel);
  if (!ok) return;
  const head = $("files-title");
  if (head && typeof head.scrollIntoView === "function") head.scrollIntoView({ block: "start" });
}

function paintAllRows() {
  const rows = [];
  const walk = (node) => {
    const files = node.files || [];
    if (files.length) {
      const head = document.createElement("li");
      head.className = "tree-group";
      const title = document.createElement("h3");
      title.textContent = node.path ? "/" + node.path : T("tree.root");
      head.append(title);
      rows.push(head);
      for (const f of files) rows.push(folderFileCard(f));
    }
    for (const child of node.folders || []) walk(child);
  };
  if (treeRoot) walk(treeRoot);
  return rows;
}

/** Числата на портала: смятат се от заредените данни и НЕ се пишат в HTML. */
function paintStats() {
  // В режим „папка“ списъкът е смесен: файловете от диска ПЛЮС регистрираните, които не са
  // в папката. В режим „покажи всичко“ се брои ЦЯЛОТО дърво — иначе картата казва едно,
  // а списъкът показва друго.
  let files = allFiles.length;
  if (folderRel !== null && showAll) files = treeFilesAll().length + allFiles.length;
  else if (folderRel !== null) {
    const onDisk = new Set(folderFiles.map((f) => f.name));
    files = folderFiles.length + allFiles.filter((f) => !onDisk.has(f.name)).length;
  }
  const hash = allFiles.filter((f) => f.sha256).length;
  const key = allFiles.filter((f) => f.accessMode === "KEY_REQUIRED").length;
  const set = (id, value) => {
    const el = $(id);
    if (el) el.textContent = String(value);
  };
  set("stat-files", files);
  set("stat-folders", folderRel !== null ? folderSubs.length : 0);
  set("stat-hash", hash);
  set("stat-key", key);
}

/** Статус на достъпа: състояние и броячи по режим на файловете. */
function paintAccess(data) {
  const state = $("access-state");
  const list = $("access-list");
  if (!state || !list) return;
  const total = prof ? prof.total : allFiles.length;
  const free = allFiles.filter((f) => !f.accessMode || f.accessMode === "FREE").length;
  const key = allFiles.filter((f) => f.accessMode === "KEY_REQUIRED").length;
  const disabled = allFiles.filter((f) => f.accessMode === "DISABLED").length;
  const isPublic = Boolean(data && data.visibility === "public");
  state.textContent = isPublic ? T("access.public.chip") : T("access.key.chip");
  state.className = "chip " + (isPublic ? "chip-ok" : "chip-warn");
  const items = [];
  if (!total) items.push(T("access.none"));
  else {
    items.push(T("access.free.count", { n: free }));
    if (key) items.push(T("access.key.count", { n: key }));
    if (disabled) items.push(T("access.disabled.count", { n: disabled }));
  }
  list.replaceChildren(
    ...items.map((value) => {
      const li = document.createElement("li");
      li.className = "chip";
      li.textContent = value;
      return li;
    }),
  );
}

/** Един ред „етикет: стойност“ в листа за ЕДИН файл. */
function fiRow(list, label, value, opts) {
  if (!list) return;
  const dt = document.createElement("dt");
  dt.textContent = label;
  const dd = document.createElement("dd");
  if (opts && opts.mono) dd.className = "mono";
  if (isNode(value)) dd.append(value);
  else dd.textContent = String(value == null || value === "" ? "—" : value);
  list.append(dt, dd);
}

/** Лист с подробности за ЕДИН файл — на място, без отделна страница. */
function openFileInfo(file) {
  const box = $("file-info");
  if (!box || !file) return;
  const general = $("fi-general");
  const integrity = $("fi-integrity");
  if (general) general.replaceChildren();
  if (integrity) integrity.replaceChildren();
  const name = $("file-info-name");
  if (name) name.textContent = file.name;
  fiRow(general, T("fileinfo.size"), fmtSize(file.size));
  const date = fmtDate(file.uploadedAt);
  if (date) fiRow(general, T("fileinfo.date"), date);
  if (Number(file.version) > 1) fiRow(general, T("fileinfo.version"), String(file.version));
  const tax = [file.topic, file.category, file.group].filter(Boolean).join(" · ");
  if (tax) fiRow(general, T("fileinfo.taxonomy"), tax);
  fiRow(
    general,
    T("fileinfo.mode"),
    file.accessMode === "KEY_REQUIRED" ? T("file.meta.key") : file.accessMode === "DISABLED" ? T("access.disabled") : T("access.free"),
  );
  fiRow(integrity, T("fileinfo.algorithm"), "SHA-256");
  fiRow(integrity, T("fileinfo.encrypted"), file.encrypted ? T("fileinfo.yes") : T("fileinfo.no"));
  const hashEl = $("fi-hash");
  if (hashEl) {
    hashEl.textContent = file.sha256 ? T("file.sha.label", { short: short(file.sha256, 32) }) : T("fileinfo.noHash");
    hashEl.title = file.sha256 ? T("file.sha.title", { full: file.sha256 }) : "";
  }
  const result = $("fi-result");
  if (result) {
    result.hidden = true;
    result.textContent = "";
    result.dataset.kind = "";
  }
  const btn = $("fi-verify");
  if (btn) {
    // Файл с ключ и забранен файл не се проверяват без ключ — бутонът се СКРИВА.
    const canVerify = Boolean(file.sha256) && file.accessMode !== "KEY_REQUIRED" && file.accessMode !== "DISABLED";
    btn.hidden = !canVerify;
    btn.disabled = false;
    btn.onclick = () => void verifyFile(file);
  }
  box.hidden = false;
  const close = $("file-info-close");
  if (close) close.focus();
}

/** Затваря листа с информацията за файла. */
function closeFileInfo() {
  const box = $("file-info");
  if (box) box.hidden = true;
}

/** Сверка на отпечатъка на ЖИВИТЕ байтове: същият SHA-256, който би се свалил. */
async function verifyFile(file) {
  const result = $("fi-result");
  const btn = $("fi-verify");
  const say = (text, kind) => {
    if (!result) return;
    result.hidden = !text;
    result.textContent = text || "";
    result.dataset.kind = kind || "";
  };
  if (!(crypto && crypto.subtle && crypto.subtle.digest)) {
    say(T("fileinfo.noCrypto"));
    return;
  }
  if (btn) btn.disabled = true;
  say(T("fileinfo.verifying"));
  try {
    const res = await fetch(apiBase + "/files/" + encodeURIComponent(file.id) + "/download", {
      headers: authHeaders(),
      referrerPolicy: "no-referrer",
    });
    if (!res.ok) {
      say(T("file.status.http", { status: res.status }), "err");
      return;
    }
    const actual = await sha256Hex(await res.arrayBuffer());
    if (actual === String(file.sha256 || "").toLowerCase()) say(T("fileinfo.match"), "ok");
    else say(T("fileinfo.mismatch"), "err");
  } catch {
    say(T("fileinfo.error"), "err");
  } finally {
    if (btn) btn.disabled = false;
  }
}

/** Бързата лента се връзва веднъж; всяко бутонче прави истинско действие. */
function wireQuickBar() {
  if (barWired) return;
  barWired = true;
  wireSheets();
  const top = $("bar-top");
  if (top) top.addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));
  const search = $("bar-search");
  if (search)
    search.addEventListener("click", () => {
      const q = $("q");
      if (!q) return;
      q.focus();
      if (q.scrollIntoView) q.scrollIntoView({ block: "center" });
    });
  const api = $("bar-info");
  if (api) api.addEventListener("click", () => void openInfo("api"));
  const manifest = $("bar-manifest");
  if (manifest) manifest.addEventListener("click", () => void openInfo("manifest"));
  const close = $("file-info-close");
  if (close) close.addEventListener("click", closeFileInfo);
  // „Покажи всичко“ / „Само тази папка“: един бутон, който сменя обхвата на списъка.
  const all = $("tree-all");
  if (all)
    all.addEventListener("click", () => {
      void (async () => {
        if (!showAll) {
          setStatus(T("tree.loading"));
          await loadWholeTree();
        }
        showAll = !showAll;
        paint(qValue());
      })();
    });
  const refresh = $("tree-refresh");
  if (refresh) refresh.addEventListener("click", () => void ensureTree(true));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (anySheetOpen()) {
        for (const id of ["info-sheet", "access-sheet"]) closeSheet(id);
      } else {
        closeFileInfo();
      }
    }
  });
}

/** Показва файловете, които отговарят на търсенето (по име, тема, категория, група). */
function paint(filter) {
  // Броячите и статусът на достъпа следват списъка: в режим „папка“ числата са други.
  paintStats();
  paintAccess(portal);
  const q = String(filter || "").trim().toLocaleLowerCase();
  const box = $("files");
  const allBtn = $("tree-all");
  if (allBtn && folderRel !== null) allBtn.textContent = showAll ? T("tree.level") : T("tree.all");
  // „Покажи всичко“: всички нива на портала наведнъж, групирани по папка.
  if (folderRel !== null && showAll) {
    const rows = paintAllRows();
    box.replaceChildren(...rows);
    $("empty").hidden = rows.length > 0;
    if (!rows.length) $("empty").textContent = T("folder.empty");
    const all = treeFilesAll();
    $("count").textContent = all.length + " " + nounFor(all.length, prof ? prof.noun : NOUNS.file);
    if (rows.length) setStatus("");
    return;
  }
  // Режим „папка“: истинските файлове от папката на портала. Регистрираните остават втори
  // изглед — бутонът връща към тях, за да не се губи нищо, което издателят е обявил.
  if (folderRel !== null) {
    const files = q ? folderFiles.filter((f) => String(f.name).toLocaleLowerCase().includes(q)) : folderFiles;
    const subs = q ? [] : folderSubs;
    const rows = subs.map(folderRow).concat(files.map(folderFileCard));
    box.replaceChildren(...rows);
    $("empty").hidden = rows.length > 0;
    if (!rows.length) $("empty").textContent = T("folder.empty");
    // Броят разделя файлове от папки: иначе една папка се чете като „1 файл“.
    const parts = [T("file.count", { n: files.length, what: nounFor(files.length, nounOf("file")) })];
    if (subs.length) parts.push(T("folder.count", { n: subs.length }));
    $("count").textContent = parts.join(" · ");
    if (!files.length && subs.length) setStatus(T("folder.onlyFolders", { n: subs.length }));
    else if (rows.length) setStatus("");
    return;
  }
  const list = q
    ? allFiles.filter((f) =>
      [f.name, f.topic, f.category, f.group, (f.tags || []).join(" ")]
        .join(" ")
        .toLocaleLowerCase()
        .includes(q),
    )
    : allFiles;
  box.replaceChildren(...list.map(fileCard));
  $("empty").hidden = list.length > 0;
  if (!list.length) {
    // Различен текст за празен портал и за празно търсене.
    $("empty").textContent = allFiles.length
      ? T("files.empty.filtered", { what: prof.noun.many })
      : prof.isPublic
        ? T("files.empty.public")
        : T("files.empty.private");
  }
  const total = allFiles.length;
  $("count").textContent = !total
    ? ""
    : list.length === total
      ? total + " " + nounFor(total, prof.noun)
      : list.length + " " + T("files.count.of") + " " + total;
  if (list.length || !total) setStatus("");
}

// ── Информация В страницата (PP-04) ─────────────────────────────────────────
// Дотук „API“ и „Манифест“ бяха линкове към суров JSON в нов таб: посетителят излизаше
// от портала, за да види какво има в него. Сега същото съдържание се разгъва ТУК, с
// четими етикети и без адреси за копиране.
let infoKind = "";
let infoWired = false;

/** Възел ли е стойността (така `<dd>` може да носи и бутон, не само текст). */
const isNode = (value) => Boolean(value) && typeof value === "object" && typeof value.nodeType === "number";

/** Един ред „етикет: стойност“ в панела с информация. */
function infoRow(label, value, opts) {
  const list = $("doc-info-body");
  if (!list) return;
  const dt = document.createElement("dt");
  dt.textContent = label;
  const dd = document.createElement("dd");
  if (opts && opts.mono) dd.className = "mono";
  if (isNode(value)) dd.append(value);
  else dd.textContent = String(value == null || value === "" ? "—" : value);
  list.append(dt, dd);
}

/** Бутон за копиране на стойност, която не се изписва на страницата. */
function copyButton(value, label, okText) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "btn btn-ghost btn-sm";
  btn.textContent = label;
  btn.addEventListener("click", () => copy(value, okText));
  return btn;
}

/** Какво знае страницата за самия портал — без адреси и без JSON. */
function renderApiInfo() {
  const data = portal || {};
  const total = prof ? prof.total : allFiles.length;
  const noun = prof ? prof.noun : nounOf("file");
  const bytes = allFiles.reduce((sum, f) => sum + (Number(f.size) || 0), 0);
  infoRow(T("info.label.title"), data.title || T("doc.title"));
  infoRow(T("info.label.id"), data.id || "", { mono: true });
  infoRow(T("info.label.slug"), data.slug || "");
  infoRow(T("info.label.visibility"), data.visibility === "public" ? T("access.public") : T("access.private"));
  infoRow(T("info.label.content"), total + " " + nounFor(total, noun) + " · " + fmtSize(bytes));
  const c = data.contact || null;
  const who = c ? [c.name, c.organization, c.department].filter(Boolean).join(" · ") : "";
  if (who) infoRow(T("info.label.contact"), who);
  const created = fmtDate(data.createdAt);
  if (created) infoRow(T("info.label.created"), created);
  const updated = fmtDate(data.updatedAt);
  if (updated) infoRow(T("info.label.updated"), updated);
}

/** Манифест: сървърът дава пътища, размери и отпечатъци — показваме тях, не адреси. */
async function renderManifestInfo() {
  const status = $("doc-info-status");
  let data = null;
  try {
    const res = await fetch(apiBase + "/manifest", { headers: authHeaders(), referrerPolicy: "no-referrer" });
    if (res.ok) data = await res.json();
  } catch {
    data = null;
  }
  // Затворен или сменен, докато зареждаше — не рисуваме върху чуждо съдържание.
  if (infoKind !== "manifest") return;
  if (status) {
    status.hidden = true;
    status.textContent = "";
  }
  const list = $("doc-info-body");
  if (list) list.replaceChildren();
  if (!data || !Array.isArray(data.files)) {
    if (status) {
      status.hidden = false;
      status.textContent = T("info.error");
    }
    return;
  }
  const storage = data.storage || {};
  infoRow(T("info.label.folders"), Number(storage.folderCount) || 0);
  infoRow(T("info.label.files"), Number(storage.fileCount) || data.files.length);
  for (const f of data.files) {
    const mode =
      f.accessMode === "KEY_REQUIRED" ? T("access.key") : f.accessMode === "DISABLED" ? T("access.disabled") : T("access.free");
    const detail = document.createElement("span");
    detail.className = "info-value";
    detail.append(document.createTextNode([f.path || "", fmtSize(f.size), mode].filter(Boolean).join(" · ")));
    if (f.sha256) {
      const hash = document.createElement("code");
      hash.className = "mono";
      hash.title = T("file.sha.title", { full: f.sha256 });
      hash.textContent = T("file.sha.label", { short: short(f.sha256, 16) });
      detail.append(document.createTextNode(" "), hash, copyButton(f.sha256, T("file.sha.copy"), T("file.sha.copied")));
    }
    infoRow(f.name || "", detail);
  }
}

/** Затваря панела с информация и връща бутоните в спокойно състояние. */
function closeInfo() {
  infoKind = "";
  const box = $("doc-info");
  if (box) box.hidden = true;
  for (const id of ["api-open", "manifest-open"]) {
    const btn = $(id);
    if (btn) btn.setAttribute("aria-expanded", "false");
  }
}

// ── Прозорци: страницата показва ДВЕТЕ секции, всичко останало се отваря като лист ────
/** Отваря лист по id и вдига `aria-expanded` на бутона, който го е отворил. */
function openSheet(id, opener) {
  const sheet = $(id);
  if (!sheet) return;
  const wasOpen = !sheet.hidden;
  sheet.hidden = false;
  if (opener) opener.setAttribute("aria-expanded", "true");
  if (wasOpen) return;
  const first = typeof sheet.querySelector === "function" ? sheet.querySelector("button, input, select") : null;
  if (first && typeof first.focus === "function") first.focus();
}

/** Затваря лист по id и връща неговите отварящи бутони в спокойно състояние. */
function closeSheet(id) {
  const sheet = $(id);
  if (!sheet || sheet.hidden) return;
  sheet.hidden = true;
  if (typeof document.querySelectorAll !== "function") return;
  for (const opener of document.querySelectorAll('[aria-controls="' + id + '"]')) {
    opener.setAttribute("aria-expanded", "false");
  }
}

/** Има ли отворен прозорец (за Escape). */
function anySheetOpen() {
  return ["info-sheet", "access-sheet"].some((id) => {
    const sheet = $(id);
    return Boolean(sheet) && !sheet.hidden;
  });
}

/** Връзва прозорците: бутоните в заглавната част, затварянето и кликът извън картата. */
function wireSheets() {
  const bind = (btnId, act) => {
    const btn = $(btnId);
    if (btn) btn.addEventListener("click", act);
  };
  bind("info-open", () => openSheet("info-sheet", $("info-open")));
  bind("access-open", () => openSheet("access-sheet", $("access-open")));
  bind("info-sheet-close", () => closeSheet("info-sheet"));
  bind("access-sheet-close", () => closeSheet("access-sheet"));
  for (const id of ["info-sheet", "access-sheet"]) {
    const sheet = $(id);
    if (!sheet) continue;
    sheet.addEventListener("click", (e) => {
      if (e.target === sheet) closeSheet(id);
    });
  }
}

/** Разгъва информацията за портала или за манифеста — в прозореца „Информация“. */
async function openInfo(kind) {
  const box = $("doc-info");
  if (!box) return;
  if (infoKind === kind && !box.hidden) {
    closeInfo();
    return;
  }
  openSheet("info-sheet", $("info-open"));
  infoKind = kind;
  box.hidden = false;
  const isApi = kind === "api";
  const apiBtn = $("api-open");
  const manifestBtn = $("manifest-open");
  if (apiBtn) apiBtn.setAttribute("aria-expanded", isApi ? "true" : "false");
  if (manifestBtn) manifestBtn.setAttribute("aria-expanded", isApi ? "false" : "true");
  $("doc-info-title").textContent = isApi ? T("info.api.title") : T("info.manifest.title");
  $("doc-info-note").textContent = isApi ? T("info.api.note") : T("info.manifest.note");
  const status = $("doc-info-status");
  if (status) {
    status.hidden = true;
    status.textContent = "";
  }
  const body = $("doc-info-body");
  if (body) body.replaceChildren();
  if (isApi) renderApiInfo();
  else {
    if (status) {
      status.hidden = false;
      status.textContent = T("info.loading");
    }
    await renderManifestInfo();
  }
  if (typeof box.scrollIntoView === "function") box.scrollIntoView({ block: "nearest" });
}

function paintPortal(data) {
  const base = data.title || T("doc.title");
  // Заглавието на раздела назовава артефактите само когато има такива.
  document.title = prof && prof.total ? base + " · " + prof.noun.for : base;
  const titleEl = $("title");
  if (titleEl) titleEl.textContent = data.title || T("doc.title");
  const desc = String(data.description || data.subject || "").trim();
  const descEl = $("description");
  if (descEl) {
    descEl.textContent = desc;
    descEl.hidden = !desc;
  }

  const badges = [];
  if (data.visibility === "public") badges.push([T("badge.public"), "chip-ok"]);
  if (data.category) badges.push([data.category, ""]);
  if (data.flag && data.flag !== "none") {
    const label = { info: T("flag.info"), important: T("flag.important"), urgent: T("flag.urgent"), archive: T("flag.archive") }[data.flag] || data.flag;
    badges.push([label, data.flag === "urgent" ? "chip-err" : "chip-warn"]);
  }
  const ul = $("badges");
  ul.replaceChildren(
    ...badges.map(([text, cls]) => {
      const li = document.createElement("li");
      li.className = ("chip " + (cls || "")).trim();
      li.textContent = text;
      return li;
    }),
  );

  const c = data.contact;
  if (c && (c.name || c.organization || c.email || c.phone)) {
    const parts = [c.name, c.organization, c.department].filter(Boolean).join(" · ");
    const el = $("contact");
    el.replaceChildren();
    if (parts) el.append(document.createTextNode(parts));
    if (c.email) {
      const mail = document.createElement("button");
      mail.type = "button";
      mail.className = "link-btn";
      mail.textContent = c.email;
      mail.title = T("contact.mail");
      mail.addEventListener("click", () => { location.href = "mailto:" + c.email; });
      el.append(document.createTextNode(parts ? " · " : ""), mail);
    }
    if (c.phone) {
      const tel = document.createElement("button");
      tel.type = "button";
      tel.className = "link-btn";
      tel.textContent = c.phone;
      tel.title = T("contact.tel");
      tel.addEventListener("click", () => { location.href = "tel:" + c.phone.replace(/[^+0-9]/g, ""); });
      el.append(document.createTextNode(c.email || parts ? " · " : ""), tel);
    }
    el.hidden = false;
  }

  // PP-04: API и Манифест са бутони, които разгъват информацията в СТРАНИЦАТА.
  if (!infoWired) {
    infoWired = true;
    const apiBtn = $("api-open");
    const manifestBtn = $("manifest-open");
    const closeBtn = $("doc-info-close");
    if (apiBtn) apiBtn.addEventListener("click", () => void openInfo("api"));
    if (manifestBtn) manifestBtn.addEventListener("click", () => void openInfo("manifest"));
    if (closeBtn) closeBtn.addEventListener("click", closeInfo);
  }
  wireQuickBar();
  $("copy-link").addEventListener("click", () => copy(pageUrl(), T("header.copyLink.ok")));
  // Копчето към ПАПКАТА: порталът е QR кодът, който води до файловете — затова страницата
  // има директен вход към папката на портала. Показва се, когато порталът има собствена
  // папка (сървърът я обявява чрез `FOLDERS`).
  const folderBtn = $("folder-open");
  if (folderBtn) {
    // Копчето се показва само когато порталът НАИСТИНА има собствена папка — сървърът го
    // обявява в `urls.folders` (`'1'`). Натискането показва съдържанието на папката В
    // СТРАНИЦАТА: посетителят не сменя адрес и ключът не влиза в него.
    const urls = data.urls || {};
    const hasFolder = String(urls.folders || "") === "1";
    folderBtn.hidden = !hasFolder;
    if (hasFolder && !folderBtn.dataset.wired) {
      folderBtn.dataset.wired = "1";
      folderBtn.addEventListener("click", () => { void toggleFolder(); });
    }
  }
}

(async () => {
  try {
    if (!key) throw new Error(T("error.noPortal"));
    const [portalRes, filesRes] = await Promise.all([
      fetch(apiBase, { headers: authHeaders(), referrerPolicy: "no-referrer" }),
      fetch(apiBase + "/files?limit=" + MAX_LISTED, { headers: authHeaders(), referrerPolicy: "no-referrer" }),
    ]);
    if (!portalRes.ok) throw new Error(T("error.portal"));
    if (!filesRes.ok) throw new Error(T("error.files"));
    portal = await portalRes.json();
    const listing = await filesRes.json();
    allFiles = Array.isArray(listing.files) ? listing.files : [];
    prof = buildProfile(allFiles, portal);
    paintPortal(portal);
    applyWording(prof);
    paint("");
    // Секцията „Структура на портала“ се пълни само когато порталът има собствена папка —
    // `/tree` за портал в общото хранилище отговаря 403. Самата папка НЕ се отваря: в
    // интеграцията посетителят влиза с бутона „Отвори папката“.
    if (portal && String((portal.urls || {}).folders || "") === "1") await ensureTree();
    if (listing.hasMore) {
      const more = $("more");
      more.textContent = T("files.more", { shown: MAX_LISTED, total: listing.total, what: nounFor(listing.total, prof.noun) });
      more.hidden = false;
    }
  } catch (err) {
    setStatus(String(err && err.message ? err.message : err), "err");
    const titleEl = $("title");
    if (titleEl) titleEl.textContent = T("doc.unavailable");
  }
})();

// Частична страница може да няма поле за търсене — тогава няма какво да се връзва.
const searchBox = $("q");
if (searchBox) searchBox.addEventListener("input", (e) => paint(e.target.value));

// PP-04: „Към файловете“ е бутон — мести фокуса върху списъка, без да пипа адреса.
const skipButton = $("skip");
if (skipButton) {
  skipButton.addEventListener("click", () => {
    const target = $("files-title") || $("files");
    if (!target) return;
    if (typeof target.focus === "function") {
      target.setAttribute("tabindex", "-1");
      target.focus();
    }
    if (typeof target.scrollIntoView === "function") target.scrollIntoView({ block: "start" });
  });
}

// PP-14: изборът на език е на посетителя — помни се и се прилага веднага, без презареждане.
// `applyLanguage()` се вика и при старт, за да дойде езикът от адреса/запазения избор, а не
// само от `lang` на страницата.
const langSelect = $("lang");
if (langSelect) {
  langSelect.value = LANG;
  langSelect.addEventListener("change", (event) => {
    const next = I18N && I18N.isLang(event.target.value) ? I18N.pick(event.target.value) : "bg";
    if (next === LANG) return;
    LANG = next;
    try {
      localStorage.setItem(LANG_KEY, LANG);
    } catch {
      // Частен режим без хранилище: изборът важи до затваряне на страницата.
    }
    applyLanguage();
  });
}
applyLanguage();
