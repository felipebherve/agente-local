# Tutorial do Agente Local

Guia de uso do app no computador (Windows e Linux) e no celular.

## 1. Instalar

### Windows

1. Baixe `AgenteLocal-Setup-Windows.exe` na página
   [Releases](https://github.com/felipebherve/agente-local/releases).
2. Abra o arquivo. Se o Windows mostrar "O Windows protegeu o computador", clique em
   **Mais informações** > **Executar assim mesmo** (o instalador é grátis e não é
   assinado).
3. Escolha a pasta (o padrão é `Documentos\Agente Local`) e marque o que quiser:
   - **Criar atalho na área de trabalho**;
   - **Deixar o painel sempre ligado para usar pelo celular**;
   - **Instalar a voz**.
4. Espere o fim: ele instala o que faltar (Python, Git, Ollama), baixa os modelos de IA
   e registra o agente no Claude. Pode levar alguns minutos.
5. Para fixar na barra de tarefas: menu Iniciar > **Agente Local** > botão direito >
   **Fixar na barra de tarefas** (o Windows não deixa um instalador fazer isso sozinho).

### Linux

1. Baixe `AgenteLocal-Instalador-Linux.run` na página
   [Releases](https://github.com/felipebherve/agente-local/releases).
2. No terminal, na pasta do download:

   ```bash
   chmod +x AgenteLocal-Instalador-Linux.run
   ./AgenteLocal-Instalador-Linux.run
   ```

3. Responda às perguntas: pasta (padrão `Documentos/Agente Local`), atalho na área de
   trabalho, fixar na barra de tarefas e painel sempre ligado para o celular.

### Atualizar

Rode o instalador novo por cima, na mesma pasta. Ele troca só os arquivos do programa:
`config.yaml`, `dados/` e `logs/` ficam como estão.

## 2. Usar no computador

Abra o app **Agente Local** (atalho, menu ou barra de tarefas).

- Ele abre com o agente **desligado**: nada roda e a placa de vídeo fica livre.
- **Acordar Agente** (botão verde no topo): liga os agentes.
- **Desligar Agente**: pausa os agentes, para o Braço, tira os modelos da placa de vídeo
  e faz o Claude trabalhar sozinho, sem chamar o agente.
- Fechar a janela **não** desliga o agente. Para desligar, use o botão.

Na janela:

- **Conversa**: escreva um pedido; o Maestro escolhe quem responde e mostra o caminho
  (no PC, IA grátis na nuvem ou "precisa do Claude").
- **Agentes** (coluna da esquerda): liga e desliga cada um (Maestro, Porteiro, Memória,
  Revisor, Braço).
- **Histórico**, **Economia** (tokens poupados), **Projetos** e **Configurações**.

Pelo terminal (na pasta do agente):

| O que | Linux | Windows |
| --- | --- | --- |
| Acordar | `.venv/bin/agente acordar-agente` | `.venv\Scripts\agente.exe acordar-agente` |
| Desligar | `.venv/bin/agente desligar-agente` | `.venv\Scripts\agente.exe desligar-agente` |
| Conferir tudo | `.venv/bin/agente doctor` | `.venv\Scripts\agente.exe doctor` |
| Fechar o painel | `pkill -f agente-painel` | `taskkill /IM agente-painel.exe /F` |

## 3. Usar no celular (Android ou iPhone)

O celular conversa com o PC pela rede privada do **Tailscale** (grátis). Só os seus
aparelhos entram, com HTTPS, e ainda é preciso um código de pareamento. O PC precisa
ficar ligado.

Uma vez só, no PC:

1. Instale o Tailscale: <https://tailscale.com/download> e entre com a sua conta.
2. No celular, instale o app do Tailscale e entre com a **mesma** conta.
3. Deixe o painel sempre ligado (se não marcou na instalação):
   - Linux: `./install.sh --sim --celular` na pasta do agente;
   - Windows: rode o instalador de novo e marque a opção do celular.
4. No terminal do PC (Linux), conecte o Tailscale à sua conta e libere o `serve` sem
   sudo. Se aparecer "Logged out", é este passo que falta:

   ```bash
   sudo tailscale up                    # abre um link: entre com a sua conta
   sudo tailscale set --operator=$USER
   tailscale serve --bg 8899
   ```

   No Windows, entre pelo app do Tailscale (ícone perto do relógio) e rode só o
   `tailscale serve --bg 8899` no PowerShell. Na primeira vez o `serve` pode mostrar um
   link para ativar o HTTPS: abra, clique em **Enable** e rode o comando de novo. No fim
   ele mostra o endereço do PC, algo como `https://meu-pc.tail1234.ts.net`.
5. Ligue o acesso com esse endereço e veja o código:

   ```bash
   .venv/bin/agente celular --ligar meu-pc.tail1234.ts.net
   .venv/bin/agente celular
   ```

   (Windows: `.venv\Scripts\agente.exe celular ...`.) Feche e abra o app de novo.

No celular:

1. Abra o endereço `https://meu-pc.tail1234.ts.net` no navegador.
2. Digite o código de pareamento (ex.: `A3TR-V4DY`) e toque em **Entrar**.
3. Instale como app: Android (Chrome) > menu > **Instalar app**; iPhone (Safari) >
   compartilhar > **Adicionar à Tela de Início**. O ícone com a logo aparece na tela.

Se o celular abrir a tela **Ligue o Tailscale**, é porque o Tailscale está desligado
no celular (ou o PC está desligado): ligue e toque em **Tentar de novo**. No PC, o app
mostra uma faixa azul com o botão **Ligar Tailscale** quando o acesso do celular está
desligado.

Pelo celular dá para conversar, acordar e desligar o agente, ligar e desligar cada
agente e ver histórico e economia. Por segurança **não** dá para mudar as pastas
liberadas, os logins nem ligar o microfone do PC.

Perdeu o celular? Rode `agente celular --novo-codigo`: todos os celulares saem e
precisam do código novo. Para desligar o acesso: `agente celular --desligar`.

## 4. Mandar fotos e prints para o agente ler

Na conversa, toque no **clipe** e escolha uma ou várias imagens (até 20; fotos do
iPhone em HEIC também). Se escrever algo no campo antes, vira o foco da leitura
(ex.: "nome, CPF e endereço"). O modelo de visão do PC lê e responde com o texto. As
imagens são apagadas do PC logo depois da leitura.

## 5. Falar pelo microfone

- No PC: o botão do microfone usa o microfone do computador (ou **Ctrl+Alt+F**).
- No celular: o botão grava pelo microfone do celular (o navegador pede permissão na
  primeira vez), e o PC transcreve e manda o pedido. Precisa da voz instalada no PC
  (`./install.sh --voz`; no Windows, a opção de voz do instalador).

## 6. Problemas comuns

- **"Sem conexão com o PC" no celular**: confira se o PC está ligado e se o Tailscale
  está ativo nos dois aparelhos.
- **O celular mostra "403 Forbidden"**: o endereço em `agente celular --ligar` tem de ser
  igual ao que o `tailscale serve` mostrou.
- **Mudei a pasta do agente de lugar**: rode o instalador (ou `install.sh`/`install.ps1`)
  de novo na pasta nova; ele refaz o `.venv` e atualiza o Claude.
- **Qualquer outra coisa**: `agente doctor`.
