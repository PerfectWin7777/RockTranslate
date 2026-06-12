; RockTranslate — Inno Setup Installer Script
; Path: dev_tools/installer.iss
;
; This configuration script compiles the standalone dist/ folder into a
; professional multi-language Windows Installation Assistant (.exe).
; Highly optimized to exclude development binaries, raw translation sources, 
; and unused heavy Qt6 DLLs to minimize final installer size.

#define MyAppName "RockTranslate"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "RockTranslate Contributors"
#define MyAppURL "https://github.com/PerfectWin7777/RockTranslate"
#define MyAppExeName "RockTranslate.exe"

[Setup]
; NOTE: The value of AppId uniquely identifies this application.
; Do not use the same AppId value in installers for other applications.
AppId={{D37D0B75-8D63-41EF-9C33-4F868E2D776C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes

; The output directory for the compiled setup installer executable
OutputDir={#SourcePath}\..\dist_installer
OutputBaseFilename=RockTranslate_Setup_v{#MyAppVersion}
SetupIconFile={#SourcePath}\..\src\assets\rocktranslate_icon.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Copy all compiled binaries and resources from PyInstaller output recursively.
; We use relative paths for cross-system compiling compatibility.
; We explicitly exclude development resources (*.ts, lrelease.exe) and heavy 
; unused Qt6 C++ binaries to drastically reduce the installer and installed sizes.
Source: "..\dist\RockTranslate\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.ts,*lrelease.exe,*Qt63D*,*Qt6Bluetooth*,*Qt6DBus*,*Qt6Designer*,*Qt6Help*,*Qt6Multimedia*,*Qt6Nfc*,*Qt6Positioning*,*Qt6RemoteObjects*,*Qt6Sensors*,*Qt6SerialPort*,*Qt6SpatialAudio*,*Qt6StateMachine*"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent