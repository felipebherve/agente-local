# Third-party notices

agente-local is MIT-licensed. It **uses** (does not copy or bundle) the packages and
programs below. Each one keeps its own license. The installers download them from their
official sources.

## Python packages, default install

| Package | License | Link |
|---|---|---|
| mcp (Model Context Protocol SDK) | MIT | https://github.com/modelcontextprotocol/python-sdk |
| PyYAML | MIT | https://pyyaml.org |
| playwright | Apache-2.0 | https://playwright.dev/python |
| mss | MIT | https://github.com/BoboTiG/python-mss |
| Pillow | MIT-CMU | https://python-pillow.org |
| psutil | BSD-3-Clause | https://github.com/giampaolo/psutil |
| numpy | BSD-3-Clause | https://numpy.org |
| pystray | LGPL-3.0 | https://github.com/moses-palmer/pystray |
| fpdf2 | LGPL-3.0 | https://github.com/py-pdf/fpdf2 |
| pywinauto (Windows only) | BSD-3-Clause | https://github.com/pywinauto/pywinauto |
| pywin32 (Windows only) | PSF-2.0 | https://github.com/mhammond/pywin32 |

pystray and fpdf2 are LGPL-3.0: they are used as unmodified, separately installed
libraries, which the LGPL allows. You can replace them with any compatible version.

## Optional voice extra (`pip install "agente-local[voz]"`)

| Package | License | Link |
|---|---|---|
| sounddevice | MIT | https://github.com/spatialaudio/python-sounddevice |
| faster-whisper | MIT | https://github.com/SYSTRAN/faster-whisper |
| piper-tts | **GPL-3.0-or-later** | https://github.com/OHF-Voice/piper1-gpl |
| nvidia-cublas-cu12, nvidia-cudnn-cu12 (Windows) | NVIDIA license | https://pypi.org/project/nvidia-cublas-cu12/ |

Piper is GPL-3.0, which is why voice is an optional extra and not part of the default
install. Piper voices have their own licenses: check the voice's model card before using it.

## Programs you install separately

| Program | License | Link |
|---|---|---|
| Ollama | MIT | https://ollama.com |
| OmniRoute (optional) | MIT | https://github.com/diegosouzapw/OmniRoute |
| Claude Code / Claude Desktop | Anthropic terms | https://claude.com |
| GitHub CLI (optional) | MIT | https://cli.github.com |

## AI models (downloaded by you through Ollama, never shipped here)

| Model | License |
|---|---|
| Qwen3, Qwen2.5-Coder, Qwen2.5-VL | Apache-2.0 (check each size's model card) |
| nomic-embed-text | Apache-2.0 |
| Whisper (via faster-whisper) | MIT |

## Trademarks

agente-local is an independent project. It is not affiliated with, endorsed by or
sponsored by Anthropic, Ollama, OmniRoute, GitHub, Alibaba (Qwen) or NVIDIA. "Claude" is
a trademark of Anthropic. Other names belong to their owners.

## Free AI providers

When you connect providers in OmniRoute, you are responsible for following each
provider's terms of use. Prefer providers that offer an official free tier with your own
account. Some "web" providers work by automating a public website and may break those
sites' terms: use them at your own risk.
