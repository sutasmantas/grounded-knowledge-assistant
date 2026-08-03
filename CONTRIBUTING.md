# Contributing

## Development setup

Use the repository Codespace or install the editable development package:

```bash
python -m pip install -e ".[dev]"
```

For a fast, deterministic local loop, set
`ATLAS_EMBEDDING_PROVIDER=hash`. Before opening a pull request, run:

```bash
ruff check .
pytest --cov=app --cov-report=term-missing
```

Keep retrieval, generation, and storage changes independently testable.
Document any new provider's data boundary, credential requirements, and failure
behavior in `docs/architecture.md`.
