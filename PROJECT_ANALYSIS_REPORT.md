# تقرير التحليل الشامل وإصلاح الأعطال
### مشروع ARN Shutdown Panel — الإصدار 2.0.1
**تاريخ التقرير:** 2026-10-19 • **النطاق:** الكود المصدري، الواجهات الست، خادم الشبكة المحلية، حزمة البناء، الاختبارات، الوثائق.

---

## 1) الملخص التنفيذي

تمت مراجعة المشروع بالكامل (221 ملفًا متعقَّبًا في Git) عبر قراءة الكود سطرًا بسطر، تشغيل خادم حقيقي على منفذ محلي، تنفيذ سيناريوهات HTTP فعلية، تشغيل حزمة الاختبارات، تحليل AST، وفحص JavaScript المضمَّن في كل قوالب HTML.

**النتيجة قبل الإصلاح:** 97 اختبارًا ناجحًا و4 فاشلة، وعيبان أمنيان خطيران (تجاوز قفل الشاشة بكلمة `admin`، وتوكنات لا تُبطَل أبدًا)، وعطل منطقي كان يحوّل جدولة «إطفاء الشاشة» إلى **إيقاف تشغيل كامل**، وبناء EXE مستحيل لأن ملفَّي `.spec` غير موجودين أصلًا.

**النتيجة بعد الإصلاح:**

| المؤشر | قبل | بعد |
|---|---|---|
| الاختبارات | 97 ناجح / 4 فاشل (101) | **108 ناجح / 2 متخطّى** (110) |
| تغطية الكود | 57% | **57%** (مع تحسّن `security` 87% و`settings` 82% و`schedules` 91%) |
| أخطاء Python القاتلة (`F821/F811`) | 3 | **0** |
| ملفات البناء `.spec` | غير موجودة | **موجودة ومتحقَّق منها** |
| كلمة سر الشبكة | نص صريح + `admin/admin` | **PBKDF2 + كلمة عشوائية عند أول تشغيل** |
| إبطال التوكن عند التدوير | لا يحدث | **كل الجلسات تُبطَل** |

> ملاحظة منهجية: بيئة الفحص Linux بلا شاشة، لذلك اختباران يعتمدان على Windows (الصوت الدقيق وإدخال لوحة المفاتيح) صارا يُتخطّيان تلقائيًا بدل أن يفشلا. لم يتم تشغيل نوافذ pywebview بصريًا، ولم تُبنَ EXE فعليًا لعدم توفر `libpython` المشترك في البيئة.

---

## 2) خريطة المعمارية ودرجة الترابط

```
main.py (pywebview + pystray + قفل نسخة واحدة)
 ├── gui/api.py  (AppAPI: 59 دالة جسر)  ──►  core/
 │     ├── scheduler.py   (عدّاد تنازلي)
 │     ├── schedules.py   (جدولة أسبوعية)
 │     ├── commander.py   (توليد أوامر النظام وتنفيذها)
 │     ├── settings.py    (JSON ذرّي)
 │     ├── metrics.py     (CPU/RAM/بطارية)
 │     ├── kiosk_lock.py  (قفل Windows)
 │     └── remote_server.py  (ThreadingHTTPServer + MJPEG + ملفات)
 ├── gui/web/       index / widget / countdown / lock / mobile
 ├── client_main.py ──► gui/client_api.py ──► core/remote_server عبر HTTP
 └── gui/client_web/ (تطبيق صفحة واحدة)
```

**الترابط سليم في الاتجاه العام** (واجهة ← جسر ← Core ← نظام)، لكن كانت هناك ثلاث فجوات حقيقية:

1. **عقد API غير متطابق** بين الويب والخادم في لوحة المفاتيح والفأرة واللمس.
2. **حالة مزدوجة** للتوكن/الجلسات: الواجهة تعرض توكنًا بينما الخادم يحتفظ بجلسات قديمة صالحة.
3. **عناصر واجهة معلّقة**: كود JS يبحث عن أزرار غير موجودة في HTML، فميزات كاملة كانت غير قابلة للاستخدام.

---

## 3) الأعطال التي تم إصلاحها

> أرقام الأسطر في هذا القسم تشير إلى الملفات **قبل** تطبيق الإصلاح، لتكون دليلًا على موضع العطل الأصلي.

### 3.1 الأمان (الأخطر)

| # | العطل | الدليل قبل الإصلاح | الإصلاح |
|---|---|---|---|
| 1 | **تجاوز قفل الشاشة** بأي كلمة `admin` | `gui/api.py:146` كان الشرط `given_pass == expected_pass or given_pass == "admin"` | إزالة الاستثناء، والتحقق عبر `settings_manager.verify_remote_password()` مع PBKDF2 ومقارنة ثابتة الزمن |
| 2 | **كلمة سر الشبكة نص صريح** في `settings.json` | `core/settings.py` كان يحفظ `remotePassword` كما هو | `core/security.py` جديد: PBKDF2-HMAC-SHA256 بـ240 ألف تكرار وملح عشوائي، صيغة `pbkdf2_sha256$iter$salt$hash`؛ ترحيل تلقائي للمفتاح القديم وحذفه من القرص |
| 3 | **توكنات لا تُبطَل** | `rotate_token()` كان يضيف توكنًا جديدًا ويترك القديم صالحًا؛ `set_credentials()` لا يمسّ الجلسات | `revoke_sessions_locked()` يمسح كل الجلسات ويصدر توكنًا جديدًا عند التدوير أو تغيير أي بيانات دخول |
| 4 | **جلسات لا تنتهي** | `is_valid_token()` لا يفحص عمر الجلسة | رفض الجلسات الأقدم من 30 يومًا وحذفها أثناء الفحص |
| 5 | **XSS من أسماء الملفات والمسارات** | `mobile.html` و`client_web` كانا يبنيان بطاقات الملفات بـ`innerHTML` مع `onclick` مضمّن وهروب ساذج | `renderFileCards()` تبني DOM وتستخدم `textContent`؛ `escapeHtml()` لأي إدخال نصي؛ قائمة الأجهزة وبطاقات الاكتشاف كذلك |
| 6 | **XSS عبر User-Agent** | `app.js:637` كان `item.innerHTML = ... ${c.userAgent}` | إنشاء عناصر `span` و`textContent` |
| 7 | **تسريب مسار** في `/fonts/` | `WEB_DIR / path.lstrip("/")` يسمح بـ`..` | `resolve()` + `relative_to(fonts_dir)` + رفض بـ404 |
| 8 | **مفتاح HTTPS الخاص عالمي القراءة** | كتابة `server.key` بالصلاحيات الافتراضية | `chmod 0600` للمفتاح و`0644` للشهادة |
| 9 | **الحقول معبّأة مسبقًا** بـ`admin/admin` | `index.html:207,211` + حقل نصي غير مخفي | إزالة القيم، `type="password"`، وعدم إعادة كلمة السر إلى الواجهة إطلاقًا |
| 10 | **كلمة سر افتراضية متوقعة** | `RemoteServer` و`SettingsManager` يبدآن بـ`admin` | عند أول تشغيل يُولَّد `token_urlsafe(12)` عشوائي ويُحفظ كـhash؛ الخادم يبقى معطّلًا حتى يفعّله المستخدم |
| 11 | **بيانات حساسة قابلة للتنزيل** | `/api/fs/download` يسمح بتنزيل `settings.json` (يحوي الـhash والسجلات) | `is_app_data_path()` تمنع التنزيل/الفتح/الضغط/الرفع/الحذف داخل مجلد بيانات التطبيق |
| 12 | **غياب رؤوس حماية المتصفح** | لا CSP ولا `X-Frame-Options` | إضافة `CSP` و`X-Content-Type-Options` و`X-Frame-Options` و`Referrer-Policy` لكل استجابة |
| 13 | **قفل الشاشة في المتصفح** | `lock_screen.html:862` كان يقبل `admin` عند غياب الجسر | إزالة البوابة الوهمية نهائيًا |

### 3.2 منطق العمل

| # | العطل | الدليل | الإصلاح |
|---|---|---|---|
| 1 | **جدولة «إطفاء الشاشة» تُنفّذ Shutdown** | `core/schedules.py:11` لم تكن `display_off` ضمن `VALID_ACTIONS`، و`_sanitize()` يستبدلها بصمت بـ`shutdown`. أُثبت تجريبيًا: `add("display_off") → "shutdown"` | إضافة `display_off` + تسجيل تحذير عند أي إجراء غير معروف بدل التحويل الصامت |
| 2 | **`hibernate` غير مدعوم فعليًا** رغم وجوده في `VALID_ACTIONS` | `Commander.plan("hibernate")` كان يرمي استثناءً على كل الأنظمة | Windows `shutdown /h`، Linux `systemctl hibernate`، macOS `pmset sleepnow` |
| 3 | **تسجيل الخروج على Linux بدون مستخدم** | `["loginctl","terminate-user",""]` ثم تُحذف السلسلة الفارغة | استخدام `$USER`/`getpass.getuser()` |
| 4 | **زر إيقاف/استئناف العدّاد من الموبايل لا يعمل** | الموبايل يرسل `pause`/`resume` إلى `/api/command`، والجسر يمرّرها إلى `Commander` الذي يرفضها كإجراء طاقة | `_on_remote_command` يعالج `pause/resume` عبر `Scheduler` مباشرةً |
| 5 | **فشل الإلغاء على Linux** | `/api/abort` يرجع `ok:false` لأن `plan_abort` غير مدعوم، رغم إلغاء العدّاد فعليًا | إرجاع `ok:true` عندما يكون الإلغاء منطقيًا فقط |
| 6 | **`hotkey` من الويب يفشل بـ400** | الويب يرسل `{action:"hotkey", keys:[...]}` والخادم يقرأ `hotkey` فقط | قبول `keys` كمرادف + تحقق من الطول والأنواع |
| 7 | **اللمس ينقر في مكان المؤشر لا في نقطة اللمس** | `onScreenTouchClick` يحسب `x,y` ثم يهملهما ويرسل `click` فقط | `fetchRemoteScreenSize()` + إرسال `move_to` أولًا ثم `click` |
| 8 | **تناقض أسماء إجراءات الفأرة** | `moveto` في نسخة ميتة و`move_to` في الحيّة | قبول الاسمين |
| 9 | **دوال مكررة ميتة** | `_input_mouse/_input_keyboard/_media_control` معرّفة مرتين (`remote_server.py` قديمًا 1795 ثم 1935) | حذف النسخة الأولى (3260 حرفًا) والإبقاء على الحيّة مع تحقق كامل |

### 3.3 أخطاء تنفيذية (كانت تُرجع HTTP 500)

| العطل | الدليل | الإصلاح |
|---|---|---|
| `NameError: SW_SHOW` عند إخفاء/إظهار شريط المهام | `core/kiosk_lock.py:202` يستخدم الاسم المجرد بينما هو سمة داخل `if IS_WINDOWS` | تعريف `SW_HIDE`/`SW_SHOW` على مستوى الوحدة (module-level) |
| `NameError: KEYEVENTF_KEYUP` عند `key_press` | `core/input_controller.py:344` | تعريف الثابت على مستوى الوحدة |
| `NameError: subprocess` عند فتح ملف | `core/remote_server.py:1717` | استيراد `subprocess` |
| `os.system` في تعديل السطوع | كان يعيد `ok:true` على Linux رغم فشل PowerShell | استدعاء `InputController.set_brightness_percent()` وإرجاع النتيجة الحقيقية |

### 3.4 الواجهات وتجربة الاستخدام

| # | العطل | الدليل | الإصلاح |
|---|---|---|---|
| 1 | **النافذة الرئيسية غير قابلة للسحب** | `main.py:163` يضع `easy_drag=False`، ولا يوجد أي `.pywebview-drag-region`؛ و`-webkit-app-region` لا تدعمها pywebview | إضافة `pywebview-drag-region` إلى شريط العلامة |
| 2 | **أزرار مفقودة** | `app.js:450` يبحث عن `btnCancelTimer`، و603/664/675 عن `remoteTokenVal`/`btnRotateToken`/`btnCopyToken` — غير موجودة في `index.html` | إضافة زر الإلغاء ولوحة التوكن (عرض/نسخ/تدوير) |
| 3 | **i18n الموبايل لا يعمل** | لا توجد دالة تطبيق ترجمات؛ `toggleLang` يغيّر الاتجاه فقط، و21 مفتاحًا مفقودًا | `applyI18n()` + 21 مفتاحًا (ar/en) |
| 4 | **نقص ترجمات العميل** | 15 مفتاحًا مفقودًا منها `lockPlaceholder` | إضافة كل المفاتيح والتحقق برمجيًا: **صفر مفقود** |
| 5 | **خطوط ناقصة** | `styles.css:12,20` تطلب `cairo-latin.woff2` و`cairo-latinext.woff2` غير موجودين | إضافتهما من حزمة `@fontsource/cairo` في `gui/web/fonts` و`client_web/fonts` |
| 6 | **اعتماد على CDN** | `widget.html` و`countdown_overlay.html` يحمّلان DS-Digital من `fonts.cdnfonts.com` | حذف الرابط والاعتماد على `fonts/ds-digital.woff` المحلي |

### 3.5 البناء والتوزيع

| العطل | الدليل | الإصلاح |
|---|---|---|
| **ملفا PyInstaller غير موجودين** | `build_exe.py:108,125` يستدعي `ShutdownPanel.spec` و`ShutdownPanelClient.spec`، ولا يوجد أي `.spec` في المستودع | إنشاء الملفين (onefile، `console=False`، تضمين `gui/web`/`gui/client_web`/`cert`/`assets`، أيقونة اختيارية) |
| **سبب اختفائهما** | `.gitignore` كان يستثني `*.spec` و`assets/icon.ico` | إزالة الاستثناءين وإضافة الأيقونة |
| **رسالة خطأ غامضة** | PyInstaller يفشل بدون توضيح | `_require_spec()` يرمي رسالة صريحة قبل التنفيذ |
| **إصدار غير متسق** | 2.0.0 في 6 مواضع | ترقية متسقة إلى **2.0.1** (الكود، المثبّت، السكربتات، الوثائق) |
| **ملف اختبار متروك** | `tests/test_sign.tmp` (UTF-16) | حُذف |
| **`.coverage` غير متجاهل** | كان يظهر كملف غير متعقَّب | أضيف إلى `.gitignore` |

### 3.6 الوثائق

- `README.md`: شارة **PyQt6** كانت تناقض التنفيذ الفعلي (pywebview) → استُبدلت بشارة المنصة.
- `CHANGELOG.md`: ادّعاء **MIT** مقابل `LICENSE` احتكاري → صُحّح.
- `PROJECT_DOCUMENTATION.md`: كان يذكر **89 اختبارًا** وملفات `client_web/app.js` و`styles.css` غير موجودة → صُحّح إلى 110 اختبارات وبنية العميل الحقيقية.
- إضافة قسم كامل في `CHANGELOG` يوثّق كل إصلاحات 2.0.1.

---

## 4) نتائج التحقق (أدلة قابلة لإعادة التشغيل)

```bash
# 1) الاختبارات
python -m pytest tests/ -q
# 108 passed, 2 skipped in 101.54s

# 2) الأخطاء القاتلة فقط
ruff check core gui tests main.py client_main.py --select F821,F841,F401,F811,F402
# All checks passed!

# 3) صحة JavaScript المضمّن في القوالب الستة
python /tmp/check_js.py     # مستخرج <script> ثم node --check
# bad blocks: 0

# 4) سيناريو حقيقي للأمان (خادم فعلي على 127.0.0.1:18211)
login 200 → rotate_token → old token 401 / session 401 / new token 200
set_credentials → master token 401 / old password 401 / new password 200
hotkey {keys:[...]} → 200 (ok:false على Linux لعدم وجود pyautogui)
/fonts/../../core/settings.py → 404
/fonts/cairo-latin.woff2 → 200

# 5) سيناريو AppAPI (APPDATA مؤقت)
plaintext stored? False | get_settings leaks hash? False
unlock with admin -> ok:False | unlock with real -> ok:True
token rotated? True | session alive? False
pause: ok True | resume: ok True | abort: ok True
settings.json mode: 600
```

**إحصاءات نهائية:** 32 ملفًا معدّلًا + 9 ملفات جديدة + حذف ملف واحد، 891 إضافة و293 حذفًا، 110 اختبارات، 31 نقطة API.

---

## 5) الفجوات المتبقية والحدود المعمارية

هذه ليست أعطالًا مُصلحة، بل دَين تقني يجب التعامل معه بوعي:

### 5.1 نقاط API موجودة بلا واجهة
`/api/proc/list`، `/api/proc/kill`، `/api/wol`، `/api/media/volume`، `/api/fs/create_dir` — تعمل مختبريًا لكن لا يستخدمها أي عميل. إما تُعرض في واجهة «أدوات متقدمة» أو تُزال لتقليل سطح الهجوم.

### 5.2 مجلد مكرر قديم
`ShutdownPanel/` نسخة قديمة من 109 ملفًا، 106 منها متطابقة بايتًا مع الجذر و3 مختلفة (widget/countdown). لا يحتاجه البناء ولا التثبيت. **موصى بحذفه** من المستودع لتجنّب تعديل الملف الخطأ.

### 5.3 تحدّيات بنيوية
- `core/remote_server.py` ما زال ~2090 سطرًا ويجمع HTTP + الملفات + البث + المصادقة + QR (God class).
- `gui/client_web/index.html` ملف واحد بـ~2470 سطرًا (HTML + CSS + JS) بلا فصل وحدات.
- تغطية `gui/api.py` 34% و`input_controller` 24% و`kiosk_lock` 23% — أي أن أخطر الطبقات (الجسر والقفل) هي الأقل اختبارًا.
- pywebview لا يعمل في بيئة headless، لذا لا توجد اختبارات UI آلية للنوافذ.
- الشهادة المستخدمة للتوقيع **ذاتية** (`cert/ARN_Technology_Root.cer`) وموقّع بها ملفات المثبّت؛ المتصفحات/Windows ستحذّر ما لم تُثبَّت الشهادة.
- `ANDROID_APP_BLUEPRINT.md` يصف عقود API قديمة (`status{name}`، `file`، `oldPath/newPath`، `/api/wol`، UDP 44444) تخالف الخادم الحالي.
- ملف `.agents/AGENTS.md` يوجّه إلى PyQt6/QLocalServer بينما التنفيذ pywebview/TCP — تعليمات مضلِّلة لأي وكيل أو مطوّر جديد.

---

## 6) توصيات الوصول إلى درجة الاحتراف والكمال

### أولًا: خلال أسبوع (مكاسب سريعة، أثر أمني/تشغيلي عالٍ)

1. **CI إلزامي على GitHub Actions**: مصفوفة `windows-latest` + `ubuntu-latest`، خطوات: `ruff` (F821/F811/F401) → `pytest` → `node --check` للسكربتات → بناء EXE على Windows → رفع المخرجات كـArtifacts.
2. **حماية الفرع `main`**: منع الدفع المباشر، طلب مراجعة، وتشغيل الفحوصات قبل الدمج.
3. **سياسة كلمات المرور**: حد أدنى 10 أحرف، منع `admin`/`password`، وإظهار مؤشر قوة في الواجهة (الخادم يتحقق منها أيضًا في `remote_set_credentials`).
4. **تدوير الجلسات من الواجهة**: زر «طرد كل الأجهزة» يستدعي `revoke_sessions()`، وعرض عدد الجلسات النشطة.
5. **حذف `ShutdownPanel/`** وتحديث `.agents/AGENTS.md` ليطابق pywebview.
6. **تغطية النقاط الميتة**: إضافة اختبارات لـ`revoke_sessions` و`is_app_data_path` و`fonts traversal` و`pause/resume` (بعضها أُضيف بالفعل في `tests/test_security.py`).

### ثانيًا: خلال شهر (جودة معمارية)

7. **تفكيك `remote_server.py`** إلى حزمة:
   `remote/http.py` (Router + Auth + RateLimit)، `remote/files.py`، `remote/screen.py`، `remote/qr.py`، `remote/session.py`.
   الفائدة: اختبار الوحدات بلا سوكيت، وتقليل الاقتران.
8. **رفع التغطية إلى 80%+** مع التركيز على `gui/api.py` و`input_controller` و`kiosk_lock`، وإدخال `pytest-freezegun`/`freezegun` لاختبار الجدولة والعدّاد زمنيًا بدل `sleep`.
9. **اختبارات عقد API**: جدول واحد يصف كل نقطة (method/path/payload/response) وتوليد اختبارات منه، لمنع تكرار فجوة `hotkey` و`moveto`.
10. **CSP بدون `unsafe-inline`**: نقل سكربتات `mobile.html` إلى ملفات خارجية مع nonce، وإزالة معالجات `onclick` المضمّنة تدريجيًا.
11. **HTTPS افتراضيًا + تدفق اقتران آمن**: QR يحمل توكنًا قصير العمر (5 دقائق) ثم يُستبدل بجلسة، بدل وضع التوكن الرئيسي في رابط دائم.
12. **فصل الواجهة**: تقسيم `client_web` إلى `app.js` + `styles.css` + قوالب، واستخدام Vite/ESBuild للبناء المصغّر. هذا سيعيد ملفات `client_web/app.js` و`styles.css` التي كانت الوثائق تدّعي وجودها.

### ثالثًا: خلال ربع سنة (احترافية كاملة)

13. **API مُصدَّر بـOpenAPI** (`/api/v1/...`) مع توافق خلفي وتوثيق تلقائي، وتسمية موحّدة (`percent` بدل `brightness`/`percent`، و`move_to` فقط).
14. **إدارة أسرار النظام**: استخدام Windows Credential Manager أو DPAPI لتشفير الـhash، بدل ملف JSON — حتى لو تسرّب الملف لا يُستخدم مباشرة.
15. **توقيع بكود CA حقيقي** (أو Azure Trusted Signing / EV) بدل الشهادة الذاتية، مع خط أنابيب توقيع RFC-3161 موجود بالفعل.
16. **Telemetry اختيارية + تقارير أعطال** (Sentry/بأذن المستخدم) مع Structured Logging و`request_id` وتدوير السجلات.
17. **خطة إصدار**: SemVer + Release Notes + قناة Beta + ترقية تلقائية موقّعة (بدل `update_installed.ps1` اليدوي).
18. **إتاحة (Accessibility)**: ARIA، إدارة التركيز في نوافذ الحوار والقفل، تباين ألوان AA، واختبارات RTL/LTR.
19. **توثيق مصدر واحد**: موقع docs أو `docs/` مع مصفوفة دعم المنصات (Windows كامل، Linux/macOS جزئي) وتوثيق كل نقطة API.
20. **إزالة الدَّين المتبقي**: حذف `ANDROID_APP_BLUEPRINT.md` أو إعادة كتابته، وتوحيد أسماء الثيمات، وحذف الأيقونات غير المستخدمة (8 من 14)، وحذف `--radius` غير المستخدم.

---

## 7) خطة 30/60/90 يومًا

| المرحلة | المخرجات | معيار القبول |
|---|---|---|
| **0–30 يوم** | CI + حماية main + حد كلمات المرور + طرد الجلسات + حذف المجلد المكرر | كل PR يمر بـruff+pytest؛ لا أسرار نصية في القرص |
| **31–60 يوم** | تفكيك `remote_server` + 80% تغطية + CSP nonce + عقد API موحّد | انخفاض حجم أكبر ملف إلى <600 سطر؛ صفر `unsafe-inline` |
| **61–90 يوم** | OpenAPI + توقيع CA + تحديث تلقائي موقّع + docs | إصدار 2.1.0 موقّع ومثبّت بلا تحذيرات SmartScreen |

---

## 8) ملحق: الملفات الرئيسية المتأثرة

**جديدة:** `core/security.py`، `tests/test_security.py`، `ShutdownPanel.spec`، `ShutdownPanelClient.spec`، `assets/icon.ico`، خطّا Cairo اللاتينيان.

**معدّلة جوهريًا:** `core/remote_server.py`، `core/settings.py`، `core/schedules.py`، `core/commander.py`، `core/input_controller.py`، `core/kiosk_lock.py`، `gui/api.py`، `gui/client_api.py`، `gui/web/{index.html,app.js,i18n.js,mobile.html,lock_screen.html,widget.html,countdown_overlay.html}`، `gui/client_web/index.html`، `build_exe.py`، `installer.iss`، `.gitignore`، الوثائق الثلاث.

**تم التحقق من عدم وجود:** أخطاء `F821` (أسماء غير معرّفة)، `F811` (تعريفات مكررة)، `F401/F841` (استيرادات/متغيرات ميتة)، مراجع `getElementById` لعناصر غير موجودة، معالجات `onclick` لدوال غير موجودة، أو مفاتيح ترجمة ناقصة في الواجهات الثلاث.
