# Changelog

## Unreleased

- Desktop app `agente-app` (Windows and Linux): its own window with the app logo, opens
  with the agent **off**; "Acordar Agente" / "Desligar Agente" buttons on top. Off means
  every agent paused, Arm stopped, models unloaded from the GPU and the MCP tools answer
  that the agent is off. CLI: `agente desligar-agente`, `agente acordar-agente`.
- Phone app: the panel is an installable PWA (Android and iPhone). Access only through a
  private Tailscale network (`tailscale serve`), with an 8-character pairing code and a
  secure cookie; from the phone you cannot change allowed folders, sign-ins or the PC
  microphone. Setup: `agente celular`.
- Installers: `AgenteLocal-Setup-Windows.exe` (Inno Setup, no admin) and
  `AgenteLocal-Instalador-Linux.run`, built by GitHub Actions. Both install into
  Documents/Agente Local by default, keep your data on update and handle spaces in the
  folder name. `install.sh --celular` / `install.ps1 -Celular` keep the panel running.
- Installers recreate `.venv` when the folder was moved (absolute paths inside it).
- New tool `transcrever_imagem`: transcribes the text of screenshots and photos with the
  local vision model (the image never leaves the PC; optional save to `.md`, asks before
  overwriting).
- New tool `juntar_em_pdf`: merges photos, text files and existing PDFs into one PDF
  (A4 pages for photos, EXIF rotation, JPEG compression, asks before overwriting).
- Photos in HEIC/HEIF (iPhone) are supported by both tools, through `pi-heif` (decode only).
- Installer: also registers the MCP server in Claude Desktop on Linux and macOS.

## 1.0.0 (2026-11)

First public release.

- MCP server for Claude Code and Claude Desktop with 40 tools: tests, git, pull
  requests, summaries, project memory (RAG), code review, browser and screen control,
  second opinion and a token-savings report.
- Cost ladder: direct command → local model (Ollama) → free cloud AI (OmniRoute,
  optional) → Claude only when needed. Every answer is labelled with where it came from.
- Agents: Maestro (router), Gatekeeper, Memory, Reviewer and Arm.
- Web panel (`agente-painel`): PC usage, Ollama/OmniRoute status, agent switches,
  chat with the route of each answer, microphone, history, savings chart, projects and
  Settings (sign in to Claude and GitHub, OmniRoute model queue, allowed folders,
  voice shortcut).
- Voice (optional extra): press the shortcut to start talking, press again to send.
- `agente init` (picks models for your GPU and registers in Claude) and `agente doctor`.
- One-command installers for Linux and Windows.
