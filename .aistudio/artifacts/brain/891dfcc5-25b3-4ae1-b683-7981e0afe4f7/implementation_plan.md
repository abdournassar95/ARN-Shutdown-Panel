# خطة تطوير ARN Shutdown Panel — خط كايرو، رفع المجلدات، تنزيل ZIP، وماسح QR Code

## 📋 أهداف التحديث
1. **تطبيق خط كايرو (Cairo) في كامل واجهات التطبيق**: اعتماد خط كايرو العربي الأنيق كخط النظام الأساسي لجميع النصوص، الحقول، الأزرار، والصفحات.
2. **دعم رفع مجلد كامل من الهاتف إلى الحاسوب (Folder Upload)**: إتاحة خيار للمستخدم عند النقر على زر الرفع للاختيار بين "رفع ملفات" أو "رفع مجلد كامل" عبر `ACTION_OPEN_DOCUMENT_TREE`، وقراءة جميع ملفات المجلد ورفعها دفعة واحدة.
3. **حل مشكلة عدم ظهور ملفات ZIP المنزلة في الهاتف**: ضبط امتداد `.zip` للمجلدات وتحديث فهرس النظام فوراً عبر `MediaScannerConnection.scanFile` ليظهر الأرشيف فوراً في تطبيق "الملفات" ومجلد التنزيلات.
4. **ماسح QR Code سريع بكاميرا الهاتف (In-App Bottom Sheet)**: إضافة زر في شاشة البوابة لفتح نافذة سفلية (Bottom Sheet) تمسح رمز QR من شاشة الكمبيوتر، وتقرأ عنوان IP ورقم المنفذ وتملأ الحقول وتتصل تلقائياً.
5. **أذونات الكاميرا**: تضمين إذن الكاميرا `android.permission.CAMERA` في `AndroidManifest.xml` وإدارته وقت التشغيل بانسيابية.

---

## 🛠️ خطة التنفيذ التفصيلية

### 1. إعدادات الخطوط والسمات (`res/values/themes.xml` + `font/cairo.ttf`)
- تم تثبيت خط `cairo.ttf` عبر أداة `font-util`.
- ربط الخط في `Theme.ARNShutdown` عبر:
  `<item name="android:fontFamily">@font/cairo</item>`
  `<item name="fontFamily">@font/cairo</item>`
- تحديث صفحة الـ HTML للاسترداد لتستخدم خط `Cairo`.

### 2. مكتبات مسح QR Code والأذونات (`build.gradle.kts` & `AndroidManifest.xml`)
- إضافة إذن الكاميرا:
  `<uses-permission android:name="android.permission.CAMERA" />`
  `<uses-feature android:name="android.hardware.camera" android:required="false" />`
- إضافة مكتبة `com.journeyapps:zxing-android-embedded:4.3.0` و `com.google.zxing:core:3.5.3` لمسح رموز QR بكفاءة عالية داخل نافذة الـ Bottom Sheet.

### 3. دعم رفع المجلدات في `WebWrapperActivity.kt`
- عند استدعاء `onShowFileChooser`:
  عرض نافذة حوارية سفلية للمستخدم:
  - **📄 رفع ملفات محددة:** تفتح محدد الملفات التقليدي.
  - **📁 رفع مجلد كامل:** تفتح `Intent.ACTION_OPEN_DOCUMENT_TREE`.
- عند اختيار مجلد:
  قراءة شجرة المجلد عبر `DocumentFile` واستخراج روابط جميع الملفات بداخله وتمريرها لمحدد الويب لرفعها مباشرة للخادم.

### 4. معالجة تنزيل المجلدات المضغوطة ZIP
- في `setDownloadListener`:
  التحقق من أن المجلدات المنزلة تحتفظ بامتداد `.zip` ونوع المحتوى `application/zip`.
- في مستلم انتهاء التنزيل `downloadCompleteReceiver`:
  تشغيل `MediaScannerConnection.scanFile` لفهرسة الملف المضغوط في وسائط أندرويد وتطبيق "الملفات" فور اكتمال التنزيل لضمان ظهوره الفوري.

### 5. واجهة ماسح QR Code في `GatewayActivity.kt` و `activity_gateway.xml`
- إضافة زر ماسح الكاميرا بجانب حقول الاتصال: `📷 مسح كود QR من شاشة الحاسوب`.
- تصميم تخطيط `layout_qr_scanner_bottom_sheet.xml` بتصميم داكن وفريم ماسح متحرك.
- تحليل الكود المقروء (يدعم `IP:PORT` أو `http://IP:PORT` أو JSON `{"ip":"...","port":...}`).
- تعبئة الحقول تلقائياً وإعطاء تنبيه اهتزازي بالنجاح ثم الاتصال التلقائي.

---

## ✅ التحقق والاختبار
- [x] تجميع التطبيق بنجاح وتأكيد ظهور خط كايرو.
- [x] اختبار ظهور خيار رفع المجلدات وقراءة ملفات المجلد.
- [x] اختبار حفظ ملفات ZIP وفهرستها بنجاح في مجلد التنزيلات.
- [x] اختبار طلب إذن الكاميرا وتشغيل ماسح الـ QR في الـ Bottom Sheet واستخراج IP والمنفذ بدقة.
