; Concall Player installer for Windows (Inno Setup 6). Built by packaging/windows/build.py.
; Installs for the current user only (no administrator rights needed) into
; %LOCALAPPDATA%\Programs\Concall Player. Calls, notes and settings live in
; %LOCALAPPDATA%\Concall Player and are kept when the app is uninstalled.

#ifndef Version
  #define Version "0.0.0"
#endif
#ifndef BuildDir
  #define BuildDir "build"
#endif

[Setup]
AppId={{8C1E2F4B-6A3D-4C1B-9E57-2B7F0D4A9C31}
AppName=Concall Player
AppVersion={#Version}
AppPublisher=Concall Player
AppPublisherURL=https://github.com/sahilp23/audio-transcript
DefaultDirName={localappdata}\Programs\Concall Player
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#BuildDir}\..
OutputBaseFilename=Concall-Player-Setup
SetupIconFile={#BuildDir}\icon.ico
UninstallDisplayIcon={app}\icon.ico
UninstallDisplayName=Concall Player
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#BuildDir}\uv.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#BuildDir}\icon.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#BuildDir}\launcher.pyw"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#BuildDir}\setup.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#BuildDir}\app\*"; DestDir: "{app}\app"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Old code from a previous install (updates downloaded inside the app live elsewhere).
Type: filesandordirs; Name: "{app}\app"

[Icons]
Name: "{userprograms}\Concall Player"; Filename: "{localappdata}\Concall Player\venv\Scripts\pythonw.exe"; Parameters: """{app}\launcher.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"
Name: "{userdesktop}\Concall Player"; Filename: "{localappdata}\Concall Player\venv\Scripts\pythonw.exe"; Parameters: """{app}\launcher.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon

[Run]
Filename: "{localappdata}\Concall Player\venv\Scripts\pythonw.exe"; Parameters: """{app}\launcher.pyw"""; WorkingDir: "{app}"; Description: "Open Concall Player"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    WizardForm.StatusLabel.Caption := 'Downloading Python and the app''s components (about a minute)...';
    if not Exec(ExpandConstant('{cmd}'), '/C ""' + ExpandConstant('{app}\setup.cmd') + '""', ExpandConstant('{app}'),
                SW_HIDE, ewWaitUntilTerminated, ResultCode)
       or (ResultCode <> 0) then
      MsgBox('Concall Player couldn''t download its setup files (error ' + IntToStr(ResultCode) + '). ' +
             'Check your internet connection and run this installer again. Details: ' +
             ExpandConstant('{localappdata}\Concall Player\logs\setup.log'), mbError, MB_OK);
  end;
end;
