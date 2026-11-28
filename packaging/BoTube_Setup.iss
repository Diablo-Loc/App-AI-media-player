; =====================================================================
; BoTube Official Windows Installer (Inno Setup 6)
; - Preserves exact legacy AppId for seamless 5.0.0 -> 6.0.0+ upgrades
; - Supports silent in-place auto-updates (/SILENT /CLOSEAPPLICATIONS)
; - Automatically relaunches BoTube as original non-elevated user
; - Preserves 100% of user data (storage/, app_resources/, videos)
; =====================================================================

#ifndef AppName
  #define AppName "BoTube"
#endif
#ifndef AppVersion
  #define AppVersion "6.1.0"
#endif
#ifndef AppPublisher
  #define AppPublisher "BoTube Studio"
#endif
#ifndef AppExeName
  #define AppExeName "BoTube.exe"
#endif
#ifndef AppIconName
  #define AppIconName "app_icon.ico"
#endif
#ifndef AppURL
  #define AppURL "https://github.com/Diablo-Loc/App-AI-media-player"
#endif
; Override via CLI: ISCC.exe /DSourceDir="D:\...\dist\release-...\BoTube" packaging\BoTube_Setup.iss
#ifndef SourceDir
  #define SourceDir "..\dist\BoTube"
#endif

[Setup]
; CRITICAL: Keep exact AppId matching existing installations so upgrades overwrite in-place
AppId={{B070B3-E119-4A92-B76F-B937DAE9E312}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases

DefaultDirName={autopf}\{#AppName}
UsePreviousAppDir=yes
DisableProgramGroupPage=yes
DisableDirPage=no

OutputDir=..\Installer
OutputBaseFilename=BoTube_Setup

SetupIconFile=..\icon\{#AppIconName}
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}

Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin

; Auto-close running BoTube cleanly during in-place upgrade; [Run] handles non-elevated relaunch
CloseApplications=yes
CloseApplicationsFilter={#AppExeName}
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Dirs]
; Allow non-elevated BoTube runtime to save settings, cache, subtitles, and offline AI models under Program Files
Name: "{app}\storage"; Permissions: users-modify
Name: "{app}\app_resources"; Permissions: users-modify
Name: "{app}\app_resources\libs"; Permissions: users-modify

[InstallDelete]
; Clean obsolete PyInstaller runtime files & legacy v1.0.2 updater files before copying the new build.
; NEVER touch {app}\storage, {app}\app_resources, {app}\video, or user configuration files!
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\bin\ffplay.exe"
Type: files; Name: "{app}\update_helper.bat"
Type: files; Name: "{app}\update_helper.sh"
Type: files; Name: "{app}\version.json"
Type: dirifempty; Name: "{app}\input"
Type: dirifempty; Name: "{app}\output"

[Files]
; 1. Package complete PyInstaller portable directory (BoTube.exe, _internal, bin, icon, native, yt-dlp.exe)
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; 2. Bundle standalone app icon for reliable Start Menu & Desktop shortcuts
Source: "..\icon\{#AppIconName}"; DestDir: "{app}\resources"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\resources\{#AppIconName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon; IconFilename: "{app}\resources\{#AppIconName}"

[Run]
; Interactive installation: offer checkbox to launch BoTube as the normal (non-elevated) user
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent runasoriginaluser
; Silent in-app auto-update (/SILENT): automatically relaunch BoTube as the normal (non-elevated) user
Filename: "{app}\{#AppExeName}"; Flags: nowait skipifnotsilent runasoriginaluser
