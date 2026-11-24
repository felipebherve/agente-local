# Changelog

## Unreleased

- New tool `transcrever_imagem`: transcribes the text of screenshots and photos with the
  local vision model (the image never leaves the PC; optional save to `.md`).
- New tool `juntar_em_pdf`: merges photos and text files into one A4 PDF (EXIF rotation,
  JPEG compression, asks before overwriting).
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
