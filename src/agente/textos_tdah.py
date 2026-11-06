"""Textos que a pessoa vê no Modo TDAH, todos num lugar só.

Hoje só pt-BR. Para traduzir: copie o bloco "pt-BR" para "en", traduza os valores e
mude IDIOMA (ou leia do config). As chaves nunca mudam.
"""

from __future__ import annotations

IDIOMA = "pt-BR"

TEXTOS: dict[str, dict[str, str]] = {
    "pt-BR": {
        "req_pastas": "Pastas de projetos liberadas",
        "req_git": "Git instalado",
        "req_ollama": "Ollama no ar (para os resumos automáticos)",
        "erro_desligado": "ligue o Modo TDAH em Configurações",
        "erro_nao_achado": "projeto não encontrado",
        "erro_horas": "parado_horas precisa ser um número",
        "erro_fora": "pasta fora das pastas liberadas",
        "erro_ja_tem_ficha": "este projeto já tem STATUS.md",
        "sem_resumo": "Sem commits ou o modelo local não respondeu.",
        "nome_vazio": "Diga o nome do projeto que pretende criar.",
        "nome_livre": "Nenhum projeto parecido com '{nome}'. Pode criar.",
        "nome_parecido": "Já existe projeto parecido com '{nome}' (confira antes de criar outro):",
        "ctx_projeto": "Projeto: {v}",
        "ctx_pasta": "Pasta: {v}",
        "ctx_github": "GitHub: {v}",
        "ctx_concluido": "Concluído: {v}%",
        "ctx_resumo": "Resumo: {v}",
        "ctx_mudancas": "Últimas mudanças: {v}",
        "ctx_falta": "Falta: {v}",
        "ctx_proxima": "Próxima ação: {v}",
        "semanal_titulo": (
            "Meus projetos (resumo da semana). Sugira as 3 prioridades e o porquê, curto."
        ),
        "sem_prioridade": "sem prioridade",
        "sem_proxima": "sem próxima ação",
        "parado": "parado {h:.0f}h",
        "pasta_vazia": "Pasta vazia.",
        "sem_leiame": "Sem README nem STATUS.md. {titulo}Contém: {nomes}",
        "ficha_resumo_vazio": "Escreva aqui em 3 linhas o que é o projeto.",
    },
}


def t(chave: str, **valores: object) -> str:
    """Texto da chave no idioma atual (cai no pt-BR se faltar a tradução)."""
    texto = TEXTOS.get(IDIOMA, {}).get(chave) or TEXTOS["pt-BR"][chave]
    return texto.format(**valores) if valores else texto
