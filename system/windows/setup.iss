; ─────────────────────────────────────────────────────────────────────────────
; Inkify Agent — Windows Installer (Inno Setup 6)
;
; Embedding a token in the filename:
;   Rename the output exe to  InkifySetup--tkn_<token>.exe  before distributing.
;   The installer will strip the token from the filename and use it for auto-pairing.
;
; Manual install (no embedded token):
;   The token page is shown and the user must paste their token.
; ─────────────────────────────────────────────────────────────────────────────

[Setup]
; --- Basic App Info ---
AppName=Inkify Agent
AppVersion=1.0.0
AppPublisher=Inkify Technologies
AppPublisherURL=https://inkify.in
AppSupportURL=https://support.inkify.in
AppUpdatesURL=https://inkify.in/downloads

DefaultDirName={autopf}\Inkify
ArchitecturesInstallIn64BitMode=x64compatible

; --- Installer Settings ---
DefaultGroupName=Inkify
PrivilegesRequired=admin

OutputDir=Output
OutputBaseFilename=InkifySetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=120

; --- Uninstaller Settings ---
UninstallDisplayIcon={app}\inkify-agent.exe
UninstallDisplayName=Inkify Printer Agent

; Require Windows 10+
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; --- Bundle the 3 files into the installer ---
; Windows binary executable file 
Source: "..\dist\inkify-agent.exe"; DestDir: "{app}"; Flags: ignoreversion
; WinSW service wrapper renamed to inkify-agent-service.exe 
Source: "inkify-agent-service.exe"; DestDir: "{app}"; Flags: ignoreversion
; WinSW XML configuration
Source: "inkify-agent-service.xml"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; No desktop shortcut — this is a background service

[Code]
var
  TokenPage: TInputQueryWizardPage;
  ExtractedToken : String;

{ Extract token from Installer file }
function ExtractTokenFromFilename(): String;
var
  InstallerName, Token: String;
  TokenStartPos: Integer;
begin
  InstallerName := ExtractFileName(ExpandConstant('{srcexe}'));
  { Look for '--' separator }
  TokenStartPos := Pos('--', InstallerName);
  if TokenStartPos > 0 then
  begin
    Token := Copy(InstallerName, TokenStartPos + 2, Length(InstallerName));
    { Strip the .exe extension }
    Token := Copy(Token, 1, Pos(ExtractFileExt(InstallerName), Token) - 1);
    { Basic validation: must start with tkn_ }
    if Copy(Token, 1, 4) = 'tkn_' then
      Result := Token
    else
      Result := '';
  end
  else
    Result := '';
end;

procedure InitializeWizard;
var
  InstallerName: String;
  TokenStart: Integer;
begin
  TokenPage := CreateInputQueryPage(
    wpWelcome,
    'Connect to Inkify Cloud',
    'Agent Authentication',
    'Please enter your 24-hour Registration Token. '
  );
  TokenPage.Add('Registration Token:', False);

  { Pre-fill from the Extracted Token from file }
  ExtractedToken := ExtractTokenFromFilename();
  if ExtractedToken <> '' then
  begin
    TokenPage.Values[0] := ExtractedToken;
    TokenPage.Edits[0].ReadOnly := True;  { Lock the field if auto-filled }
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = TokenPage.ID then
  begin
    if Trim(TokenPage.Values[0]) = '' then
    begin
      MsgBox('Please enter a Registration Token to continue.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

function GetUserToken(Param: String): String;
begin
  Result := Trim(TokenPage.Values[0]);
end;

[Run]
; 1. Pair the agent using the token (runs hidden, waits for completion)
Filename: "{app}\inkify-agent.exe"; Parameters: "--token ""{code:GetUserToken}"" --pair-only"; Flags: runhidden waituntilterminated; StatusMsg: "Pairing agent with Inkify Cloud...";

; 2. Install the Windows service via WinSW
Filename: "{app}\inkify-agent-service.exe"; Parameters: "install"; Flags: runhidden waituntilterminated; StatusMsg: "Installing background service...";

; 3. Start the Service immediately
Filename: "{app}\inkify-agent-service.exe"; Parameters: "start"; Flags: runhidden nowait; StatusMsg: "Starting Inkify Agent service...";

[UninstallRun]
; 1. Stop the running service
Filename: "{app}\inkify-agent-service.exe"; Parameters: "stop"; Flags: runhidden waituntilterminated
; 2. Remove the service from Windows
Filename: "{app}\inkify-agent-service.exe"; Parameters: "uninstall"; Flags: runhidden waituntilterminated