; PartCAD, 2026
;
; Licensed under Apache License, Version 2.0.
;
; The Windows installer for the PartCAD IDE. Compiled by ../build.sh, which
; passes the version and the output location on the command line; everything
; else is here.
;
;   ISCC.exe /DVersion=0.7.158 /O<output directory> /F<file name> partcad-ide.iss
;
; It installs per user by default -- into %LOCALAPPDATA%\Programs, without a UAC
; prompt -- and offers "for all users" in the wizard for someone who has an
; administrator account and wants it in Program Files. That is the same choice
; the editors this one is built from offer, and the reason the registry entries
; below use HKA: they follow the installation into HKCU or HKLM.

#ifndef Version
  #define Version "0.0.0"
#endif

; Where the built application is. ../build.sh passes it absolutely, with
; /DAppDir, and has to: Inno resolves a relative source against this file's own
; directory without normalizing it, so a relative '[Files]' source survives into
; every path it opens and adds 31 characters to each. The deepest file in the
; application is 245 characters absolute and 276 that way, MAX_PATH is 260, and
; the compiler is not long-path aware -- it aborts with "The system cannot find
; the path specified" and names neither a line nor a file.
#ifndef AppDir
  #define AppDir "..\..\..\dist\ide\partcad-ide"
#endif

; The licence shown in the wizard, passed absolutely for a different reason: it
; is resolved relative to *this file*, and this file moved a level deeper in
; #553. That silently turned '..\..\' from the repository root into 'ide/', and
; Inno aborted with `Could not read "...\installer\..\..\LICENSE.txt"`.
#ifndef LicenseFile
  #define LicenseFile "..\..\..\LICENSE.txt"
#endif

; Both fallbacks are for compiling this by hand from this directory. They are
; correct for the current depth -- and are exactly what breaks the next time
; this file moves, which is why build.sh passes both in.

#define AppName "PartCAD IDE"
#define AppExeName "partcad-ide.exe"

[Setup]
; Fixed for the lifetime of the product: Windows recognizes an upgrade, and an
; uninstall, by this and nothing else. Never regenerate it.
AppId={{0F1D6B4E-3C5A-4C1B-9A7E-1C0A9D2E8B31}
AppName={#AppName}
AppVersion={#Version}
AppVerName={#AppName} {#Version}
AppPublisher=PartCAD
AppPublisherURL=https://partcad.org/
AppSupportURL=https://github.com/partcad/partcad/issues
AppUpdatesURL=https://github.com/partcad/partcad/releases
VersionInfoVersion={#Version}
VersionInfoProductName={#AppName}

DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes
LicenseFile={#LicenseFile}

; Per user unless the person running it asks for otherwise, which is what makes
; the common case a double click with no prompt.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline

; The application is 64-bit, and so is every Windows this supports.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

; lzma2/max would save roughly a tenth of a gigabyte-sized payload and cost the
; build the better part of an hour. Raise it if a release build ever has the
; time to spare.
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern

; Both are set because the installer writes outside {app}: the PATH entries in
; [Code], and the context menu entries in [Registry].
ChangesEnvironment=yes
ChangesAssociations=yes

UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
; The icon is rendered from the project logo by the build, which can only do it
; where its renderers are installed. ../build.sh defines HaveIcon when there is
; one; without it the installer keeps Inno Setup's own icon.
#ifdef HaveIcon
SetupIconFile={#AppDir}\partcad-ide.ico
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "addcontextmenufiles"; Description: "Add ""Open with {#AppName}"" to the file context menu"; GroupDescription: "Other:"; Flags: unchecked
Name: "addcontextmenufolders"; Description: "Add ""Open with {#AppName}"" to the folder context menu"; GroupDescription: "Other:"; Flags: unchecked
Name: "addtopath"; Description: "Add ""partcad-ide"" and ""pc"" to PATH (needs a new terminal)"; GroupDescription: "Other:"

[Files]
Source: "{#AppDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
; So that "partcad-ide" works in the Run dialog and in Start menu search.
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\{#AppExeName}"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExeName}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\{#AppExeName}"; ValueType: string; ValueName: "Path"; ValueData: "{app}"

; The URL scheme the editor is branded with (product.overlay.json), so that a
; partcad-ide:// link opens this application and not a VSCodium beside it.
Root: HKA; Subkey: "Software\Classes\partcad-ide"; ValueType: string; ValueName: ""; ValueData: "URL:{#AppName} Protocol"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\partcad-ide"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\partcad-ide\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExeName},0"
Root: HKA; Subkey: "Software\Classes\partcad-ide\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" --open-url -- ""%1"""

Root: HKA; Subkey: "Software\Classes\*\shell\{#AppName}"; ValueType: string; ValueName: ""; ValueData: "Open w&ith {#AppName}"; Tasks: addcontextmenufiles; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\*\shell\{#AppName}"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExeName}"; Tasks: addcontextmenufiles
Root: HKA; Subkey: "Software\Classes\*\shell\{#AppName}\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%1"""; Tasks: addcontextmenufiles

Root: HKA; Subkey: "Software\Classes\Directory\shell\{#AppName}"; ValueType: string; ValueName: ""; ValueData: "Open w&ith {#AppName}"; Tasks: addcontextmenufolders; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Directory\shell\{#AppName}"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExeName}"; Tasks: addcontextmenufolders
Root: HKA; Subkey: "Software\Classes\Directory\shell\{#AppName}\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%V"""; Tasks: addcontextmenufolders
Root: HKA; Subkey: "Software\Classes\Directory\Background\shell\{#AppName}"; ValueType: string; ValueName: ""; ValueData: "Open w&ith {#AppName}"; Tasks: addcontextmenufolders; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Directory\Background\shell\{#AppName}"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExeName}"; Tasks: addcontextmenufolders
Root: HKA; Subkey: "Software\Classes\Directory\Background\shell\{#AppName}\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%V"""; Tasks: addcontextmenufolders

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
{ The two directories that go on PATH: the editor's command line launcher, and
  the PartCAD command line tools the application carries. }

function PathRootKey: Integer;
begin
  if IsAdminInstallMode then
    Result := HKEY_LOCAL_MACHINE
  else
    Result := HKEY_CURRENT_USER;
end;

function PathSubKey: String;
begin
  if IsAdminInstallMode then
    Result := 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'
  else
    Result := 'Environment';
end;

function PathDirectory(const Index: Integer): String;
begin
  if Index = 0 then
    Result := ExpandConstant('{app}\bin')
  else
    Result := ExpandConstant('{app}\resources\partcad-cli');
end;

procedure AddToPath(const Directory: String);
var
  Paths: String;
begin
  if not RegQueryStringValue(PathRootKey, PathSubKey, 'Path', Paths) then
    Paths := '';
  if Pos(';' + Uppercase(Directory) + ';', ';' + Uppercase(Paths) + ';') > 0 then
    Exit;
  if (Paths <> '') and (Paths[Length(Paths)] <> ';') then
    Paths := Paths + ';';
  RegWriteExpandStringValue(PathRootKey, PathSubKey, 'Path', Paths + Directory);
end;

procedure RemoveFromPath(const Directory: String);
var
  Paths: String;
  Position: Integer;
begin
  if not RegQueryStringValue(PathRootKey, PathSubKey, 'Path', Paths) then
    Exit;
  { Searched with a separator on each side so that a directory whose name ends
    with another entry's name is not mistaken for it. The match position in the
    padded string is the position of the directory itself in Paths. }
  Position := Pos(';' + Uppercase(Directory) + ';', ';' + Uppercase(Paths) + ';');
  if Position = 0 then
    Exit;
  Delete(Paths, Position, Length(Directory) + 1);
  if (Paths <> '') and (Paths[Length(Paths)] = ';') then
    Delete(Paths, Length(Paths), 1);
  RegWriteExpandStringValue(PathRootKey, PathSubKey, 'Path', Paths);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('addtopath') then
  begin
    AddToPath(PathDirectory(0));
    AddToPath(PathDirectory(1));
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  { Unconditionally: the task the user chose at install time is not recorded
    anywhere the uninstaller can read, and removing an entry that is not there
    does nothing. }
  if CurUninstallStep = usUninstall then
  begin
    RemoveFromPath(PathDirectory(0));
    RemoveFromPath(PathDirectory(1));
  end;
end;
