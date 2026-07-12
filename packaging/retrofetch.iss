#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif

[Setup]
AppId={{D10F762E-A2DB-4D67-B970-9A3C3071D8D5}
AppName=Retrofetch
AppVersion={#MyAppVersion}
AppPublisher=veedy-dev
AppPublisherURL=https://github.com/veedy-dev/retrofetch
AppSupportURL=https://github.com/veedy-dev/retrofetch/issues
AppUpdatesURL=https://github.com/veedy-dev/retrofetch/releases
DefaultDirName={localappdata}\Programs\Retrofetch
DefaultGroupName=Retrofetch
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=RetrofetchSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\Retrofetch.exe
SetupIconFile=retrofetch.ico
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: checkedonce

[Files]
Source: "..\dist\Retrofetch.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Retrofetch"; Filename: "{app}\Retrofetch.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Retrofetch"; Filename: "{app}\Retrofetch.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\Retrofetch.exe"; Description: "Launch Retrofetch"; Flags: nowait postinstall skipifsilent
