# agente-local

[English](README.md) · **Português** · [Site](https://felipebherve.github.io/agente-local/)

Um ajudante de IA gratuito que roda na **sua placa de vídeo** e faz o trabalho mecânico
do **Claude Code**: rodar testes, git, pull requests, resumos, revisão de código, busca
nos projetos e navegador. O Claude recebe uma resposta curta em vez de milhares de
linhas, e você gasta muito menos tokens.

> No PC do autor, ele já poupou **mais de 370 mil tokens do Claude** em cerca de
> 100 tarefas.

## Como funciona

Cada pedido sobe uma escada de custo e para no primeiro degrau que resolve:

```
comando direto  →  modelo local (Ollama)  →  IA grátis na nuvem (OmniRoute, opcional)  →  Claude
 grátis, na hora      grátis, privado            grátis, precisa de internet                pago
```

O Claude conversa com o agente pelo **MCP** (Model Context Protocol). Lá dentro, alguns
agentes pequenos dividem o trabalho:

| Agente | O que faz |
|---|---|
| **Maestro** | Lê cada pedido e manda para o agente certo. |
| **Porteiro** | Responde o simples no PC ou na IA grátis; o resto vai para o Claude. |
| **Memória** | Indexa seus projetos e entrega ao Claude só os trechos que importam. |
| **Revisor** | Roda lint, tipos e testes; trava commit com senha ou marca de conflito. |
| **Braço** | Controla o navegador e a tela, e pergunta antes de qualquer coisa arriscada. |

Toda resposta vem com a etiqueta de onde veio (`[Ollama local · modelo]`,
`[OmniRoute · modelo]`), para você saber sempre quem respondeu.

## O que precisa

| | Mínimo | Recomendado |
|---|---|---|
| Sistema | Linux ou Windows 10/11 | Ubuntu 24.04+ / Windows 11 |
| Placa de vídeo | nenhuma (roda no processador, mais lento) | NVIDIA com 8 a 12 GB |
| Memória | 8 GB | 16 GB |
| Programas | Python 3.10+, Git, [Ollama](https://ollama.com), [Claude Code](https://claude.com/claude-code) | + Node.js (para o OmniRoute), Google Chrome (para o navegador), [GitHub CLI](https://cli.github.com) (para PRs) |

O `agente init` escolhe os modelos que cabem na sua placa:

| Memória da placa | Modelos |
|---|---|
| 12 GB ou mais | qwen3:8b, qwen2.5-coder:7b, qwen2.5vl:7b |
| 8 GB | qwen3:8b, qwen2.5-coder:7b |
| 6 GB | qwen3:4b, qwen2.5-coder:3b |
| Só processador | qwen3:1.7b, qwen2.5-coder:1.5b |

## Instalar

**Linux**

```bash
git clone https://github.com/felipebherve/agente-local.git
cd agente-local
./install.sh            # --voz para o atalho de voz, --sim para aceitar tudo
```

**Windows** (PowerShell)

```powershell
git clone https://github.com/felipebherve/agente-local.git
cd agente-local
powershell -ExecutionPolicy Bypass -File .\install.ps1     # -Voz, -Sim
```

O instalador instala o que faltar (Ollama; no Windows também Python e Git pelo
`winget`), cria o ambiente do agente, baixa os modelos, escreve o `config.yaml`, registra
o agente no Claude Code e no Claude Desktop e cria o atalho **Agente local**, que abre o
painel no seu navegador.

Deu algo errado? Rode `agente doctor` (Windows: `.venv\Scripts\agente.exe doctor`).

## Conectar suas contas

O agente nunca guarda senha. Ele usa os logins que você já tem:

- **Claude**: entre no Claude Code como sempre. O agente é só uma ferramenta MCP dele.
- **GitHub**: rode `gh auth login` uma vez. O agente usa isso para push e pull requests.
- **OmniRoute (IA grátis na nuvem, opcional)**:
  1. `npm install -g omniroute` e rode `omniroute`.
  2. Abra `http://localhost:20128`, vá em **Providers** e conecte um provedor grátis com a
     sua conta (Groq, Gemini, NVIDIA NIM e outros têm plano gratuito).
  3. No `config.yaml`, coloque `omniroute.ligado: true` e os ids dos modelos em
     `omniroute.modelos`, por exemplo `- groq/llama-3.3-70b-versatile`.
- **Navegador**: o Braço usa um perfil próprio do Chrome. Entre nos sites por ele uma
  vez; os logins ficam no Chrome, não no agente.

## Usar

Não precisa fazer nada especial: o Claude Code chama o agente sozinho (o `agente init`
coloca as instruções em `~/.claude/CLAUDE.md`). Exemplos do que pedir:

- "roda os testes" · "faz o commit" · "abre um PR em rascunho"
- "o que mudou neste projeto?" · "onde fica o login?"
- "revisa o projeto antes de eu publicar"

**Painel** (`agente-painel` ou o atalho *Agente local*): uso do PC, Ollama e OmniRoute,
chave para ligar e desligar cada agente, conversa que mostra o caminho de cada resposta,
microfone, histórico, gráfico de economia, seus projetos e a aba **Configurações**, para
entrar no Claude e no GitHub, escolher os modelos do OmniRoute, escolher as pastas que o
agente pode usar e trocar o atalho de voz.

**Voz** (opcional, `--voz`): aperte **Ctrl+Alt+F** para começar a falar e aperte de novo
para mandar. Dá para trocar o atalho no painel (Configurações).

<details>
<summary>Todas as ferramentas MCP</summary>

`pedir_ao_agente`, `perguntar_local`, `segunda_opiniao`, `resumir_texto`,
`resumir_arquivo`, `rodar_testes`, `git_status`, `git_pull`, `git_criar_branch`,
`git_commit`, `git_merge`, `git_push`, `abrir_pr`, `relatorio_economia`, `status_agente`,
`contexto_projeto`, `ler_relevante`, `indexar_projeto`, `lembrar`, `revisar_projeto`,
`organizar_pasta`, `navegador_abrir`, `navegador_ler`, `navegador_clicar`,
`navegador_preencher`, `navegador_tecla`, `navegador_fechar`, `janelas_listar`,
`janela_ler`, `janela_clicar`, `janela_digitar`, `abrir_app`, `tela_descrever`,
`tela_clicar`, `braco_liberar`, `reiniciar_claude`, `falar`.

</details>

## Segurança e privacidade

- Só lê as pastas de `pastas_permitidas` e só roda os comandos de `comandos_liberados`.
- Pergunta antes de enviar formulário, entrar em conta, pagar, comprar, apagar ou digitar
  em campo de senha. Para parar o Braço na hora, desligue a chave dele no painel (no
  Windows, **Ctrl+Alt+P** também funciona).
- Uma página pode trazer texto tentando dar ordens ao agente (injeção de prompt).
  Mantenha as confirmações ligadas.
- Sem telemetria e sem servidor nosso: tudo roda no seu PC, menos o que você mandar para
  os provedores do OmniRoute ou para o Claude.

Para avisar um problema, veja [SECURITY.md](SECURITY.md).

## Licença e avisos

[MIT](LICENSE) © 2026 Felipe Bruno Hervé. As licenças de terceiros estão em
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md); a voz (opcional) usa o Piper, que é
GPL-3.0.

Projeto independente, sem vínculo com Anthropic, Ollama, OmniRoute ou GitHub. "Claude" é
marca da Anthropic. O agente roda comandos e clica no seu computador: use por sua conta e
risco, e siga os termos de cada provedor de IA que você conectar.

O código e os comentários estão em português; a documentação, em inglês e português.
Contribuições são bem-vindas: veja [CONTRIBUTING.md](CONTRIBUTING.md).
