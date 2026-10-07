; ImobHunter-BR Windows installer
#define MyAppName "ImobHunter-BR"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "ImobHunter-BR"
#define MyAppExeName "ImobHunter-BR.exe"

[Setup]
AppId={{8A1C8C1E-6A25-4B54-9E0E-IMOBHUNTERBR}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\ImobHunter-BR
DefaultGroupName=ImobHunter-BR
OutputBaseFilename=ImobHunter-BR-Setup-Windows
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "..\..\dist\ImobHunter-BR\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autodesktop}\ImobHunter-BR"; Filename: "{app}\ImobHunter-BR.exe"
Name: "{group}\ImobHunter-BR"; Filename: "{app}\ImobHunter-BR.exe"

[Run]
Filename: "{app}\ImobHunter-BR.exe"; Description: "Abrir ImobHunter-BR"; Flags: nowait postinstall skipifsilent
