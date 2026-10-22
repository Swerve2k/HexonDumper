#define MyAppName "Hexon"
#define MyAppVersion "2.0.0-dev.2"
#define MyAppPublisher "CELESTARR Productions"
#define MyAppExeName "Hexon.exe"
#define BuildDir AddBackslash(SourcePath) + "..\dist\Hexon"

#if !FileExists(AddBackslash(BuildDir) + MyAppExeName)
  #error Hexon.exe was not found in dist\Hexon. Build the app first by running packaging\build_release.bat, then compile this script again.
#endif

[Setup]
AppId={{AC2BBF41-EA75-4B33-A6ED-913433F8AC4D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
SetupIconFile=..\app\assets\logo.ico
OutputDir=..\dist-installer
OutputBaseFilename=Hexon-Setup-{#MyAppVersion}
InfoBeforeFile=notice.txt
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    if SuppressibleMsgBox('Remove Hexon from the games you set it up for?' + #13#10 + #13#10 +
              'This deletes the dxgi.dll Hexon added to each game folder and restores any original it replaced. ' +
              'Close your games first. Your dumped and replaced textures are not touched.',
              mbConfirmation, MB_YESNO, IDYES) = IDYES then
      Exec(ExpandConstant('{app}\{#MyAppExeName}'), '--remove-all', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
  if CurUninstallStep = usPostUninstall then
  begin
    if SuppressibleMsgBox('Also delete your Hexon profiles and settings?', mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES then
      DelTree(ExpandConstant('{userappdata}\CELESTARR\Hexon'), True, True, True);
  end;
end;
