# دليل ومخطط بناء تطبيق الأندرويد الشامل — Shutdown Panel Mobile
# (Comprehensive Android App Blueprint for Google AI Studio)

> **موجّه لمنصة Google AI Studio:**
> هذا المستند يحتوي على المعمارية الكاملة، ومواصفات البروتوكولات، وجميع نقاط النهاية (APIs)، وعقود البيانات (Data Contracts)، وتصميم الشاشات لبناء تطبيق Android أصلي للتحكم بجهاز الكمبيوتر عبر تطبيق **Shutdown Panel** العامل على الشبكة المحلية (LAN).

---

## 📑 الفهرس (Table of Contents)
1. [نظرة عامة والهدف من التطبيق](#1-نظرة-عامة-والهدف-من-التطبيق)
2. [التقنية المقترحة وهيكلية المشروع](#2-التقنية-المقترحة-وهيكلية-المشروع)
3. [بروتوكول الاكتشاف التلقائي عبر الشبكة (UDP Discovery)](#3-بروتوكول-الاكتشاف-التلقائي-عبر-الشبكة-udp-discovery)
4. [المصادقة وإدارة الجلسات والأمان (Authentication & Security)](#4-المصادقة-وإدارة-الجلسات-والأمان-authentication--security)
5. [المواصفات الكاملة للـ APIs (REST & Streaming Endpoints)](#5-المواصفات-الكاملة-للـ-apis-rest--streaming-endpoints)
6. [تصميم واجهات المستخدم والشاشات (UI/UX Design & Screens)](#6-تصميم-واجهات-المستخدم-والشاشات-uiux-design--screens)
7. [أذونات نظام أندرويد وإعدادات الشبكة (Manifest & Network Config)](#7-أذونات-نظام-أندرويد-وإعدادات-الشبكة-manifest--network-config)
8. [أوامر مقترحة لاستخدامها داخل Google AI Studio (Prompting Guide)](#8-أوامر-مقترحة-لاستخدامها-داخل-google-ai-studio-prompting-guide)

---

## 1. نظرة عامة والهدف من التطبيق

* **اسم التطبيق:** Shutdown Panel Remote
* **الوظيفة:** تطبيق تحكم عن بعد للاتصال بخادم **Shutdown Panel Desktop Server** عبر شبكة Wi-Fi المحلية.
* **الميزات الرئيسية:**
  1. اكتشاف الحواسيب العاملة على الشبكة تلقائياً (Zero Configuration).
  2. مسح رمز الاستجابة السريعة (QR Code) أو كتابة اسم المستخدم/كلمة المرور للاتصال الفوري.
  3. إدارة الطاقة: إيقاف التشغيل، إعادة التشغيل، وضع النوم، قفل الشاشة، إطفاء الشاشة، تسجيل الخروج، وإلغاء الأوامر (Abort).
  4. محرك عداد تنازلي ومجدول أسبوعي.
  5. تراك باد افتراضي للتحكم بالماوس (نقرة، نقر مزدوج، زر أيمن، تمرير).
  6. لوحة مفاتيح افتراضية واختصارات سريعة (`Win+D`, `Alt+Tab`, `Ctrl+C`, `Ctrl+V`).
  7. بث مباشر لشاشة الكمبيوتر (Low-latency MJPEG Stream) مع إمكانية التقاط صور للشاشة.
  8. مستكشف ملفات متكامل: تصفح الأقراص والمجلدات، رفع ملفات، تنزيل، وحذف إلى سلة المحذوفات.
  9. مراقبة مؤشرات عتاد الكمبيوتر: CPU%, RAM%, البطارية%, درجة الحرارة، وزمن التشغيل (Uptime).
  10. التحكم بمستوى الصوت والوسائط ومزامنة الحافظة (Clipboard) و Wake-on-LAN.
  11. شاشة القفل المخصصة عن بعد (Custom Remote Lock Screen) مع فك القفل السريع (Remote Unlock) بدون إدخال كلمة المرور.
  12. نافذة "حول البرنامج" (About ARN Technology) بهوية المطور عبده رجب نصار وروابط التواصل الاجتماعي المباشرة.

---

## 2. التقنية المقترحة وهيكلية المشروع

### التقنية الموصى بها داخل Google AI Studio:
* **Flutter (Dart)** (الخيار الأسهل والأسرع لإنشاء واجهة متطابقة وعصرية، مع حزم جاهزة لـ UDP و Camera و MJPEG).
* *أو:* **Kotlin + Jetpack Compose** (لتطبيق Native 100%).

### هيكلية المشروع المقترحة (Flutter Architecture):
```
lib/
├── main.dart
├── core/
│   ├── api/
│   │   ├── api_client.dart       # إدارة طلبات HTTP والمصادقة (Dio/Http)
│   │   └── endpoints.dart        # ثوابت روابط الـ API
│   ├── discovery/
│   │   └── udp_discovery.dart    # الاستماع لإشارات UDP على المنفذ 44444
│   ├── models/
│   │   ├── server_info.dart      # نموذج الخادم المكتشف
│   │   ├── system_stats.dart     # نموذج إحصائيات النظام والعتاد
│   │   └── file_item.dart        # نموذج عناصر الملفات والمجلدات
│   └── storage/
│       └── connection_storage.dart # حفظ الخوادم المتصلة والمفضلة (SharedPreferences)
├── ui/
│   ├── theme/
│   │   └── app_theme.dart        # الثيم الداكن (الأزرق الليلي مع إضاءات Cyan)
│   ├── screens/
│   │   ├── connection_screen.dart # شاشة البحث التلقائي ومسح QR والاتصال اليدوي
│   │   ├── dashboard_screen.dart  # لوحة التحكم الرئيسية والعداد التنازلي
│   │   ├── trackpad_screen.dart   # شاشة التراك باد ولوحة المفاتيح
│   │   ├── screen_stream_screen.dart # شاشة بث الشاشة الحية
│   │   ├── files_screen.dart      # شاشة مستكشف الملفات
│   │   └── media_tools_screen.dart # شاشة الوسائط والحافظة و WoL
│   └── widgets/
│       ├── power_action_button.dart
│       └── circular_countdown.dart
```

---

## 3. بروتوكول الاكتشاف التلقائي عبر الشبكة (UDP Discovery)

خادم الديسكتوب يبث إشارات دورية (كل 3 ثوانٍ) عبر بروتوكول UDP Broadcast:
* **المنفذ (Port):** `44444`
* **نوع البث:** `UDP Broadcast` (`255.255.255.255` أو شبكة الـ Subnet)
* **صيغة الحزمة (JSON Payload):**
```json
{
  "app": "ShutdownPanel",
  "name": "MY-GAMING-PC",
  "port": 8080
}
```
* **آلية عمل التطبيق:**
  1. يفتح التطبيق مقبس UDP (`RawDatagramSocket.bind(InternetAddress.anyIPv4, 44444)`).
  2. يستمع للرسائل الواردة، ويستخرج منها عنوان الـ IP الخاص بالمرسل (`datagram.address.address`).
  3. يتحقق أن الحقل `"app" == "ShutdownPanel"`.
  4. يضيف الجهاز تلقائياً إلى قائمة الأجهزة المكتشفة المتاحة للاتصال بنقرة واحدة!

---

## 4. المصادقة وإدارة الجلسات والأمان (Authentication & Security)

### طرق المصادقة المدعومة:
1. **طريقة مسح رمز الاستجابة السريعة (QR Code):**
   * الكود الممسوح يحتوي على: `http://<IP>:<PORT>/?token=<MASTER_TOKEN>`
   * يقوم التطبيق باستخراج الـ IP والمنفذ والـ Token وحفظها.
2. **طريقة تسجيل الدخول (Username / Password):**
   * إرسال طلب `POST /api/auth/login` ببيانات المستخدم.
   * يقوم السيرفر بإرجاع `session_token` صالح للجلسة الحالية.

### إرسال الرمز مع كل طلب (Header):
يجب تضمين الرمز في ترويسة جميع الطلبات:
```http
X-Auth-Token: <TOKEN>
# أو
Authorization: Bearer <TOKEN>
```
*(أو تمريره في الروابط كمعامل: `?token=<TOKEN>` في روابط البث وتحميل الملفات).*

---

## 5. المواصفات الكاملة للـ APIs (REST & Streaming Endpoints)

### 1) التحقق من الاتصال (Public Status)
* **المسار:** `GET /api/status`
* **المصادقة:** عام (لا يتطلب رمز)
* **الاستجابة الناجحة (200 OK):**
```json
{
  "ok": true,
  "app": "ShutdownPanel",
  "version": "2.0.0",
  "name": "MY-PC"
}
```

---

### 2) تسجيل الدخول (Auth Login)
* **المسار:** `POST /api/auth/login`
* **الترويسة:** `Content-Type: application/json`
* **البيانات (Body):**
```json
{
  "username": "admin",
  "password": "your_password"
}
```
* **الاستجابة الناجحة (200 OK):**
```json
{
  "ok": true,
  "token": "A1B2C3D4E5F6..."
}
```

---

### 3) تنفيذ أوامر الطاقة والعداد (Power & Timer Commands)
* **المسار:** `POST /api/command`
* **المصادقة:** مطلوبة
* **البيانات (Body):**
```json
{
  "action": "shutdown",   // الخيارات: "shutdown", "restart", "sleep", "lock", "signout", "display_off"
  "delaySecs": 1800,      // التأخير بالثواني (0 = فوري)
  "force": false          // إجبار إغلاق البرامج دون انتظار الحفظ
}
```
* **الاستجابة:**
```json
{
  "ok": true,
  "display": "shutdown.exe /s /t 1800"
}
```

---

### 4) إلغاء الأوامر والعداد المجدول (Abort Command)
* **المسار:** `POST /api/abort`
* **المصادقة:** مطلوبة
* **الاستجابة:**
```json
{
  "ok": true,
  "message": "Countdown aborted"
}
```

---

### 5) استعلام مؤشرات العتاد والنظام (System Summary)
* **المسار:** `GET /api/system/summary`
* **المصادقة:** مطلوبة
* **الاستجابة (200 OK):**
```json
{
  "ok": true,
  "cpu": 24.5,
  "ram": {
    "percent": 48.2,
    "used_mb": 7800,
    "total_mb": 16384
  },
  "battery": {
    "percent": 95,
    "power_plugged": true
  },
  "disk": {
    "percent": 65.0
  },
  "uptime": 14500,
  "temp": 48.5,
  "countdown": {
    "active": true,
    "remainingSecs": 1250,
    "totalSecs": 1800,
    "action": "shutdown",
    "paused": false
  }
}
```

---

### 6) بث الشاشة المباشر (Live Screen MJPEG Stream)
* **المسار:** `GET /api/screen/stream?fps=30&scale=0.8&q=65&token=<TOKEN>`
* **المصادقة:** عبر الـ query parameter `token`
* **نوع المحتوى:** `multipart/x-mixed-replace; boundary=frame`
* **طريقة العرض في أندرويد:**
  * استخدام قارئ MJPEG Stream جاهز (مثل مكتبة `flutter_mjpeg` أو قراءة الإطارات كـ `HttpStream`).
* **لقطة شاشة ثابتة (Snapshot):**
  * `GET /api/screen/frame?scale=0.8&q=80&token=<TOKEN>` (يرجع صورة JPEG مفردة).

---

### 7) التحكم بالماوس والتراك باد (Mouse Input)
* **المسار:** `POST /api/input/mouse`
* **المصادقة:** مطلوبة
* **البيانات (Body):**
```json
{
  "dx": 12.5,          // حركة الماوس الأفقية
  "dy": -5.0,          // حركة الماوس الرأسية
  "click": "left",     // اختياري: "left", "right", "double"
  "scroll": 0.0        // اختياري: قيمة التمرير (Scroll)
}
```

---

### 8) محاكاة لوحة المفاتيح (Keyboard Input)
* **المسار:** `POST /api/input/keyboard`
* **المصادقة:** مطلوبة
* **كتابة نص:**
```json
{ "text": "مرحباً بكم / Hello World" }
```
* **ضغط مفتاح خاص أو اختصار:**
```json
{ "key": "enter" }
// أو اختصار:
{ "hotkey": ["ctrl", "alt", "del"] }
{ "hotkey": ["win", "d"] }
{ "hotkey": ["alt", "tab"] }
```

---

### 9) التحكم بالوسائط والصوت (Media & Volume)
* **المسار:** `POST /api/media`
* **المصادقة:** مطلوبة
* **البيانات (Body):**
```json
// للتحكم بالصوت (من 0 إلى 100):
{ "action": "volume", "value": 75 }

// للتحكم بالتشغيل:
{ "action": "play_pause" } // أو "next", "prev", "stop"
```

---

### 10) مستكشف الملفات (File Manager)
* **استعراض الملفات والأقراص:**
  * `GET /api/fs/list?path=<ENCODED_PATH>&token=<TOKEN>`
  * *عند تمرير `path` فارغ يرجع قائمة الأقراص (`C:\`, `D:\`).*
  * **الاستجابة:**
  ```json
  {
    "ok": true,
    "currentPath": "D:\\Projects",
    "drives": [{"name": "C:\\", "total": "500GB", "free": "120GB"}],
    "breadcrumbs": [{"name": "D:", "path": "D:\\"}, {"name": "Projects", "path": "D:\\Projects"}],
    "items": [
      {"name": "Folder1", "isDir": true, "size": 0, "mtime": 1700000000},
      {"name": "Document.pdf", "isDir": false, "size": 2450000, "mtime": 1700000000}
    ]
  }
  ```
* **تنزيل ملف:**
  * `GET /api/fs/download?path=<ENCODED_PATH>&token=<TOKEN>` (يدعم استئناف التحميل عبر `Range Header`).
* **رفع ملف:**
  * `POST /api/fs/upload` (Multipart Form Data مع حقل `file` وحقل `target_path`).
* **حذف ملف (آمن إلى سلة المحذوفات):**
  * `POST /api/fs/delete` مع Body: `{"path": "D:\\Folder\\file.txt"}`.
* **إعادة تسمية:**
  * `POST /api/fs/rename` مع Body: `{"oldPath": "...", "newPath": "..."}`.

---

### 11) مزامنة الحافظة و Wake-on-LAN
* **قراءة حافظة الكمبيوتر:** `GET /api/clipboard` -> `{"ok": true, "text": "..."}`
* **إرسال نص لحافظة الكمبيوتر:** `POST /api/clipboard` -> `{"text": "محتوى الحافظة"}`
* **إيقاظ كمبيوتر آخر عبر الشبكة:** `POST /api/wol` -> `{"mac": "AA:BB:CC:DD:EE:FF"}`

---

### 12) شاشة القفل المخصصة عن بعد (Custom Remote Lock Screen)
* **الاستعلام عن حالة القفل (Lock Status):**
  * **المسار:** `GET /api/lock/status`
  * **المصادقة:** مطلوبة
  * **الاستجابة:**
  ```json
  {
    "ok": true,
    "locked": true,             // هل شاشة القفل مفعّلة حالياً
    "message": "الجهاز تحت الصيانة - يرجى عدم لمس الحاسوب"
  }
  ```
* **تفعيل قفل الشاشة عن بعد (Activate Remote Lock):**
  * **المسار:** `POST /api/lock/activate`
  * **المصادقة:** مطلوبة
  * **البيانات (Body):**
  ```json
  {
    "message": "الجهاز تحت الصيانة - يرجى عدم لمس الحاسوب"
  }
  ```
  * **الاستجابة:**
  ```json
  {
    "ok": true,
    "message": "Custom lock screen activated"
  }
  ```
  *(ملاحظة: يمكن أيضاً تفعيلها عبر `POST /api/command` بإرسال `{"action": "custom_lock", "message": "..."}`).*
* **فك القفل عن بعد (Remote Unlock):**
  * **المسار:** `POST /api/lock/unlock`
  * **المصادقة:** مطلوبة
  * **البيانات (Body):** `{}`
  * **الاستجابة:**
  ```json
  {
    "ok": true,
    "message": "Custom lock screen unlocked"
  }
  ```

---

### 13) التحكم بسطوع الشاشة وفتح الروابط (Brightness & Open URL)
* **ضبط سطوع الشاشة (0 إلى 100):**
  * `POST /api/system/brightness` مع Body: `{"brightness": 75}`
* **فتح رابط فوري في متصفح الكمبيوتر:**
  * `POST /api/system/open_url` مع Body: `{"url": "https://youtube.com"}`

---

## 6. تصميم واجهات المستخدم والشاشات (UI/UX Design & Screens)

### الثيم البصري (Design System):
* **النمط:** Modern Cyber Dark / Glassmorphism
* **الألوان:**
  * الخلفية الرئيسية: `#070c16` (Deep Dark Navy)
  * خلفية الكروت والألواح: `#0d1726` (Panel Surface)
  * لون التمييز الأساسي: `#06b6d4` (Vibrant Cyan)
  * لون التحذير والخطر: `#ef4444` (Red Rose)
  * لون النجاح: `#10b981` (Emerald Green)
  * الخطوط الموصى بها: `Cairo` للغة العربية و `Outfit` للغة الإنجليزية والأرقام.

### الشاشات الرئيسية الستة:
1. **شاشة الاتصال (Connection Screen):**
   * عرض تلقائي لأجهزة الكمبيوتر المكتشفة مع اسم الجهاز وأيقونة خادم نابضة.
   * زر لمسح الـ QR Code مباشرة للاقتران الفوري.
   * خيار الإدخال اليدوي (IP + المنفذ + اسم المستخدم وكلمة المرور).
2. **لوحة التحكم والمؤقت (Dashboard & Timer):**
   * عداد تنازلي دائري حي يعرض الوقت المتبقي.
   * أزرار مدة جاهزة سريعة (15 دقيقة، 30 دقيقة، ساعة، ساعتان).
   * أزرار اختيار نوع الإجراء (إيقاف تشغيل، نوم، إعادة تشغيل، قفل).
   * شبكة أزرار للإجراءات الفورية السريعة وزر إلغاء العداد البارز.
3. **التراك باد والفأرة (Trackpad & Control):**
   * منطقة لمس ناعمة تأخذ معظم الشاشة مع دعم الحركات (إصبع للحركة، نقرة للزر الأيسر، إصبعان للزر الأيمن).
   * شريط جانبي للتمرير (Vertical Scroll).
   * صف أزرار لاختصارات ويندوز السريعة (`Win+D`, `Alt+Tab`, `Esc`, إلخ).
4. **بث الشاشة الحي (Live Screen):**
   * عرض بث الشاشة بجودة ديناميكية وسرعة استجابة عالية.
   * أزرار للتحكم بنسبة التكبير والتقاط لقطة فورية وتدوير الشاشة أفقياً (Landscape).
5. **مستكشف الملفات (File Explorer):**
   * شريط مسارات علوي (Breadcrumbs) للتنقل السلس بين المجلدات.
   * استعراض الأقراص والملفات مع أحجامها وتواريخها.
   * زر عائم لرفع الملفات من الهاتف إلى الكمبيوتر، وقائمة خيارات لكل ملف (تنزيل، حذف، إعادة تسمية).
6. **الوسائط والعتاد (Media & Hardware Stats):**
   * مؤشرات حية لنسبة استهلاك المعالج والذاكرة والبطارية.
   * منزلق للتحكم الدقيق بمستوى صوت الكمبيوتر وأزرار التحكم بالموسيقى.
   * مزامنة الحافظة النصية المتبادلة بين الهاتف والكمبيوتر.
7. **كرت قفل الشاشة المخصص وفك القفل عن بعد (Custom Remote Lock Card):**
   * كرت تفاعلي يتغير شكله تلقائياً حسب حالة القفل المستعلم عنها دورياً من الخادم (`/api/lock/status`):
   * **الحالة 1 — عندما يكون الجهاز غير مقفل (Unlocked):**
     * حقل كتابة لإدخال نص الرسالة التنبيهية التي ستظهر على شاشة الكمبيوتر بالحجم الكامل.
     * رقاقات أزرار جاهزة (Quick Presets Chips):
       - "تحت الصيانة 🛠️" -> "الجهاز تحت الصيانة - يرجى عدم لمس الحاسوب"
       - "إجازة قصيرة ☕" -> "إجازة قصيرة - سأعود بعد قليل"
       - "ممنوع اللمس ⚠️" -> "تم قفل الجهاز لأسباب أمنية - يرجى الابتعاد"
     * زر تفعيل القفل الأساسي باللون الأزرق المتدرج (`#0284c7` إلى `#0369a1`): `🔒 تفعيل قفل الشاشة الآن`.
   * **الحالة 2 — عندما يكون الجهاز مقفلاً حالياً (Locked):**
     * شارة تحذيرية حمراء مع وميض نابض (Pulsing Dot): `🔴 شاشة الكمبيوتر مقفلة حالياً عن بعد!`.
     * كادر داكن يعرض نص الرسالة الحالية المعروضة على شاشة الكمبيوتر.
     * زر بارز ونابض باللون الأخضر الزمردي (`#10b981` إلى `#059669`): `🔓 فك القفل عن بعد (Remote Unlock)` يتيح للمسؤول إلغاء القفل فورياً من الموبايل بدون لمس الحاسوب أو إدخال كلمة المرور.
8. **نافذة حول البرنامج والمطور (About ARN Technology Dialog):**
   * نافذة منبثقة بتصميم أنيق داكن (`#0f172a`).
   * اسم الشركة: **ARN Technology**.
   * اسم المطور: `تطوير وبرمجة: عبده رجب نصار` باللون الأخضر الزمردي (`#10b981`).
   * حقوق الملكية: `حقوق النشر (c) 2026 لشركة ARN Technology. جميع الحقوق محفوظة.`
   * أزرار تواصل دائرية أنيقة (`border-radius: 25px`):
     - **WhatsApp:** `https://wa.me/201556710314`
     - **Telegram:** `https://t.me/ABDOURNASSAR95`
     - **Facebook:** `https://www.facebook.com/abdouragab.nassar`
     - **Messenger:** `https://m.me/abdouragab.nassar`

---

## 7. أذونات نظام أندرويد وإعدادات الشبكة (Manifest & Network Config)

### 1) الأذونات في `AndroidManifest.xml`:
```xml
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
<uses-permission android:name="android.permission.ACCESS_WIFI_STATE" />
<!-- للسماح بالاستماع لبث الـ UDP Broadcast في شبكة الواي فاي -->
<uses-permission android:name="android.permission.CHANGE_WIFI_MULTICAST_STATE" />
<!-- لمسح رمز QR الخاص بالاقتران -->
<uses-permission android:name="android.permission.CAMERA" />
<!-- للاهتزاز اللمسي أثناء النقر على التراك باد -->
<uses-permission android:name="android.permission.VIBRATE" />
```

### 2) السماح باتصالات الشبكة المحلية (Cleartext Traffic):
نظراً لأن السيرفر يعمل افتراضياً على `http://` في الشبكة المحلية:
في `AndroidManifest.xml` داخل وسام `<application>`:
```xml
android:usesCleartextTraffic="true"
```

---

## 8. أوامر مقترحة لاستخدامها داخل Google AI Studio (Prompting Guide)

يمكنك نسخ الأوامر التالية مباشرة في Google AI Studio:

### البرومبت 1: توليد خدمة الاتصال والاكتشاف التلقائي
> "قم ببناء كلاس Dart في Flutter باسم `ServerDiscoveryService` يقوم بفتح مقبس UDP والاستماع على المنفذ `44444` لاستقبال حزم JSON التي تبثها أجهزة الكمبيوتر بصيغة `{'app': 'ShutdownPanel', 'name': string, 'port': int}` واستخراج عنوان IP الخاص بكل جهاز وإضافته لقائمة أجهزة مكتشفة بدون تكرار."

### البرومبت 2: توليد عميل الـ API وإدارة المصادقة
> "قم بإنشاء كلاس `ShutdownApiClient` لإدارة كافة طلبات HTTP إلى الخادم الموضح في مخطط المشروع، بحيث يدعم تخزين رمز المصادقة `token` وإرساله تلقائياً في الترويسة `X-Auth-Token`، مع دوال لتسجيل الدخول، وإرسال أمر إيقاف التشغيل، واستعلام إحصائيات المعالج والذاكرة."

### البرومبت 3: بناء واجهة التراك باد للتحكم بالماوس
> "قم ببرمجة ويدجت `TrackpadArea` في Flutter يتيح للمستخدم تحريك إصبعه على الشاشة وحساب فروق الإحداثيات (`dx`, `dy`) وإرسالها عبر `POST /api/input/mouse` مع Throttle خفيف لمنع إغراق الشبكة، ودعم النقر بإصبع واحد للزر الأيسر ونقر بإصبعين للزر الأيمن مع اهتزاز لمسي خفيف `HapticFeedback.lightImpact()`."

### البرومبت 4: بناء قارئ بث الشاشة المباشر
> "قم ببرمجة شاشة `LiveScreenViewer` في Flutter تقوم بقراءة وعرض بث الـ MJPEG المباشر القادم من الرابط `/api/screen/stream` الخاص بالخادم وعرض الإطارات بسلاسة مع دعم وضع الشاشة الكاملة والوضع الأفقي (Landscape)."

### البرومبت 5: إضافة ميزة شاشة القفل المخصصة وفك القفل عن بعد (Custom Remote Lock Screen)
> "لدينا تطبيق Shutdown Panel Remote مكتوب بلغة (Flutter / Kotlin). أريد إضافة ميزة قفل شاشة الكمبيوتر عن بعد بنافذة كشك مخصصة وفك القفل عن بعد.
> قم بتعديل عميل الـ API بإضافة الدوال التالية:
> 1. `getLockStatus()` عبر `GET /api/lock/status` لإرجاع `{ 'locked': bool, 'message': String }`.
> 2. `activateLock(String message)` عبر `POST /api/lock/activate` مع إرسال `{ 'message': message }`.
> 3. `remoteUnlock()` عبر `POST /api/lock/unlock` مع كائن فارغ `{}`.
> ثم أضف في لوحة التحكم كرت تفاعلي `CustomLockCard`:
> - يستعلم دورياً عن حالة القفل مع تحديث الإحصائيات (كل ثانية إلى ثانيتين).
> - إذا كان الجهاز غير مقفل (`locked == false`)، يعرض حقل كتابة لرسالة القفل مع 3 أزرار لاختيار رسائل جاهزة سريعة، وزر أزرق أنيق `🔒 تفعيل قفل الشاشة الآن`.
> - إذا كان الجهاز مقفلاً (`locked == true`)، يعرض شارة تحذيرية حمراء بأن الكمبيوتر مقفل حالياً مع إظهار الرسالة الحالية، وزر أخضر زمردي بارز `🔓 فك القفل عن بعد (Remote Unlock)` لفتح الكمبيوتر بنقرة واحدة."

### البرومبت 6: إضافة نافذة "حول التطبيق والمطور" لهوية شركة ARN Technology
> "قم بإضافة نافذة منبثقة About Dialog في التطبيق تفتح عند النقر على أيقونة الإعدادات أو معلومات التطبيق:
> - تصميم داكن أنيق بلون خلفية `#0f172a`.
> - العنوان: 'حول التطبيق — ARN Technology'.
> - اسم المطور: 'تطوير وبرمجة: عبده رجب نصار' بلون أخضر زمردي `#10b981`.
> - نص الحقوق: 'حقوق النشر (c) 2026 لشركة ARN Technology. جميع الحقوق محفوظة.'.
> - أزرار دائرية للسوشيال ميديا تفتح الروابط عبر `url_launcher`:
>   * WhatsApp: https://wa.me/201556710314
>   * Telegram: https://t.me/ABDOURNASSAR95
>   * Facebook: https://www.facebook.com/abdouragab.nassar
>   * Messenger: https://m.me/abdouragab.nassar"

---
**جاهز للتنفيذ والتطوير فوراً داخل Google AI Studio!** 🚀

