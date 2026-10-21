# Changelog — hAPI Enterprise

Всички забележими промени в add-on-а (`hapi_enterprise`) и в custom интеграцията
(`custom_components/hapi_enterprise`). Версията има един източник на истина —
`hapi_enterprise/config.yaml`; `manifest.json` трябва да носи същата стойност.

## 0.62.0

### „Бърз линк“ (Send-lite) — публичен достъп до един файл

- **Нов модул `hapi_enterprise/send.js`** — непрозрачен id (22 знака, Crockford base32),
  парола по избор (scrypt + сол), срок, лимит на свалянията и отмяна.
  **По подразбиране линкът е безсрочен** — както порталите; срокът е опция, не задължение.
- **Няма дълготраен токен в URL.** Изтеглянето минава през еднократен билет с TTL 60 s,
  издаден след проверка на паролата; страницата `/s/<id>` е без JS и работи под строга CSP.
- Маршрути: `POST|GET /admin/api/portals/:id/files/:fileId/sends`,
  `DELETE .../sends/:sendId`, `GET /s/<id>`, `POST /api/v1/sends/:id/access`,
  `GET /api/v1/sends/:id/file?ticket=`.
- Ограничение на опитите с грешна парола: 5 за 15 минути на двойка (линк, IP).
- Линкът не показва подател или имейл; `Referrer-Policy: no-referrer` и `no-store` навсякъде.
- Административният панел получава секция „Бърз линк“ до всеки файл: срок
  (Без срок / 24 ч / 7 / 30 / 90 дни), лимит (1 / 5 / без ограничение), парола (по избор),
  копиране на адреса и списък с активните линкове с копче „Отмени“.
- `tests/send.cjs` покрива: безсрочност по подразбиране, еднократност на билета,
  грешна/вярна парола, лимит на свалянията, изтичане, отмяна и липса на изтичане на
  хеша на паролата в административния и публичния изглед.

### OpenPGP v6 — проверено и документирано

- **`tests/pgp-v6.cjs`** доказва v6 веригата със структура, не само кръгов тест:
  Ed25519 ключ по RFC 9580 (версия 6, алгоритъм 27, uint32 дължина на материала,
  SHA-256 отпечатък от 64 hex знака, keyId = първите 64 бита), Direct Key
  self-signature тип `0x1f`, v6 подпис със salt по алгоритъм (SHA-512 → 32 байта),
  проверка, изолация между ключове и обратна съвместимост с v4.
- **Подписан експортен пакет с v6 ключ** — тестът минава през `packager.build()` и
  проверява `.asc` срещу `.zip`, т.е. същият път, който ползва
  `POST /admin/api/packages` с `autoSign`.
- **v6 криптиране съзнателно НЕ е добавено.** RFC 9580 изисква PKESK v6 + SEIPD v2
  (AEAD); GnuPG 2.5.24 наличният тук поддържа само v4 и черновата RFC 4880bis, т.е.
  няма срещу какво да се валидира. Ръкописно криптиране без проверка не влиза в
  изданието; at-rest остава AES-256-GCM с вътрешния ключ (асиметрично криптиране на
  собствените данни е архитектурно безсмислено — услугата трябва да ги чете).
  README описва точно какво v6 може днес и какво предстои.

### Административен панел без токен

- **Панелът е обикновен бутон в страничната лента** — `panel_admin: false`. Видим е за
  всеки потребител на Home Assistant, а какво може всеки се решава от RBAC по HA
  самоличност (`user_roles` / `group_roles`), не от видимостта на бутона.
- **Опцията `token` е премахната изцяло** от `config.yaml` (options + schema),
  от преводите `en`/`bg` и от README. Няма какво да се въвежда, копира или пази.
- **Токенът е премахнат от човешкия поток.** Под Home Assistant Ingress
  `/admin/api/ingress-login` връща само сесия (`role`, `ingress`, `user`, `defaultRole`,
  `mapped`) — никога ключ. Панелът се удостоверява с идентичността, която HA подава
  (`X-Remote-User-*`), а полето „Admin token“ е премахнато от лентата.
- Инсталиралият add-on-а е администратор по подразбиране; ролята се сменя с
  `user_roles` / `group_roles`. Standalone (Docker без Supervisor) запазва досегашното
  поведение — там ключът остава единственият начин за достъп и се дава само на loopback.
- `adminToken` остава **вътрешен** мастер ключ за AES-256-GCM, HMAC на подписаните
  URL-и, PGP материала и одит веригата: генерира се веднъж в `/data/admin-token` (0600),
  никъде не се показва и никой не го въвежда.

## Непубликувани (Unreleased)

Локално разгръщане без GitHub — само инструменти, изображението на add-on-а не се променя.

- **Проектният одит е на 100%** — `tests/ha-compatibility.cjs` минава 42/42 правила
  без предупреждения и блокери. Остават две забележки (`info`) за неща, които Home
  Assistant изрично приема: deprecated `armv7` в `arch` и root контейнер без AppArmor
  профил (влияе само на security rating, не на инсталацията).
- Правилото за мъртъв код вече отчита и референции от тестовете: `plugins/ocr.js` и
  `plugins/renderer.js` се зареждат от `tests/core-plugins.cjs` и не са остатъци.
- Еднократните `tmp-*.ps1` скриптове са преместени в `archive/dev-scripts/` (коренът
  на хранилището е чист, нищо не е изтрито).

- **Готово за HACS хранилище** — `scripts/build-haoss.cjs` (`npm run release:haoss`)
  сглобява самостоятелно хранилище в `release/haoss` по стандарта на HACS:
  `hacs.json` само с документирани ключове, `README.md`, `LICENSE`, `SECURITY.md`,
  `.github/workflows/validate.yml` (hassfest + HACS action, `category: integration`) и
  `custom_components/hapi_enterprise/` с пълен `manifest.json` (`domain`,
  `documentation`, `issue_tracker`, `codeowners`, `name`, `version`) и
  `brand/icon.png`. Скриптът проверява договора на HACS преди да приключи, не пише
  нищо извън изходната папка и не копира кешове (`__pycache__`, `*.pyc`).
- **`tests/haoss-release.cjs`** — построява изданието във временна папка и валидира
  готовия артефакт (една интеграция, версия = `config.yaml`, brand PNG, без кешове и
  без тайни), за да не се разминава структурата при бъдещи промени.
- **`release.yml` в HACS хранилището** — таг `v<версия>` създава пълно GitHub release
  (`gh release create --generate-notes`) и първо сверява тага с `manifest.json`, за да
  не излезе издание с чужда версия. `CHANGELOG.md` се копира в хранилището.
- **`manifest.json`: `integration_type: hub`** — интеграцията е хъб към add-on-а;
  полето вече е явно, вместо да се подразбира.
- **`RELEASE_QUALIFICATION.md` е приведен в актуално състояние** — статус 0.61.3
  „готово за публикуване“ с таблица на локалните гейтове (132/132 теста, 42/42 правила
  HA одит, 20/20 издателски сценария), вместо стария запис v0.47.0 „BLOCKED“ и
  несъществуващия вече `START_hAPI_Enterprise.bat`. Историята е запазена под
  „История (предишни снимки)“.
- **`npm run audit` спазва `.gitignore`** — проверява само това, което реално би влязло
  в хранилището (449 файла вместо 2314). Досега локалните `.venv/` и `*.7z` архиви
  даваха „файлове > 5 MB“ и одитът излизаше с код 1 при всеки push. Сега: 0 едри
  файла, 0 подозрителни имена, 0 тайни.
- **Локалните артефакти са изнесени извън проекта** (нищо не е изтрито) —
  `release/windows` (backup от 0.54.0 с премахнатия вече `run.sh`) и трите архива
  `brand.7z`, `hAPI Enterptice.7z`, `READY_JS_PACKAGES.7z` са преместени в
  `H:\PROJECT_HA\_hAPI-local-archive-2026-10-21`. В `release/` остава само `haoss`.
- **`scripts/publish-haoss.ps1`** (`npm run publish:haoss`, задача „hAPI: публикувай
  HACS хранилището (dry run)“) — публикуването на интеграцията е една команда:
  build с адреса на новото репо → `git init`/commit → `gh repo create` (или push към
  съществуващо) → описание + topics + Issues → таг `v<версия>` → проверка. Без
  `-Execute` е dry run и не качва нищо; не прави force push и не трие от GitHub.
- **Интеграцията е публикувана** — <https://github.com/PasevSU/hapi-enterprise-integration>
  (public, `main`, topics `home-assistant`/`hacs`/`integration`, Issues включени).
  Release `v0.61.3` е създаден автоматично от `release.yml`; `Validate`
  (hassfest + HACS action) тече при всеки push.
- **`git` върху мрежов диск** — `H:` е SMB дял и `git` там блокира дори на
  `git rev-parse`, а `git init` след build пада с код 1. Затова генераторът вече
  **не пипа `.git`**, а публикацията минава през локално копие във `%TEMP%`
  (`-InPlace` за работа направо в `release/haoss`).

- **`scripts/sync-local-addon.ps1`** — копира add-on-а в `/addons/hapi_enterprise` и
  интеграцията в `/config/custom_components/hapi_enterprise` (`robocopy /MIR`), с
  `-VerifyOnly` (само проверки) и `-Backup` (копие на предишната версия извън `/addons`,
  за да не се появи втори add-on).
- **Проверки на оформлението** — `Assert-AddonLayout` (ключове в `config.yaml`, всеки
  `COPY` източник от `Dockerfile`, `exec node /app/server.js`) и
  `Assert-IntegrationLayout` (`manifest.domain = hapi_enterprise`, SemVer версия,
  `__init__.py`, `config_flow.py`, `sensor.py`, `strings.json`). Липсващ файл се хваща
  преди билда в Supervisor, вместо да излезе като неясна грешка.
- **`npm run sync:local`** и VS Code задачи „hAPI: синхронизирай локалния add-on“,
  „hAPI: провери локалния add-on“ и „hAPI: пълен тестов пакет“.
- **README** — секция „Local add-on and integration (no GitHub)“ с точните стъпки в
  Home Assistant (Check for updates → Rebuild; махане на GitHub репото от Repositories).
- **Забележка** — Home Assistant зарежда custom интеграция само от папка, чието име
  съвпада с `domain` в `manifest.json`; копие в `custom_components/hAPI Enterptice`
  (пълно копие на репото) се игнорира тихо от HA.
## 0.61.4 — 2026-10-21

Първите три грешки на hassfest, хванати веднага след като интеграцията стана публична.

- **`manifest.json`: ключовете са подредени според изискването на hassfest** — `domain`,
  `name`, после по азбучен ред. Досега `version` стоеше веднага след `name`, а
  `after_dependencies`/`config_flow`/`dependencies` не бяха сортирани.
- **`CONFIG_SCHEMA` за YAML режима** — интеграцията дефинира `async_setup`, затова Home
  Assistant изисква схема; без нея `hapi_enterprise: backend_url: ...` се отчита като
  невалидна конфигурация (hassfest: конфигурационна схема липсва). Схемата приема
  `backend_url` като низ и позволява допълнителни ключове, за да не чупи стари конфигурации.
- **Без HTML в преводите** — `(http://<addon-hostname>:8098)` се приемаше за HTML таг и
  hassfest отхвърляше `strings.json` и `translations/en.json`. Заменено с
  `(напр. http://hapi_enterprise:8098)` в en и bg.
- **Първо публикуване** — <https://github.com/PasevSU/hapi-enterprise-integration>;
  `v0.61.3` остава в историята като първия опит, `v0.61.4` е изданието, което минава
  `Validate` (hassfest + HACS action).
- **CI без изключения** — след като description/topics/Issues са зададени в GitHub,
  `ignore: topics` отпада от `validate.yml`; така HACS action минава „без грешки и без
  изключения“, което е изискване за включване в списъка по подразбиране на HACS.
- **Тагът се вдига само веднъж** — `publish-haoss.ps1` проверява дали `v<версия>`
  вече сочи друг commit и тогава не го мести, а подсказва да се вдигне версията.
  Така издадено издание не може да бъде подменено по невнимание.
- **Add-on репото е публикувано (0.61.4)** — дотогава `PasevSU/hAPI` беше на `0.54.0`,
  тоест Home Assistant щеше да предложи стар add-on. Новият
  `scripts/publish-addon-repo.ps1` клонира репото във `%TEMP%`, огледално копира
  локалното дърво (robocopy, без `.git/.venv/node_modules/release/dist`), пуска
  `verify-release` като гейт и push-ва с истински diff — без force push. Без `-Execute`
  е dry run.
- **Ясно разделение на двете хранилища в README на интеграцията** — ако адресът ѝ се
  добави като add-on (app) repository, HA отговаря „is not a valid app repository“.
  README-то вече показва таблица „кое се добавя къде“, за да не се стига дотам.

## 0.61.3 — 2026-10-21

Ingress идентичност по реалните HA заглавки, peer изолация и проект-wide одит за съвместимост.

- **Ingress SSO по истинските заглавки** — `rbac.js` чете `X-Remote-User-Name`,
  `X-Remote-User-Id` и `X-Remote-User-Display-Name` (Home Assistant не изпраща
  `X-Remote-User` и не изпраща групи). `user_roles` вече работи с реалните HA данни;
  старите заглавки остават само като fallback за reverse proxy.
- **Peer allowlist на admin listener-а** — порт 8098 приема само Supervisor проксито
  (`172.30.32.2`) и loopback (`ADMIN_PEERS` за custom мрежи). Друг контейнер в Docker
  мрежата вече не достига административния API.
- **`ssl` в `map`** — `tls_cert`/`tls_key` могат да сочат към `/ssl`, както е описано
  в преводите; преди това пътят не съществуваше в контейнера.
- Allowlist-ите за backup/mirror приемат само монтираните корени
  (`/share`, `/media`, `/config`, `/data`); премахнати са `/backup` и `/addon_config`,
  които никога не са били монтирани.
- `DATA_DIR` е премахната от `environment` — `start.js` я задава от storage preflight.
- `hapi_enterprise/.dockerignore` — build контекстът не включва README, SVG икони и `plugins/`.
- CI билдва и `armv7`, така че обявената архитектура има покрит билд.
- **Нов проект-wide одит `tests/ha-compatibility.cjs`** — 44 правила в 9 области
  (манифест, образ, entrypoint, ingress, Supervisor API, съхранение, интеграция, CI,
  остатъци). Blocker → exit 1, warning → отчет със доказателство.

## 0.61.2 — 2026-10-21

Add-on-ът е чист JavaScript от край до край и говори със Supervisor API-то коректно.

- **Entrypoint на JS** — `run.sh` е премахнат; контейнерът стартира с
  `CMD ["node", "/app/start.js"]`. `start.js` прави същото, което правеше shell
  скриптът (четене на `/data/options.json`, ADMIN_TOKEN с постоянен файл
  `/data/admin-token` с права 0600, storage preflight, `--max-old-space-size`, env от
  опциите), но без `/bin/sh`, без `chmod` и без втори език за стартиране. Сървърът е
  дете на entrypoint-а, за да получава SIGTERM и да затваря SQLite WAL чисто.
- **`homeassistant_api: true`** в `config.yaml` — без него Supervisor не разрешава
  проксито `http://supervisor/core/api`, през което `notify.js` изпраща QR/линк
  (default е `false`, т.е. dispatch-ът гърми с 403/502 в реален add-on).
- **`EXPOSE 8088`** — публичният gateway порт вече е обявен и в образа, не само в
  `config.yaml`.
- `arch: armv7` остава (образът `node:22.16.0-alpine3.21` публикува `linux/arm/v7`),
  с изрична бележка, че Supervisor вече маркира тази стойност като deprecated.
- Тестове: нов `tests/start-entrypoint.cjs` вдига реалния entrypoint и проверява
  storage preflight, генерирания токен (0600, без печат в лога) и спирането.
  Обновени: `docker-runtime`, `node-runtime-gate`, `raspberrypi-compat`, `ha-bridge`,
  `release-tooling`, `addon-config`, `scenario-matrix`. `verify-release` S13 пази JS
  entrypoint-а, а S08 — че `run.sh` не се връща в архива.
- `.gitignore` изключва `.venv/` — локалната HA среда за разработка не е част от
  add-on хранилището.

## 0.54.0 — 2026-10-21

Порталната страница през интеграцията е същата адаптивна страница като в add-on-а.

- `custom_components/hapi_enterprise/portal.html|portal.js|portal.css` са подменени с
  адаптивната версия: текстовете зависят от артефактите („Документи“ / „Снимки“ /
  „Документи и снимки“ / „Файлове“), правилни числителни форми, търсене само при повече
  от 3 файла, SHA-256 с копиране, изтегляне с ключ (`X-File-Key`), QR панел.
- Заявките минават през fail-closed моста на интеграцията
  (`/api/hapi_enterprise/v1/p/<id>`); ключът за достъп се държи **само във фрагмента**
  (`#token=…`) и се праща като `X-Portal-Key` — не като query параметър.
- Мостът вече разрешава и `qr.svg`, за да показва страницата своя QR код.
- `tests/ha-integration-flow.cjs` пази тези инварианти (адаптивни маркери, фрагмент-токен,
  разрешен `qr.svg`, без `innerHTML` за данните).
- **Enterprise Control Center** (`ui/`) вече е част от add-on пакета: папката е преместена в
  `hapi_enterprise/ui/`, `Dockerfile` я копира в `/app/ui/`, а `server.js` я сервира първо до
  себе си (контейнер), после в родителската папка (разработка). Преди това `/ui` връщаше 500
  в add-on-а, защото build context-ът на Supervisor е само папката на add-on-а.
- Ingress allowlist-ът пуска `/ui`, `/ui/*` и `/hapi_enterprise/*` на административния
  листенър (и ги блокира на публичния) — Control Center-ът се отваря през Home Assistant.
- Липсващ статичен асет връща 404 + `ui.asset.missing` в журнала, вместо 500.
- `tests/docker-runtime.cjs` проверява, че всеки асет от `UI_FILES` съществува в add-on
  папката и е покрит от `COPY`; `tests/ingress-isolation.cjs` пази ingress маршрутите.
- `hapi_enterprise/README.md` има раздел **Recommended settings before you install**:
  готов YAML блок за Configuration таба (token, storage, публичен адрес, `user_roles`),
  таблица „опция → препоръка → защо“ и чеклист за първите две минути след старт.
  `tests/addon-config.cjs` пази блока синхронизиран с `config.yaml` (всяка препоръка е
  реална опция с валидна стойност).
- **RFC 3161 TSA блок** (порт от HASH_REPORT / ChronoSeal-Vault): панел „RFC 3161 TSA“
  в Report Studio с DFN START и DigiCert STOP адреси, бутони за реален токен и резултат.
  Нов `tsa-client.js` (без зависимости, ръчен DER): TimeStampReq, разбор на
  PKIStatusInfo/TSTInfo, проверка на `messageImprint`. `POST /admin/api/v2/rfc3161`
  създава `.tsr` + `.json` в `<storage>/tsa/`; STOP подпечатва затварящия хеш
  `SHA-256(startDigest | startTokenSha256)`. Отказ на TSA → `502` без запис.
  Тестове: `tests/tsa-client.cjs`, `tests/rfc3161-api.cjs` (фалшив локален TSA).

## 0.53.1 — 2026-10-21

Поправка в UI настройката на интеграцията.

- Смяната на опциите (адрес, токен, интервал) вече се прилага **веднага** —
  `entry.add_update_listener(async_update_entry)` е регистриран в `async_setup_entry` и се
  отписва при unload. Преди промяната `async_update_entry` съществуваше, но никога не се
  извикваше, т.е. опциите влизаха в сила само след преинсталиране на интеграцията.
- `tests/ha-integration-flow.cjs` пази това: изисква listener-а и отписването му.

## 0.53.0 — 2026-10-21

Пълният набор функции на интеграцията от `PasevSU/hAPI` (portal_enterprise) е пренесен
в `custom_components/hapi_enterprise`, без да се маха нищо от тази версия.

- **UI настройка**: `config_flow.py` с config и options flow (адрес, административен токен,
  интервал на обновяване); уникален запис по адрес, валидация на URL, дължина на токена
  (24–512) и интервал (10–86400 s).
- **Телеметрия**: `coordinator.py` пита `/admin/api/sensors` с Bearer токен и превежда
  camelCase полетата на add-on-а (`fileBytes`, `databaseBytes`, `telemetryBytes`) към
  ключовете на сензорите; `sensor.py` създава 7 сензора (посещения, изтегляния, файлове,
  портали, място за файлове, размер на базата, размер на телеметрията).
- **Преводи**: `strings.json` + `translations/en.json` и `translations/bg.json`.
- `manifest.json`: `config_flow: true`, `iot_class: local_polling`.
- `async_setup` вече не блокира UI настройката, когато няма `backend_url` в YAML; порталната
  страница и активите (`/api/hapi_enterprise/portal/<id>`, `/api/hapi_enterprise/assets/*`)
  се регистрират винаги.
- Нови тестове: `tests/ha-integration-flow.cjs` (договор между const/coordinator/sensor/
  преводи/манифест) и разширени `tests/hacs-structure.cjs` + сценарии S06/S07 в
  `scripts/verify-release.cjs` (всички Python модули, config flow в архива).

## 0.52.1 — 2026-10-21

Инсталиране през HACS.

- `hacs.json` в корена на хранилището (`content_in_root: false`, `homeassistant: 2024.6.0`,
  `domains: [hapi_enterprise]`), така че хранилището се добавя като custom repository в HACS.
- Brand изображения в `custom_components/hapi_enterprise/brand/` (icon/logo) — новото място,
  което Home Assistant и HACS очакват; старите копия до `manifest.json` остават за съвместимост.
- `manifest.json`: `codeowners: ["@PasevSU"]`, `documentation` и `issue_tracker` сочат
  GitHub хранилището, добавени `after_dependencies` и `loggers`.
- GitHub Actions `HACS validation` (`hacs/action`, category `integration`) + локален тест
  `tests/hacs-structure.cjs`; нов сценарий S21 в `scripts/verify-release.cjs`.
- Кешовете на Python (`__pycache__`, `*.pyc`) се изключват от изданието и се проверяват.

## 0.52.0 — 2026-10-21

Издание с изцяло автоматизиран build и проверка.

**Публичен портал**

- Публичната страница и QR кодът се адресират с **id на портала** (`/p/<id>`), не с име;
  `/p/<slug>` и `/api/v1/p/<slug>` продължават да работят (`resolvePortal`).
- Текстовете на страницата се променят според артефактите в портала: „Документи“,
  „Снимки“, „Документи и снимки“ или „Файлове“; правилни числителни форми
  („1 документ“, „5 снимки“), търсене само при повече от 3 артефакта, бележки под QR
  кода само за наличните функции (SHA-256, ключ, спряно изтегляне).
- Празен портал показва „Съдържание“ и „издателят още не е публикувал файлове“.

**Публични адреси**

- Опцията `public_domain` на add-on-а се подава като `PUBLIC_BASE_URL` (чрез `run.sh`),
  така че QR кодът и адресите от административния панел сочат външния домейн, дори
  когато панелът се отваря по вътрешния адрес.
- Невалиден публичен адрес се игнорира (пада към адреса на заявката) — както за
  настройката `limits.publicBaseUrl`, така и за средата.
- QR прозорецът в панела предупреждава, когато адресът е вътрешен (LAN/localhost).

**Издание и проверка**

- `scripts/build-release.cjs` строи `dist/`: add-on `tar.gz`, интеграция `zip`,
  `repository.yaml`, `RELEASE.json` (с хеш на всеки файл) и `SHA256SUMS.txt`, без
  външни зависимости.
- `scripts/verify-release.cjs` проверява 19 сценария: версия, add-on схема, файлове,
  Dockerfile, JS/Python синтаксис, манифест на интеграцията, двата архива, манифеста
  на изданието, тайни, портални активи, `run.sh`, опции↔схема, `repository.yaml`,
  документация, хигиена на архива, четене със системен `tar` и (по избор) целия
  тестов набор.
- GitHub Actions `release.yml` строи и проверява изданието при таг `v*` и качва
  артефактите.

## 0.51.0 — 2026-10-20

- Пълен пакет хешове за файловете (sha256/sha512/sha384/sha3-256/sha1/md5) в API, в
  интерфейса и в ZIP пакета (`hashes/sha256sum.txt`, `hashes/checksums.txt`).
- Единна SVG икона система в интерфейса вместо емоджита; заключване/видимост и
  контекстно меню на файловете.

## 0.50.0 — 2026-10-19

- Публична страница на портала (`/p/<slug>`), QR код към нея, контакт на издателя,
  търсене и изтегляне с ключ (`X-File-Key`).
