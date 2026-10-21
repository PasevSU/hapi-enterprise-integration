"use strict";
// Публична страница на портала, сервирана от Home Assistant интеграцията.
//
// Същата адаптивна страница като в add-on-а (текстовете зависят от артефактите:
// документи / снимки / файлове, търсене, QR, SHA-256, изтегляне с ключ), но заявките
// минават през fail-closed моста на интеграцията (`/api/hapi_enterprise/v1/p/<id>`).
//
// Сигурност: ключът на портала НЕ влиза в адреса на заявката — държи се във фрагмента
// на страницата (`#token=…`) и се праща само като `X-Portal-Key`. Всички стойности се
// вмъкват с textContent (без innerHTML), за да не може име на файл да инжектира HTML.

const $ = (id) => document.getElementById(id);
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
let portal = null;
let allFiles = [];
// Профил на съдържанието — всички текстове на страницата се извеждат от него.
let prof = null;

const setStatus = (text, kind) => {
  const el = $("status");
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

/** Съществителни за всеки вид (български: 1 файл / 2 файла) — с форми за „за …“. */
const NOUNS = {
  file: { one: "файл", many: "файла", capMany: "Файлове", for: "файлове" },
  doc: { one: "документ", many: "документа", capMany: "Документи", for: "документи" },
  image: { one: "снимка", many: "снимки", capMany: "Снимки", for: "снимки" },
  media: { one: "медиен файл", many: "медийни файла", capMany: "Медия", for: "медия" },
  archive: { one: "архив", many: "архива", capMany: "Архиви", for: "архиви" },
  mixed: { one: "файл", many: "файла", capMany: "Документи и снимки", for: "документи и снимки" },
};
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
    noun: NOUNS[key],
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
    ? "Портал за " + noun.for
    : p.isPublic
      ? "Публичен портал"
      : "Портал с ограничен достъп";
  $("files-title").textContent = hasFiles ? noun.capMany : "Съдържание";

  // Прескачането към списъка има смисъл само когато има списък.
  const skip = $("skip");
  skip.textContent = hasFiles ? "Към " + noun.for : "Към съдържанието";
  skip.hidden = !hasFiles;

  // Търсенето се показва само когато има какво да се търси, а подсказката —
  // само по полетата, които наистина съществуват в тези файлове.
  $("toolbar").hidden = p.total <= 3;
  $("q").placeholder = p.hasTags
    ? "Търси по име, тема, категория или етикет"
    : p.hasTax
      ? "Търси по име, тема или категория"
      : "Търси по име";
  $("q-label").textContent = $("q").placeholder;

  // Бележки под QR кода — само за неща, които са налични в портала.
  const notes = [];
  if (p.allHash) notes.push("Всеки файл носи SHA-256 отпечатък — сверявай го след изтегляне.");
  else if (p.hasHash) notes.push("Показаните отпечатъци са SHA-256 — сверявай ги след изтегляне.");
  if (p.hasKey) notes.push("Файловете с ключ се отварят само с ключа, издаден от издателя.");
  if (p.allDisabled) notes.push("Издателят е спрял изтеглянето на всички файлове в портала.");
  const note = $("qr-note");
  note.textContent = notes.join(" ");
  note.hidden = notes.length === 0;

  $("qr-hint").textContent =
    p.isPublic && !token
      ? "Сканирай кода, за да отвориш портала на друго устройство."
      : "Сканирай кода или сподели адреса — за този портал е нужен ключ от издателя.";

  const details = [];
  if (hasFiles) details.push(p.total + " " + nounFor(p.total, noun));
  if (p.newest) details.push("обновено на " + fmtDate(p.newest.toISOString()));
  details.push("съдържанието е собственост на издателя");
  const strong = document.createElement("strong");
  strong.textContent = "hAPI Enterprise";
  $("foot-note").replaceChildren(
    document.createTextNode("Порталът се обслужва от "),
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
    setStatus(okText || "Копирано.", "ok");
  } catch {
    setStatus("Копирането не е позволено от браузъра.", "err");
  }
}

/** Малка икона (вграден SVG — без шрифт-икони и без мрежови заявки). */
function icon(name) {
  const paths = {
    download: '<path d="M12 3.5v11"/><path d="M7.5 10L12 14.5 16.5 10"/><path d="M4.5 20h15"/>',
    copy: '<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 5.5h-9a2 2 0 0 0-2 2v9"/>',
    lock: '<rect x="4.6" y="10.6" width="14.8" height="9.4" rx="2"/><path d="M8.2 10.6V7.6a3.8 3.8 0 0 1 7.6 0v3"/>',
    file: '<path d="M6 3.4h8.2l3.8 3.8v13.4H6z"/><path d="M14 3.6v3.8h3.8"/>',
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

/** Изтегляне: FREE → директно; KEY_REQUIRED → с ключ в X-File-Key. */
async function downloadFile(file, key) {
  setStatus("Изтегляне на „" + file.name + "“…");
  try {
    const headers = authHeaders(key ? { "X-File-Key": key } : {});
    const url = apiBase + "/files/" + encodeURIComponent(file.id) + "/download";
    const res = await fetch(url, { headers, referrerPolicy: "no-referrer" });
    if (res.status === 403) {
      setStatus(key ? "Невалиден или изтекъл ключ за този файл." : "Нужен е ключ за този файл.", "err");
      return;
    }
    if (!res.ok) {
      setStatus("Изтеглянето не бе успешно (HTTP " + res.status + ").", "err");
      return;
    }
    const blob = await res.blob();
    const link = document.createElement("a");
    const objectUrl = URL.createObjectURL(blob);
    link.href = objectUrl;
    link.download = file.name;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 30000);
    setStatus("Изтеглянето започна: " + file.name, "ok");
  } catch {
    setStatus("Няма връзка със сървъра на портала.", "err");
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
  meta.append(metaItem("", fmtSize(file.size)));
  if (Number(file.version) > 1) meta.append(metaItem("v", String(file.version)));
  const date = fmtDate(file.uploadedAt);
  if (date) meta.append(metaItem("", date));
  if (file.encrypted) meta.append(metaItem("", "шифрован"));
  if (file.accessMode === "KEY_REQUIRED") meta.append(metaItem("", "нужен е ключ"));
  li.append(meta);

  if (file.sha256) {
    const hash = document.createElement("p");
    hash.className = "file-hash";
    hash.title = "SHA-256: " + file.sha256;
    const label = document.createElement("span");
    label.className = "mono";
    label.textContent = "SHA-256 " + short(file.sha256, 16);
    const copyBtn = document.createElement("button");
    copyBtn.type = "button";
    copyBtn.className = "icon-btn";
    copyBtn.title = "Копирай пълния SHA-256";
    copyBtn.setAttribute("aria-label", "Копирай SHA-256 за " + file.name);
    copyBtn.append(icon("copy"));
    copyBtn.addEventListener("click", () => copy(file.sha256, "SHA-256 е копиран."));
    hash.append(label, copyBtn);
    li.append(hash);
  }

  const actions = document.createElement("div");
  actions.className = "file-actions";
  if (file.accessMode === "DISABLED") {
    const blocked = document.createElement("span");
    blocked.className = "chip chip-warn";
    blocked.textContent = "Изтеглянето е забранено от издателя";
    actions.append(blocked);
  } else if (file.accessMode === "KEY_REQUIRED") {
    const input = document.createElement("input");
    input.type = "password";
    input.autocomplete = "off";
    input.className = "key-input";
    input.placeholder = "Ключ за файла";
    input.setAttribute("aria-label", "Ключ за " + file.name);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-primary";
    btn.append(icon("lock"), document.createTextNode(" Изтегли с ключ"));
    btn.addEventListener("click", () => downloadFile(file, input.value.trim()));
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") downloadFile(file, input.value.trim());
    });
    actions.append(input, btn);
  } else {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-primary";
    btn.append(icon("download"), document.createTextNode(" Изтегли"));
    btn.addEventListener("click", () => downloadFile(file, ""));
    actions.append(btn);
  }
  li.append(actions);
  return li;
}

/** Показва файловете, които отговарят на търсенето (по име, тема, категория, група). */
function paint(filter) {
  const q = String(filter || "").trim().toLocaleLowerCase();
  const list = q
    ? allFiles.filter((f) =>
        [f.name, f.topic, f.category, f.group, (f.tags || []).join(" ")]
          .join(" ")
          .toLocaleLowerCase()
          .includes(q),
      )
    : allFiles;
  const box = $("files");
  box.replaceChildren(...list.map(fileCard));
  $("empty").hidden = list.length > 0;
  if (!list.length) {
    // Различен текст за празен портал и за празно търсене.
    $("empty").textContent = allFiles.length
      ? "Няма " + prof.noun.for + ", отговарящи на търсенето."
      : prof.isPublic
        ? "Порталът е публичен, но издателят още не е публикувал файлове."
        : "Издателят още не е публикувал файлове в този портал.";
  }
  const total = allFiles.length;
  $("count").textContent = !total
    ? ""
    : list.length === total
      ? total + " " + nounFor(total, prof.noun)
      : list.length + " от " + total;
  if (list.length || !total) setStatus("");
}

function paintPortal(data) {
  const base = data.title || "Портал за документи";
  // Заглавието на раздела назовава артефактите само когато има такива.
  document.title = prof && prof.total ? base + " · " + prof.noun.for : base;
  $("title").textContent = data.title || "Портал за документи";
  const desc = String(data.description || data.subject || "").trim();
  $("description").textContent = desc;
  $("description").hidden = !desc;

  const badges = [];
  if (data.visibility === "public") badges.push(["Публичен", "chip-ok"]);
  if (data.category) badges.push([data.category, ""]);
  if (data.flag && data.flag !== "none") {
    const label = { info: "информация", important: "важно", urgent: "спешно", archive: "архив" }[data.flag] || data.flag;
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
      const a = document.createElement("a");
      a.href = "mailto:" + c.email;
      a.textContent = c.email;
      el.append(document.createTextNode(parts ? " · " : ""), a);
    }
    if (c.phone) {
      const a = document.createElement("a");
      a.href = "tel:" + c.phone.replace(/[^+0-9]/g, "");
      a.textContent = c.phone;
      el.append(document.createTextNode(c.email || parts ? " · " : ""), a);
    }
    el.hidden = false;
  }

  // Препратките се строят от адреса на моста, не от стойностите в отговора на add-on-а
  // (те сочат публичния порт 8099, който тук не е достъпен).
  $("api-link").href = apiBase;
  $("manifest-link").href = apiBase + "/manifest";
  $("qr").src = apiBase + "/qr.svg";
  $("portal-url").textContent = pageUrl();
  $("copy-link").addEventListener("click", () => copy(pageUrl(), "Адресът на портала е копиран."));
}

(async () => {
  try {
    if (!key) throw new Error("Липсва портал в адреса.");
    const [portalRes, filesRes] = await Promise.all([
      fetch(apiBase, { headers: authHeaders(), referrerPolicy: "no-referrer" }),
      fetch(apiBase + "/files?limit=" + MAX_LISTED, { headers: authHeaders(), referrerPolicy: "no-referrer" }),
    ]);
    if (!portalRes.ok) throw new Error("Порталът не е наличен или достъпът изисква ключ.");
    if (!filesRes.ok) throw new Error("Списъкът с файлове не е достъпен.");
    portal = await portalRes.json();
    const listing = await filesRes.json();
    allFiles = Array.isArray(listing.files) ? listing.files : [];
    prof = buildProfile(allFiles, portal);
    paintPortal(portal);
    applyWording(prof);
    paint("");
    if (listing.hasMore) {
      const more = $("more");
      more.textContent =
        "Показани са първите " +
        MAX_LISTED +
        " от " +
        listing.total +
        " " +
        nounFor(listing.total, prof.noun) +
        " — използвай търсенето или API-то за останалите.";
      more.hidden = false;
    }
  } catch (err) {
    setStatus(String(err && err.message ? err.message : err), "err");
    $("title").textContent = "Порталът не е достъпен";
  }
})();

$("q").addEventListener("input", (e) => paint(e.target.value));
