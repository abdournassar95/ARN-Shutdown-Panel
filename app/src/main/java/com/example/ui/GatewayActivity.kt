package com.example.ui

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.VibrationEffect
import android.os.Vibrator
import android.view.View
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.example.R
import com.example.data.ServerSession
import com.example.data.SessionManager
import com.example.databinding.ActivityGatewayBinding
import com.example.network.DiscoveredHost
import com.example.network.UDPDiscoveryManager
import com.google.android.material.bottomsheet.BottomSheetDialog
import com.google.zxing.ResultPoint
import com.journeyapps.barcodescanner.BarcodeCallback
import com.journeyapps.barcodescanner.BarcodeResult
import com.journeyapps.barcodescanner.CompoundBarcodeView
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL

class GatewayActivity : AppCompatActivity() {

    private lateinit var binding: ActivityGatewayBinding
    private lateinit var sessionManager: SessionManager
    private lateinit var discoveryManager: UDPDiscoveryManager

    private val discoveredList = mutableListOf<DiscoveredHost>()
    private lateinit var spinnerAdapter: ArrayAdapter<String>
    private var autoLoginJob: Job? = null

    // Camera permission launcher for QR code scanner
    private val cameraPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { isGranted ->
        if (isGranted) {
            openQrScannerBottomSheet()
        } else {
            Toast.makeText(this, "يرجى منح صلاحية الكاميرا لمسح كود QR من شاشة الحاسوب", Toast.LENGTH_LONG).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityGatewayBinding.inflate(layoutInflater)
        setContentView(binding.root)

        sessionManager = SessionManager(this)
        discoveryManager = UDPDiscoveryManager(this)

        initViews()
        setupSocialLinks()
        checkAutoLogin()
    }

    private fun initViews() {
        spinnerAdapter = ArrayAdapter(
            this,
            android.R.layout.simple_spinner_dropdown_item,
            mutableListOf("اختر حاسوباً من الشبكة...")
        )
        binding.spinnerServers.adapter = spinnerAdapter

        binding.spinnerServers.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                // position 0 is default hint if list has items
                val hostIndex = position - 1
                if (hostIndex in discoveredList.indices) {
                    val host = discoveredList[hostIndex]
                    binding.editIp.setText(host.ip)
                    binding.editPort.setText(host.port.toString())
                }
            }
            override fun onNothingSelected(parent: AdapterView<*>?) {}
        }

        binding.btnLogin.setOnClickListener {
            val ip = binding.editIp.text.toString().trim()
            val port = binding.editPort.text.toString().trim().toIntOrNull() ?: 8080
            val user = binding.editUser.text.toString().trim()
            val pass = binding.editPass.text.toString().trim()

            performLogin(ip, port, user, pass)
        }

        binding.btnScanQr.setOnClickListener {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
                == PackageManager.PERMISSION_GRANTED
            ) {
                openQrScannerBottomSheet()
            } else {
                cameraPermissionLauncher.launch(Manifest.permission.CAMERA)
            }
        }

        binding.btnRefreshDiscovery.setOnClickListener {
            binding.txtDiscoveryBadge.text = "جاري البحث..."
            discoveredList.clear()
            spinnerAdapter.clear()
            spinnerAdapter.add("اختر حاسوباً من الشبكة...")
            spinnerAdapter.notifyDataSetChanged()
            startDiscovery()
            Toast.makeText(this, "جاري إعادة فحص الشبكة المحلية بحثاً عن الخادم...", Toast.LENGTH_SHORT).show()
        }

        binding.btnCancelAutoLogin.setOnClickListener {
            autoLoginJob?.cancel()
            val last = sessionManager.getLastSession()
            showLoginUI(last?.ip ?: "", last?.port ?: 8080, last?.username ?: "admin")
        }
    }

    private fun openQrScannerBottomSheet() {
        val bottomSheet = BottomSheetDialog(this)
        val sheetView = layoutInflater.inflate(R.layout.bottom_sheet_qr_scanner, null)
        bottomSheet.setContentView(sheetView)

        val barcodeView = sheetView.findViewById<CompoundBarcodeView>(R.id.barcodeScannerView)
        val btnToggleTorch = sheetView.findViewById<Button>(R.id.btnToggleTorch)
        val btnClose = sheetView.findViewById<Button>(R.id.btnCloseScanner)

        var isTorchOn = false
        btnToggleTorch.setOnClickListener {
            isTorchOn = !isTorchOn
            if (isTorchOn) barcodeView.setTorchOn() else barcodeView.setTorchOff()
            btnToggleTorch.text = if (isTorchOn) "💡 إطفاء الفلاش" else "💡 إضاءة الفلاش"
        }

        btnClose.setOnClickListener {
            bottomSheet.dismiss()
        }

        barcodeView.decodeSingle(object : BarcodeCallback {
            override fun barcodeResult(result: BarcodeResult?) {
                val text = result?.text?.trim() ?: return
                runOnUiThread {
                    vibrateFeedback()
                    bottomSheet.dismiss()
                    handleScannedQrCode(text)
                }
            }
            override fun possibleResultPoints(resultPoints: MutableList<ResultPoint>?) {}
        })

        bottomSheet.setOnShowListener {
            barcodeView.resume()
        }
        bottomSheet.setOnDismissListener {
            barcodeView.pause()
        }

        bottomSheet.show()
    }

    private fun handleScannedQrCode(rawText: String) {
        var ip = ""
        var port = 8080

        val trimmed = rawText.trim()
        if (trimmed.startsWith("{") && trimmed.endsWith("}")) {
            try {
                val json = JSONObject(trimmed)
                ip = json.optString("ip", "")
                port = json.optInt("port", 8080)
            } catch (_: Exception) {}
        }

        if (ip.isEmpty()) {
            val cleanUrl = trimmed
                .removePrefix("http://")
                .removePrefix("https://")
                .removePrefix("arn://")
                .trimEnd('/')
            val parts = cleanUrl.split(":")
            if (parts.isNotEmpty()) {
                ip = parts[0].substringBefore("/")
                if (parts.size > 1) {
                    port = parts[1].substringBefore("/").substringBefore("?").toIntOrNull() ?: 8080
                }
            }
        }

        if (ip.isNotEmpty()) {
            binding.editIp.setText(ip)
            binding.editPort.setText(port.toString())
            Toast.makeText(this, "تم مسح الرمز بنجاح: $ip:$port ⚡", Toast.LENGTH_LONG).show()
        } else {
            Toast.makeText(this, "تعذر قراءة عنوان الخادم من الرمز الممسوح", Toast.LENGTH_SHORT).show()
        }
    }

    private fun vibrateFeedback() {
        try {
            val vibrator = getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                vibrator?.vibrate(VibrationEffect.createOneShot(120, VibrationEffect.DEFAULT_AMPLITUDE))
            } else {
                @Suppress("DEPRECATION")
                vibrator?.vibrate(120)
            }
        } catch (_: Exception) {}
    }

    private fun setupSocialLinks() {
        binding.btnSocialWhatsapp.setOnClickListener {
            openExternalUrl("https://wa.me/201556710314")
        }
        binding.btnSocialTelegram.setOnClickListener {
            openExternalUrl("https://t.me/ABDOURNASSAR95")
        }
        binding.btnSocialFacebook.setOnClickListener {
            openExternalUrl("https://www.facebook.com/abdouragab.nassar")
        }
    }

    private fun openExternalUrl(urlStr: String) {
        try {
            val intent = Intent(Intent.ACTION_VIEW, Uri.parse(urlStr))
            startActivity(intent)
        } catch (_: Exception) {
            Toast.makeText(this, "تعذر فتح الرابط", Toast.LENGTH_SHORT).show()
        }
    }

    private fun checkAutoLogin() {
        val lastSession = sessionManager.getLastSession()
        if (lastSession != null && lastSession.token.isNotEmpty()) {
            binding.layoutConnecting.visibility = View.VISIBLE
            binding.layoutLogin.visibility = View.GONE
            binding.btnCancelAutoLogin.visibility = View.VISIBLE
            binding.txtStatus.text = "جاري التحقق من الاتصال بالحاسوب (${lastSession.ip})..."

            autoLoginJob = lifecycleScope.launch(Dispatchers.IO) {
                val isValid = testTokenValidity(lastSession.ip, lastSession.port, lastSession.token)
                if (isValid) {
                    withContext(Dispatchers.Main) {
                        launchWebView(lastSession.ip, lastSession.port, lastSession.token)
                    }
                } else {
                    // Try silent auto-re-login if credentials are saved
                    if (lastSession.passwordHash.isNotEmpty()) {
                        withContext(Dispatchers.Main) {
                            binding.txtStatus.text = "جاري تجديد جلسة الاتصال بالحاسوب..."
                        }
                        val newToken = executeLoginApi(
                            lastSession.ip,
                            lastSession.port,
                            lastSession.username,
                            lastSession.passwordHash
                        )
                        if (newToken != null) {
                            sessionManager.saveSession(lastSession.copy(token = newToken))
                            withContext(Dispatchers.Main) {
                                launchWebView(lastSession.ip, lastSession.port, newToken)
                            }
                            return@launch
                        }
                    }
                    withContext(Dispatchers.Main) {
                        showLoginUI(lastSession.ip, lastSession.port, lastSession.username)
                    }
                }
            }
        } else {
            showLoginUI("", 8080, "admin")
        }
    }

    private fun showLoginUI(ip: String, port: Int, user: String) {
        binding.layoutConnecting.visibility = View.GONE
        binding.layoutLogin.visibility = View.VISIBLE
        if (ip.isNotEmpty()) {
            binding.editIp.setText(ip)
        }
        binding.editPort.setText(port.toString())
        binding.editUser.setText(user)

        startDiscovery()
    }

    private fun startDiscovery() {
        discoveryManager.startListening { host ->
            if (!discoveredList.any { it.ip == host.ip && it.port == host.port }) {
                discoveredList.add(host)
                spinnerAdapter.add("${host.pcName} (${host.ip}:${host.port})")
                spinnerAdapter.notifyDataSetChanged()

                binding.txtDiscoveryBadge.text = "تم العثور على (${discoveredList.size})"

                if (binding.editIp.text.isNullOrEmpty()) {
                    binding.editIp.setText(host.ip)
                    binding.editPort.setText(host.port.toString())
                }
            }
        }
    }

    private fun performLogin(ip: String, port: Int, user: String, pass: String) {
        if (ip.isEmpty() || pass.isEmpty()) {
            Toast.makeText(this, "يرجى إدخال عنوان IP وكلمة المرور", Toast.LENGTH_SHORT).show()
            return
        }

        binding.btnLogin.isEnabled = false
        binding.btnLogin.text = "جاري تسجيل الدخول... ⏳"

        lifecycleScope.launch(Dispatchers.IO) {
            val token = executeLoginApi(ip, port, user, pass)
            withContext(Dispatchers.Main) {
                binding.btnLogin.isEnabled = true
                binding.btnLogin.text = "تسجيل الدخول والفتح ⚡"
                if (token != null) {
                    val pcName = discoveredList.find { it.ip == ip }?.pcName ?: "Windows PC"
                    sessionManager.saveSession(
                        ServerSession(ip, port, pcName, user, pass, token)
                    )
                    launchWebView(ip, port, token)
                } else {
                    Toast.makeText(
                        this@GatewayActivity,
                        "فشل تسجيل الدخول: تأكد من صحة بيانات الخادم وكلمة المرور",
                        Toast.LENGTH_LONG
                    ).show()
                }
            }
        }
    }

    private fun testTokenValidity(ip: String, port: Int, token: String): Boolean {
        return try {
            val url = URL("http://$ip:$port/api/system/summary?token=$token")
            val conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = 2500
                readTimeout = 2500
                setRequestProperty("X-Auth-Token", token)
            }
            conn.responseCode == 200
        } catch (_: Exception) {
            false
        }
    }

    private fun executeLoginApi(ip: String, port: Int, user: String, pass: String): String? {
        return try {
            val url = URL("http://$ip:$port/api/auth/login")
            val conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
                doOutput = true
                connectTimeout = 4000
                readTimeout = 4000
            }
            val body = JSONObject().apply {
                put("username", user)
                put("password", pass)
            }
            OutputStreamWriter(conn.outputStream).use { it.write(body.toString()) }

            if (conn.responseCode == 200) {
                val resp = conn.inputStream.bufferedReader().readText()
                val json = JSONObject(resp)
                if (json.optBoolean("ok")) json.optString("token") else null
            } else {
                null
            }
        } catch (_: Exception) {
            null
        }
    }

    private fun launchWebView(ip: String, port: Int, token: String) {
        discoveryManager.stop()
        val intent = Intent(this, WebWrapperActivity::class.java).apply {
            putExtra("EXTRA_IP", ip)
            putExtra("EXTRA_PORT", port)
            putExtra("EXTRA_TOKEN", token)
        }
        startActivity(intent)
        finish()
    }

    override fun onDestroy() {
        super.onDestroy()
        autoLoginJob?.cancel()
        discoveryManager.stop()
    }
}
