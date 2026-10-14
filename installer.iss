; ==============================================================================
; Shutdown Panel — Unified Windows Installer Script (Inno Setup 6 / 7)
; Developer: Abdou Ragab Nassar (عبده رجب نصار)
; Company: ARN Technology
; Copyright (c) 2026 ARN Technology. All Rights Reserved.
; ==============================================================================

#define MyAppName "Shutdown Panel"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "ARN Technology (تطوير وبرمجة عبده رجب نصار)"
#define MyAppURL "https://wa.me/201556710314"
#define MyAppExeName "ShutdownPanel.exe"
#define MyClientExeName "ShutdownPanelClient.exe"

[Setup]
AppId={{D37F8E12-4B29-4A91-893C-E8973648BFD1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\ARN Technology\Shutdown Panel
DefaultGroupName=ARN Technology - {#MyAppName}
AllowNoIcons=yes
OutputDir=dist
OutputBaseFilename=ShutdownPanel_Setup_v{#MyAppVersion}
SetupIconFile=assets\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=force
CloseApplicationsFilter=*.exe
RestartApplications=no


[Languages]
Name: "ar"; MessagesFile: "compiler:Languages\Arabic.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
ar.CompServerDesc=لوحة التحكم الرئيسية والخادم (Host Server & Panel)
ar.CompServerExtra=لوحة إدارة النظام، إيقاف التشغيل، الجدولة، وخادم التحكم عن بعد.
ar.CompClientDesc=عميل التحكم عن بعد للكمبيوتر (Desktop Client)
ar.CompClientExtra=تطبيق للتحكم بأجهزة الكمبيوتر الأخرى عبر الشبكة المحلية.
ar.TaskDesktopServer=إنشاء اختصار للوحة الرئيسية على سطح المكتب
ar.TaskDesktopClient=إنشاء اختصار لعميل التحكم على سطح المكتب
ar.TaskAutoStartServer=تشغيل لوحة التحكم الرئيسية تلقائياً عند بدء ويندوز
ar.RunServer=تشغيل لوحة التحكم الرئيسية الآن
ar.RunClient=تشغيل عميل التحكم عن بعد الآن
ar.CertRootMsg=جاري توثيق شهادة أمان ARN Technology...
ar.CertPubMsg=جاري توثيق ناشر التطبيق في قائمة الناشرين الموثوقين...

en.CompServerDesc=Host Server & Main Panel
en.CompServerExtra=System management, shutdown scheduler, and LAN remote control server.
en.CompClientDesc=Desktop Remote Client
en.CompClientExtra=Control other computers running Shutdown Panel on the local network.
en.TaskDesktopServer=Create a desktop shortcut for the Main Panel
en.TaskDesktopClient=Create a desktop shortcut for the Remote Client
en.TaskAutoStartServer=Start Main Panel automatically with Windows
en.RunServer=Launch Shutdown Panel now
en.RunClient=Launch Shutdown Panel Client now
en.CertRootMsg=Installing ARN Technology Root Security Certificate...
en.CertPubMsg=Registering ARN Technology as a Trusted Publisher...

[Types]
Name: "full"; Description: "Full Installation (البرنامج الكامل — الخادم والعميل)"
Name: "serveronly"; Description: "Host Server Only (اللوحة الرئيسية فقط لإدارة هذا الجهاز)"
Name: "clientonly"; Description: "Remote Client Only (عميل التحكم عن بعد فقط لإدارة أجهزة أخرى)"
Name: "custom"; Description: "Custom Installation (تثبيت مخصص)"; Flags: iscustom

[Components]
Name: "server"; Description: "{cm:CompServerDesc}"; Types: full serveronly
Name: "client"; Description: "{cm:CompClientDesc}"; Types: full clientonly

[Tasks]
Name: "desktopicon_server"; Description: "{cm:TaskDesktopServer}"; GroupDescription: "{cm:AdditionalIcons}"; Components: server
Name: "desktopicon_client"; Description: "{cm:TaskDesktopClient}"; GroupDescription: "{cm:AdditionalIcons}"; Components: client
Name: "autostart_server"; Description: "{cm:TaskAutoStartServer}"; GroupDescription: "{cm:AutoStartProgramGroupDescription}"; Components: server; Flags: unchecked

[Files]
; Server Executable & Assets
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion; Components: server
Source: "assets\icon.ico"; DestDir: "{app}"; Flags: ignoreversion

; Client Executable
Source: "dist\{#MyClientExeName}"; DestDir: "{app}"; Flags: ignoreversion; Components: client

; Security Certificate
Source: "cert\ARN_Technology_Root.cer"; DestDir: "{app}\cert"; Flags: ignoreversion

[Icons]
; Start Menu
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"; Components: server
Name: "{group}\Shutdown Panel Client"; Filename: "{app}\{#MyClientExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"; Components: client
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"; WorkingDir: "{app}"

; Desktop Shortcuts
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon_server
Name: "{autodesktop}\Shutdown Panel Client"; Filename: "{app}\{#MyClientExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon_client

; Auto-start via Startup Folder
Name: "{commonstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: autostart_server

[Run]
; Digital Certificate Trust Registration (Rule 7: LocalMachine & CurrentUser)
Filename: "certutil.exe"; Parameters: "-addstore -f ""Root"" ""{app}\cert\ARN_Technology_Root.cer"""; StatusMsg: "{cm:CertRootMsg}"; Flags: runhidden waituntilterminated
Filename: "certutil.exe"; Parameters: "-addstore -f ""TrustedPublisher"" ""{app}\cert\ARN_Technology_Root.cer"""; StatusMsg: "{cm:CertPubMsg}"; Flags: runhidden waituntilterminated
Filename: "certutil.exe"; Parameters: "-user -addstore -f ""Root"" ""{app}\cert\ARN_Technology_Root.cer"""; StatusMsg: "{cm:CertRootMsg}"; Flags: runhidden waituntilterminated
Filename: "certutil.exe"; Parameters: "-user -addstore -f ""TrustedPublisher"" ""{app}\cert\ARN_Technology_Root.cer"""; StatusMsg: "{cm:CertPubMsg}"; Flags: runhidden waituntilterminated

; Post-installation launch
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:RunServer}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent; Components: server
Filename: "{app}\{#MyClientExeName}"; Description: "{cm:RunClient}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent unchecked; Components: client

[Code]
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  // Force terminate any running instances of ShutdownPanel before installing/overwriting files
  Exec('taskkill.exe', '/F /IM ShutdownPanel.exe /IM ShutdownPanelClient.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := True;
end;

function InitializeUninstall(): Boolean;
var
  ResultCode: Integer;
begin
  Exec('taskkill.exe', '/F /IM ShutdownPanel.exe /IM ShutdownPanelClient.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := True;
end;

