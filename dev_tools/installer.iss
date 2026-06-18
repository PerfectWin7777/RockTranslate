; RockTranslate — Standalone Installer Script (Web Engine Edition)
; Path: dev_tools/installer.iss
;
; This configuration script compiles the standalone dist/ folder into a
; professional multi-language Windows Installation Assistant (.exe).
; Highly optimized to pack our lightweight pywebview distribution recursively.

#define MyAppName "RockTranslate"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "RockTranslate Contributors"
#define MyAppURL "https://github.com/PerfectWin7777/RockTranslate"
#define MyAppExeName "RockTranslate.exe"

[Setup]
; NOTE: The AppId uniquely identifies this application.
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
; Path updated to target the new assets folder structure
SetupIconFile={#SourcePath}\..\src\rocktranslate\assets\rocktranslate_icon.ico
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
; Excludes temporary runtime logs and compiler database residues.
Source: "..\dist_desktop\RockTranslate\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.log,app.log,*.tmp,*.bak"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent