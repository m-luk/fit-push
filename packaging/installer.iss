; Inno Setup script for the Windows installer. Built by `python scripts/release.py build`,
; which passes AppVersion, SourceDir (the PyInstaller one-folder build), IconFile,
; OutputDir and OutputBaseFilename on the ISCC command line.
;
; Installs per user (no admin rights) into %LOCALAPPDATA%\Programs\fit-push. Your data
; lives elsewhere (%LOCALAPPDATA%\fit-push) and is never touched by install/uninstall.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{0284AC24-5D97-458A-B491-2FD09EB8D862}
AppName=fit-push
AppVersion={#AppVersion}
AppVerName=fit-push {#AppVersion}
AppPublisher=fit-push contributors
DefaultDirName={localappdata}\Programs\fit-push
DefaultGroupName=fit-push
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\LICENSE
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\fit-push.exe
UninstallDisplayName=fit-push
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; Drop files of the previous version so upgrades never mix libraries.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\fit-push"; Filename: "{app}\fit-push.exe"
Name: "{autodesktop}\fit-push"; Filename: "{app}\fit-push.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\fit-push.exe"; Description: "{cm:LaunchProgram,fit-push}"; Flags: nowait postinstall skipifsilent
