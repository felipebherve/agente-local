# agente-local

**English** · [Português](README.pt-BR.md) · [Website](https://felipebherve.github.io/agente-local/)

A free AI helper that runs on **your own graphics card** and does the mechanical work for
**Claude Code**: running tests, git, pull requests, summaries, code review, project search
and the browser. Claude gets a short answer instead of thousands of lines, so you spend
far fewer tokens.

> On the author's PC it has already saved **over 370,000 Claude tokens** in about
> 100 tasks.

## How it works

Every request climbs a cost ladder and stops at the first step that solves it:

```
direct command  →  local model (Ollama)  →  free cloud AI (OmniRoute, optional)  →  Claude
   free, instant      free, private            free, needs internet                  paid
```

Claude talks to the agent through **MCP** (Model Context Protocol). Inside, a few small
agents share the work:

| Agent | What it does |
|---|---|
| **Maestro** | Reads each request and sends it to the right agent. |
| **Gatekeeper** (Porteiro) | Answers simple questions locally or on free cloud AI; passes the rest to Claude. |
| **Memory** (Memória) | Indexes your projects and hands Claude only the relevant snippets. |
| **Reviewer** (Revisor) | Runs lint, types and tests; blocks commits with passwords or conflict markers. |
| **Arm** (Braço) | Controls the browser and screen, asking before anything risky. |

Every answer is labelled with where it came from (`[Ollama local · model]`,
`[OmniRoute · model]`), so you always know who answered.

## Requirements

| | Minimum | Recommended |
|---|---|---|
| OS | Linux or Windows 10/11 | Ubuntu 24.04+ / Windows 11 |
| GPU | none (CPU works, slowly) | NVIDIA with 8–12 GB |
| RAM | 8 GB | 16 GB |
| Software | Python 3.10+, Git, [Ollama](https://ollama.com), [Claude Code](https://claude.com/claude-code) | + Node.js (for OmniRoute), Google Chrome (for the browser tools), [GitHub CLI](https://cli.github.com) (for PRs) |

`agente init` picks models that fit your GPU:

| GPU memory | Models |
|---|---|
| 12 GB or more | qwen3:8b, qwen2.5-coder:7b, qwen2.5vl:7b |
| 8 GB | qwen3:8b, qwen2.5-coder:7b |
| 6 GB | qwen3:4b, qwen2.5-coder:3b |
| CPU only | qwen3:1.7b, qwen2.5-coder:1.5b |

## Install

**Linux**

```bash
git clone https://github.com/felipebherve/agente-local.git
cd agente-local
./install.sh            # add --voz for the voice shortcut, --sim to accept all defaults
```

**Windows** (PowerShell)

```powershell
git clone https://github.com/felipebherve/agente-local.git
cd agente-local
powershell -ExecutionPolicy Bypass -File .\install.ps1     # -Voz, -Sim
```

The installer installs what is missing (Ollama; on Windows also Python and Git through
`winget`), creates the agent's environment, downloads the models, writes `config.yaml`,
registers the agent in Claude Code and Claude Desktop and creates an **Agente local**
shortcut that opens the panel in your browser.

Something wrong? Run `agente doctor` (Windows: `.venv\Scripts\agente.exe doctor`).

## Connect your accounts

The agent never stores passwords. It uses the logins you already have:

- **Claude**: sign in to Claude Code as usual. The agent is just an MCP tool inside it.
- **GitHub**: run `gh auth login` once. The agent uses it for push and pull requests.
- **OmniRoute (free cloud AI, optional)**:
  1. `npm install -g omniroute` and run `omniroute`.
  2. Open `http://localhost:20128`, go to **Providers** and connect a free provider with
     your own account (Groq, Gemini, NVIDIA NIM and others offer free tiers).
  3. In `config.yaml`, set `omniroute.ligado: true` and add the model ids under
     `omniroute.modelos`, e.g. `- groq/llama-3.3-70b-versatile`.
- **Browser**: the Arm uses its own Chrome profile. Sign in to sites there once; the
  logins stay in Chrome, not in the agent.

## Use

You do not need to do anything special: Claude Code calls the agent on its own
(`agente init` adds the instructions to `~/.claude/CLAUDE.md`). Some things you can ask:

- "run the tests" · "commit this" · "open a draft PR"
- "what changed in this project?" · "where is the login handled?"
- "review the project before I ship"

**Panel** (`agente-painel` or the *Agente local* shortcut): PC usage, Ollama and
OmniRoute status, switches for each agent, a chat that shows the route of every answer,
microphone, history, savings chart, your projects and a **Settings** tab to sign in to
Claude and GitHub, pick your OmniRoute models, choose which folders the agent may use
and change the voice shortcut.

**Voice** (optional, `--voz`): press **Ctrl+Alt+F** to start talking and press it again
to send. You can change the shortcut in the panel (Settings).

<details>
<summary>All MCP tools</summary>

`pedir_ao_agente`, `perguntar_local`, `segunda_opiniao`, `resumir_texto`,
`resumir_arquivo`, `rodar_testes`, `git_status`, `git_pull`, `git_criar_branch`,
`git_commit`, `git_merge`, `git_push`, `abrir_pr`, `relatorio_economia`, `status_agente`,
`contexto_projeto`, `ler_relevante`, `indexar_projeto`, `lembrar`, `revisar_projeto`,
`organizar_pasta`, `navegador_abrir`, `navegador_ler`, `navegador_clicar`,
`navegador_preencher`, `navegador_tecla`, `navegador_fechar`, `janelas_listar`,
`janela_ler`, `janela_clicar`, `janela_digitar`, `abrir_app`, `tela_descrever`,
`tela_clicar`, `braco_liberar`, `reiniciar_claude`, `falar`.

</details>

## Safety and privacy

- Reads only the folders in `pastas_permitidas` and runs only the commands in
  `comandos_liberados`.
- Asks before submitting forms, logging in, paying, buying, deleting or typing into a
  password field. To stop the Arm at once, turn off its switch in the panel
  (on Windows, **Ctrl+Alt+P** also works).
- Web pages can contain text that tries to give the agent orders (prompt injection).
  Keep the confirmations on.
- No telemetry and no server of ours: everything runs on your PC, except what you send
  to OmniRoute providers or to Claude.

See [SECURITY.md](SECURITY.md) to report a problem.

## License and disclaimers

[MIT](LICENSE) © 2026 Felipe Bruno Hervé. Third-party licenses are listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md); the optional voice extra uses Piper,
which is GPL-3.0.

This is an independent project, not affiliated with Anthropic, Ollama, OmniRoute or
GitHub. "Claude" is a trademark of Anthropic. The agent runs commands and clicks on your
computer: use it at your own risk, and follow the terms of every AI provider you connect.

The code and comments are in Brazilian Portuguese; the docs are in English and
Portuguese. Contributions are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md).
