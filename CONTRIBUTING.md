# Contributing

Thanks for helping! Issues and pull requests are welcome, in English or Portuguese.

1. Fork and clone, then: `python -m venv .venv && .venv/bin/pip install -e ".[dev,voz]"`
   (Windows: `.venv\Scripts\pip install -e ".[dev,voz]"`).
2. Before opening a PR: `ruff check src tests`, `mypy src` and `pytest -q`.
3. Keep changes small and explain *why* in the PR.

The code and its comments are in Brazilian Portuguese (the project started that way);
documentation is in English and Portuguese.

By contributing you agree that your contribution is licensed under the MIT License of
this project. Please follow the [Code of Conduct](CODE_OF_CONDUCT.md).
