# Contributing to Polyglot PMD

Thanks for helping improve PMD. Small, focused changes are easiest to review.

## Before you start

- Search existing issues and proposals before opening a new one.
- Use an issue for bugs and narrowly scoped feature requests.
- Use a proposal for changes to the document format, execution semantics, agent
  protocol, or public CLI behavior.
- Report vulnerabilities privately as described in `SECURITY.md`.

## Development setup

```console
git clone https://github.com/qwertyuu/polyglot-md-llm.git
cd polyglot-md-llm
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
```

Before submitting a pull request, run:

```console
pytest
pmd check examples/basic.pmd --graph
pmd test examples/basic.pmd --fresh
python -m build
python -m twine check dist/*.whl dist/*.tar.gz
```

On PowerShell, pass the expanded wheel and source-distribution paths to
`twine check`.

## Pull requests

- Add or update tests for behavioral changes.
- Update `README.md`, specifications, and the shipped agent skill when public
  behavior changes.
- Add a concise entry to `CHANGELOG.md` for user-visible changes.
- Keep commits reviewable and avoid unrelated formatting changes.
- Explain the problem, the chosen behavior, and how you verified it.

By contributing, you agree that your contribution is licensed under the MIT
license in `LICENSE`.
