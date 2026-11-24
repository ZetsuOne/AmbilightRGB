; AmbilightRGB — Inno Setup 6 installer
; Builds dist\AmbilightRGB-Setup.exe (run via build\build_release.bat)

#define MyAppName "AmbilightRGB"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "AmbilightRGB"
#define MyAppExeName "ambilight.exe"

[Setup]
AppId={{A3B1C7D9-4E2F-4A8B-9C1D-6E5F8A0B2C3D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=AmbilightRGB-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#MyAppName}
CloseApplications=force

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Files]
; Compiled ambilight (from PyInstaller)
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
; Portable OpenRGB next to ambilight.exe → {app}\bin\OpenRGB\
Source: "..\bin\OpenRGB\*"; DestDir: "{app}\bin\OpenRGB"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
; Autostart at logon with highest privileges (PowerShell Scheduled Task — reliable quoting)
Filename: "powershell.exe"; \
    Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""$a = New-ScheduledTaskAction -Execute '{app}\{#MyAppExeName}'; $t = New-ScheduledTaskTrigger -AtLogOn; $p = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest; Register-ScheduledTask -TaskName 'AmbilightRGB' -Action $a -Trigger $t -Principal $p -Force"""; \
    Flags: runhidden waituntilterminated
; Start immediately after install
Filename: "{app}\{#MyAppExeName}"; Flags: nowait runhidden

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -Command ""Unregister-ScheduledTask -TaskName 'AmbilightRGB' -Confirm:$false -ErrorAction SilentlyContinue"""; Flags: runhidden waituntilterminated
Filename: "{sys}\taskkill.exe"; Parameters: "/IM ambilight.exe /F /T"; Flags: runhidden waituntilterminated
Filename: "{sys}\taskkill.exe"; Parameters: "/IM openrgb.exe /F /T"; Flags: runhidden waituntilterminated
