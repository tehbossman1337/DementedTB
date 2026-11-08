; Inno Setup script - builds DementedToolbox-Setup.exe (per-user install, no admin rights needed)
#define AppName "Demented Toolbox"
#define AppVer "1.0.0"

[Setup]
AppId={{6F0C2C1E-91B4-4B7A-8D25-3E5A7C41D9B2}
AppName={#AppName}
AppVersion={#AppVer}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=installer_out
OutputBaseFilename=DementedToolbox-Setup
SetupIconFile=app\app.ico
UninstallDisplayIcon={app}\DementedToolbox.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: checkedonce

[InstallDelete]
; a clean copy of the program files every time (your data lives in %APPDATA%\DementedToolbox and is never touched)
Type: filesandordirs; Name: "{app}\*"

[Files]
Source: "dist\DementedToolbox\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\DementedToolbox.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\DementedToolbox.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\DementedToolbox.exe"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
; silent in-app updates relaunch the app
Filename: "{app}\DementedToolbox.exe"; WorkingDir: "{app}"; Flags: nowait; Check: WizardSilent
