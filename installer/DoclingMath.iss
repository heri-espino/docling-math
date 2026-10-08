; Per-user, no-terminal Windows installer for the frozen desktop application.
#define AppName "Docling Math"
#define AppVersion "0.8.0"

[Setup]
AppId={{C1FF493A-3EA0-412E-91D9-8D6962C7FE0D}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=docling-math
DefaultDirName={localappdata}\Programs\DoclingMath
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
OutputDir=..\out
OutputBaseFilename=DoclingMath-Setup
WizardStyle=modern
UninstallDisplayIcon={app}\DoclingMath.exe

[Files]
Source: "..\dist\DoclingMath\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Docling Math"; Filename: "{app}\DoclingMath.exe"
Name: "{autodesktop}\Docling Math"; Filename: "{app}\DoclingMath.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create desktop shortcut"; GroupDescription: "Shortcuts:"

[Run]
Filename: "{app}\DoclingMath.exe"; Description: "Launch Docling Math"; Flags: nowait postinstall skipifsilent
