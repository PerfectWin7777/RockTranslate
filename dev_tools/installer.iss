; RockTranslate — Standalone Installer Script (Web Engine Edition)
; Path: dev_tools/installer.iss
;
; This configuration script compiles the standalone dist/ folder into a
; professional multi-language Windows Installation Assistant (.exe).
; Highly optimized to pack our lightweight pywebview distribution recursively.

#define MyAppName "RockTranslate"
; The CI passes /DMyAppVersion=<version from __init__.py>; local builds use this default
#ifndef MyAppVersion
  #define MyAppVersion "2.0.7"
#endif
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
DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
AllowNoIcons=yes

; The output directory for the compiled setup installer executable
OutputDir={#SourcePath}\..\dist_installer
OutputBaseFilename=RockTranslate_Setup_v{#MyAppVersion}
; Path updated to target the new assets folder structure
SetupIconFile={#SourcePath}\..\src\rocktranslate\assets\rocktranslate_icon.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
; Refreshes Explorer after registering "Open with RockTranslate" for PDFs
ChangesAssociations=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
; Optional, unchecked: proposes RockTranslate as the PDF reader. Windows 10/11
; still ask the user to confirm the default app (a setup cannot force it).
Name: "pdfdefault"; Description: "{cm:AssocFileExtension,{#MyAppName},.pdf}"; GroupDescription: "{cm:AssocingFileExtension,{#MyAppName},.pdf}"; Flags: unchecked

[Registry]
; Always: "Open with > RockTranslate" on PDF files (no change of the default app)
Root: HKA; Subkey: "Software\Classes\RockTranslate.PDF"; ValueType: string; ValueName: ""; ValueData: "PDF - RockTranslate"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\RockTranslate.PDF\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"
Root: HKA; Subkey: "Software\Classes\RockTranslate.PDF\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "RockTranslate.PDF"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""
; Task "pdfdefault": registers RockTranslate as the .pdf handler of this user
Root: HKA; Subkey: "Software\Classes\.pdf"; ValueType: string; ValueName: ""; ValueData: "RockTranslate.PDF"; Flags: uninsdeletevalue; Tasks: pdfdefault


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