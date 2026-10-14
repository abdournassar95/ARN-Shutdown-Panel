@echo off
chcp 65001 >nul
title تحديث النسخة المثبتة - ARN Technology
echo ========================================================
echo        ARN Technology - تحديث البرنامج المثبت
echo ========================================================
echo.
echo جاري طلب صلاحيات المسؤول لنسخ التحديثات إلى مجلد التثبيت...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"\"%~dp0update_installed.ps1\"\"'"

echo تم إرسال أمر التحديث!
timeout /t 3 >nul
