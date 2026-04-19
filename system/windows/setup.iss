[Setup]
; --- Basic App Info ---
AppName=Inkify Agent
AppVersion=1.0.0
DefaultDirName={autopf}\Inkify
ArchitecturesInstallIn64BitMode=x64

; --- Installer Settings ---
PrivilegesRequired=admin
OutputBaseFilename=InkifySetup
Compression=lzma
SolidCompression=yes
WizardStyle=modern

; --- Uninstaller Settings ---
UninstallDisplayIcon={app}\inkify-agent.exe

[Files]
; --- Bundle the 3 files into the installer ---
; "Source" is the file on your computer. "DestDir" is where it goes on the user's computer ({app} = Program Files\Inkify)
Source: "inkify-agent.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "inkify-agent-service.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "inkify-agent-service.xml"; DestDir: "{app}"; Flags: ignoreversion

[Code]
var
  TokenPage: TInputQueryWizardPage;
  ExtractedToken: String;

procedure InitializeWizard;
var
  InstallerName: String;
  TokenStart: Integer;
begin
  TokenPage := CreateInputQueryPage(wpWelcome,
    'Agent Authentication', 'Connect to Inkify Cloud',
    'Please enter your 24-hour Registration Token. If you just downloaded this file, it should be pre-filled.');
  TokenPage.Add('Registration Token:', False);

  InstallerName := ExtractFileName(ExpandConstant('{srcexe}'));
  TokenStart := Pos('--', InstallerName);
  
  if TokenStart > 0 then
  begin
    ExtractedToken := Copy(InstallerName, TokenStart + 2, Length(InstallerName));
    ExtractedToken := Copy(ExtractedToken, 1, Pos('.exe', ExtractedToken) - 1);
    TokenPage.Values[0] := ExtractedToken;
  end;
end;

function GetUserToken(Param: String): String;
begin
  Result := TokenPage.Values[0];
end;

[Run]
; --- What to do AFTER the files are copied ---
; 1. First, run the agent briefly in "pair-only" mode using the token the user typed in the box
Filename: "{app}\inkify-agent.exe"; Parameters: "--token ""{code:GetUserToken}"" --pair-only"; Flags: runhidden waituntilterminated
; 2. Install the Windows Service using the wrapper (runhidden hides the black terminal window)
Filename: "{app}\inkify-agent-service.exe"; Parameters: "install"; Flags: runhidden waituntilterminated
; 3. Start the Service immediately
Filename: "{app}\inkify-agent-service.exe"; Parameters: "start"; Flags: runhidden waituntilterminated

[UninstallRun]
; --- What to do BEFORE the files are deleted during Uninstallation ---
; 1. Stop the running service
Filename: "{app}\inkify-agent-service.exe"; Parameters: "stop"; Flags: runhidden waituntilterminated
; 2. Remove the service from Windows
Filename: "{app}\inkify-agent-service.exe"; Parameters: "uninstall"; Flags: runhidden waituntilterminated