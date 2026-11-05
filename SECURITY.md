# Security

agente-local runs commands, opens web pages and can click and type on your computer.
Please report security problems **privately**, not in a public issue:

- Use GitHub's **Report a vulnerability** button on the *Security* tab of this repository.

Include what you did, what happened and the output of `agente doctor` (remove anything
personal first). I will answer as soon as I can.

## Built-in safety

- The agent only reads folders listed in `pastas_permitidas` and only runs commands in
  `comandos_liberados` (`config.yaml`).
- The browser "arm" asks for confirmation before submit, login, pay, buy or delete
  buttons and before typing into password fields. Its switch in the panel (and
  **Ctrl+Alt+P** on Windows) stops it at once.
- The Reviewer blocks commits that contain passwords, keys or merge-conflict markers.
- Web pages may contain text that tries to give the agent orders (prompt injection).
  The agent treats page text as data and keeps the confirmations on by default.
  Do not turn them off.
- No telemetry. Nothing leaves your PC except what you send to OmniRoute providers or
  to Claude.
