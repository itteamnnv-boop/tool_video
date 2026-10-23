; Bộ cài VideoAgent (Inno Setup 6) — build bằng .\build.ps1 (tự truyền /DAppVersion=…).
; Cài theo người dùng (không cần quyền Admin) vào %LOCALAPPDATA%\Programs\VideoAgent.
; Chỉ đóng gói chương trình (dist\VideoAgent). Dữ liệu người dùng — profile trình duyệt, tài khoản, cài đặt, token — nằm ở
; %APPDATA%\VideoAgent và KHÔNG có trong bộ cài: máy mới cần đăng nhập lại các tài khoản trình duyệt.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6E1F4C2A-8B7D-4E5A-9C3B-2F6A7D1E0B94}
AppName=VideoAgent
AppVersion={#AppVersion}
AppVerName=VideoAgent {#AppVersion}
AppPublisher=ITNNV
DefaultDirName={localappdata}\Programs\VideoAgent
DefaultGroupName=VideoAgent
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=dist\installer
OutputBaseFilename=VideoAgent-Setup-{#AppVersion}
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\VideoAgent.exe
UninstallDisplayName=VideoAgent
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
english.DesktopIcon=Tạo biểu tượng VideoAgent ngoài Desktop
english.LaunchApp=Mở VideoAgent ngay
english.Extra=Tuỳ chọn thêm:

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"; GroupDescription: "{cm:Extra}"

[Files]
Source: "dist\VideoAgent\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\VideoAgent"; Filename: "{app}\VideoAgent.exe"
Name: "{group}\Gỡ cài đặt VideoAgent"; Filename: "{uninstallexe}"
Name: "{userdesktop}\VideoAgent"; Filename: "{app}\VideoAgent.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\VideoAgent.exe"; Description: "{cm:LaunchApp}"; Flags: nowait postinstall skipifsilent

[Code]
// Gỡ cài đặt: hỏi có xoá luôn dữ liệu (tài khoản trình duyệt, cài đặt, tư liệu) không — mặc định GIỮ.
// Video đã xuất (thư mục lưu video, mặc định Videos\VideoAgent) không bao giờ bị xoá.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: string;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{userappdata}\VideoAgent');
    if DirExists(DataDir) and (not UninstallSilent) then
      if MsgBox('Xoá luôn dữ liệu VideoAgent trên máy này?' + #13#10 + #13#10 +
                'Gồm: profile trình duyệt đã đăng nhập (Muse, ChatGPT, Grok, Gemini…), tài khoản Facebook đã kết nối, ' +
                'cài đặt, nhân vật / tư liệu, lịch sử.' + #13#10 +
                'Video đã xuất KHÔNG bị xoá.' + #13#10 + #13#10 +
                'Chọn No để giữ lại (cài lại sẽ dùng tiếp).', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
