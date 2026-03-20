# Releasing `derzug`

DerZug publishes from Git tags with `uv` and GitHub Actions.

## One-time setup

1. Create the `derzug` project on TestPyPI and PyPI.
2. Configure a trusted publisher on both services for this repository.
3. Create GitHub environments named `testpypi` and `pypi`.
4. Add required reviewers to the `pypi` environment if you want a manual approval gate.

## Local verification

Run the same checks the release workflow uses:

```bash
uv build
uv run --isolated --no-project --with twine twine check dist/*
uv venv --python 3.12 .venv-wheel-smoke
uv pip install --python .venv-wheel-smoke/bin/python --no-deps dist/*.whl
.venv-wheel-smoke/bin/python -c "from derzug.version import __version__; print(__version__)"
.venv-wheel-smoke/bin/python -m derzug.cli --help
```

## TestPyPI rehearsal

Publish a rehearsal tag if you want to validate the end-to-end release flow before
the real release:

```bash
git tag v0.0.1rc1
git push origin v0.0.1rc1
```

The GitHub workflow will build the distributions and publish them to TestPyPI.

## Production release

Create and push the real release tag:

```bash
git tag v0.0.1
git push origin v0.0.1
```

The release workflow will:

1. Build the wheel and source distribution with `uv build`.
2. Validate metadata with `twine check`.
3. Smoke test the built artifacts.
4. Publish to TestPyPI.
5. Publish to PyPI after the `pypi` environment is approved, if approvals are enabled.
