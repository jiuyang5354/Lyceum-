; Lyceum 学园 · Windows 安装包（Inno Setup 6.5+）
; 先用 PyInstaller 生成 dist\Lyceum\，再：iscc /DMyAppVersion=0.2.1 desktop\installer.iss
; 产物：dist\Lyceum-Setup-<version>.exe

#define MyAppName "Lyceum 学园"
#define MyAppExe "Lyceum.exe"
#ifndef MyAppVersion
  #define MyAppVersion "0.3.6"
#endif

[Setup]
AppId={{086D9BA1-1C1B-4848-B67B-5C9A1C041DEB}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=jiuyang5354
AppPublisherURL=https://github.com/jiuyang5354/Lyceum-
AppSupportURL=https://github.com/jiuyang5354/Lyceum-/issues
VersionInfoVersion={#MyAppVersion}
DefaultDirName={autopf}\Lyceum
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; 默认装到当前用户（不需要管理员），安装时可改成「所有用户」
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=Lyceum-Setup-{#MyAppVersion}
SetupIconFile=assets\lyceum.ico
UninstallDisplayIcon={app}\{#MyAppExe}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=yes

[Languages]
#if FileExists(AddBackslash(CompilerPath) + "Languages\ChineseSimplified.isl")
Name: "chs"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
#elif FileExists(AddBackslash(SourcePath) + "ChineseSimplified.isl")
Name: "chs"; MessagesFile: "ChineseSimplified.isl"
#else
  #pragma warning "没有 ChineseSimplified.isl，安装界面用英文"
Name: "en"; MessagesFile: "compiler:Default.isl"
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\Lyceum\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
#if FileExists(AddBackslash(SourcePath) + "MicrosoftEdgeWebview2Setup.exe")
  #define HasWV2Bootstrapper
Source: "MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: NeedsWebView2
#endif

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
#ifdef HasWV2Bootstrapper
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "正在安装 Microsoft Edge WebView2 运行时（需要联网）…"; Check: NeedsWebView2; Flags: waituntilterminated
#endif
Filename: "{app}\{#MyAppExe}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Code]
const
  WV2Client = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WV2Url = 'https://developer.microsoft.com/microsoft-edge/webview2/';

function WV2Installed(): Boolean;
var
  v: String;
begin
  Result :=
    (RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\' + WV2Client, 'pv', v) and (v <> '') and (v <> '0.0.0.0')) or
    (RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\' + WV2Client, 'pv', v) and (v <> '') and (v <> '0.0.0.0')) or
    (RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\' + WV2Client, 'pv', v) and (v <> '') and (v <> '0.0.0.0'));
end;

function NeedsWebView2(): Boolean;
begin
  Result := not WV2Installed();
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  code: Integer;
begin
  { 装完后还是没有 WebView2（离线、或公司电脑禁止安装）：给出下载地址 }
  if (CurStep = ssPostInstall) and (not WV2Installed()) and (not WizardSilent()) then
  begin
    if MsgBox('这台电脑缺少 Microsoft Edge WebView2 运行时，Lyceum 学园的窗口需要它。' + #13#10 + #13#10 +
              '点「是」打开微软的下载页面（选 Evergreen Bootstrapper），装好后再打开 Lyceum 学园。',
              mbConfirmation, MB_YESNO) = IDYES then
      ShellExec('open', WV2Url, '', '', SW_SHOWNORMAL, ewNoWait, code);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  dir: String;
begin
  { 学习记录、错题本、模型设置在 %APPDATA%\Lyceum，默认保留；问一下要不要一起删 }
  if CurUninstallStep = usPostUninstall then
  begin
    dir := ExpandConstant('{userappdata}\Lyceum');
    if DirExists(dir) and (not UninstallSilent()) then
      if MsgBox('要不要同时删除学习数据？' + #13#10 + dir + #13#10 + #13#10 +
                '里面有错题本、学习记录和模型设置（含 API Key）。选「否」会保留，重新安装后还能接着用。',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(dir, True, True, True);
  end;
end;
