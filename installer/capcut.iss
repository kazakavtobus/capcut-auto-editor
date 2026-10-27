#define AppName "CapCut Auto Editor"
#define AppVersion "7.5.1"
[Setup]
AppId={{F3CD2BD4-6442-4B0D-AD86-A948819B66E6}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=CapCut Auto Editor Community
DefaultDirName={localappdata}\Programs\CapCutAutoEditor
DefaultGroupName={#AppName}
OutputDir=..\dist\release
OutputBaseFilename=CapCutAutoEditor_Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=yes
UninstallDisplayIcon={app}\CapCutAutoEditor.exe
WizardStyle=modern
SetupIconFile=..\assets\app_icon.ico
[Files]
Source: "..\dist\CapCutAutoEditor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\CapCutAutoEditor.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\CapCutAutoEditor.exe"; Tasks: desktopicon
[Tasks]
Name: desktopicon; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Значки:"
[Run]
Filename: "{app}\CapCutAutoEditor.exe"; Description: "Запустить {#AppName}"; Flags: nowait postinstall skipifsilent
