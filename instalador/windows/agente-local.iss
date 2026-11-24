; Instalador do Agente Local para Windows 10/11 (Inno Setup 6, grátis).
; Gerado pelo GitHub Actions (.github/workflows/instaladores.yml); para gerar à mão:
;   iscc /DVersao=1.1.0 instalador\windows\agente-local.iss
;
; Copia o agente para Documentos\Agente Local (dá para escolher outra pasta) e roda o
; install.ps1, que instala pelo winget o que faltar (Python, Git, Ollama), cria o
; ambiente, baixa os modelos e cria os atalhos com a logo. Não precisa de administrador.
; Seus dados (config.yaml, dados\, logs\) nunca são apagados, nem ao desinstalar.

#ifndef Versao
  #define Versao "0.0.0"
#endif

[Setup]
AppId={{F8A12D75-D538-4678-B068-978CC55734B6}
AppName=Agente Local
AppVersion={#Versao}
AppPublisher=Agente Local
AppPublisherURL=https://github.com/felipebherve/agente-local
DefaultDirName={userdocs}\Agente Local
DisableProgramGroupPage=yes
; a pessoa sempre escolhe a pasta (padrão: Documentos\Agente Local), até ao atualizar
DisableDirPage=no
UsePreviousAppDir=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=AgenteLocal-Setup-Windows
SetupIconFile=..\..\src\agente\icones\app.ico
UninstallDisplayIcon={app}\src\agente\icones\app.ico
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
LicenseFile=..\..\LICENSE

[Languages]
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "celular"; Description: "Deixar o painel sempre ligado para usar pelo celular (inicia com o Windows)"; Flags: unchecked
Name: "voz"; Description: "Instalar a voz (Ctrl+Alt+F para falar com o agente)"; Flags: unchecked

[Files]
Source: "..\..\src\*"; DestDir: "{app}\src"; Flags: recursesubdirs ignoreversion; Excludes: "__pycache__,*.pyc,*.egg-info"
Source: "..\..\bin\*"; DestDir: "{app}\bin"; Flags: recursesubdirs ignoreversion
Source: "..\..\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\install.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\config.example.yaml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\README.pt-BR.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\CHANGELOG.md"; DestDir: "{app}"; Flags: ignoreversion

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install.ps1"" -Sim {code:Opcoes}"; WorkingDir: "{app}"; StatusMsg: "Instalando o agente e baixando os modelos (pode levar alguns minutos)..."; Flags: waituntilterminated
Filename: "{app}\.venv\Scripts\agente-app.exe"; Description: "Abrir o Agente Local"; Flags: postinstall nowait skipifsilent skipifdoesntexist

[UninstallRun]
Filename: "taskkill.exe"; Parameters: "/F /IM agente-painel.exe"; Flags: runhidden; RunOnceId: "ParaPainel"
Filename: "taskkill.exe"; Parameters: "/F /IM agente-app.exe"; Flags: runhidden; RunOnceId: "ParaApp"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: files; Name: "{userdesktop}\Agente Local.lnk"
Type: files; Name: "{userprograms}\Agente Local.lnk"
Type: files; Name: "{userprograms}\Agente local - falar.lnk"
Type: files; Name: "{userstartup}\Agente Local - celular.lnk"

[Code]
function Opcoes(Param: String): String;
begin
  Result := '';
  if WizardIsTaskSelected('celular') then Result := Result + ' -Celular';
  if WizardIsTaskSelected('voz') then Result := Result + ' -Voz';
end;
