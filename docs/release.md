# Releasing DerZug

This document describes the exact steps to publish `derzug` to TestPyPI and
PyPI using `uv`, Git tags, and GitHub trusted publishing.

The first public release is intended to be `0.0.1`.

## Release model

- Build frontend: `uv`
- Build artifacts: wheel and source distribution
- Publish path: GitHub Actions
- Authentication: PyPI trusted publishing via GitHub OIDC
- Release trigger: pushing a Git tag like `v0.0.1`

## One-time setup

### 1. Create the package on TestPyPI and PyPI

Reserve the `derzug` project on:

- `https://test.pypi.org/`
- `https://pypi.org/`

If the name is unavailable, stop and choose a different distribution name
before tagging any release.

### 2. Configure trusted publishing on TestPyPI

In TestPyPI:

1. Open the `derzug` project settings.
2. Add a trusted publisher.
3. Use this repository and workflow:
   - Owner: `DASDAE`
   - Repository: `derzug`
   - Workflow file: `release.yml`
   - Environment: `testpypi`

### 3. Configure trusted publishing on PyPI

In PyPI:

1. Open the `derzug` project settings.
2. Add a trusted publisher.
3. Use this repository and workflow:
   - Owner: `DASDAE`
   - Repository: `derzug`
   - Workflow file: `release.yml`
   - Environment: `pypi`

### 4. Create GitHub environments

In GitHub repository settings, create these environments:

- `testpypi`
- `pypi`

Recommended:

- Leave `testpypi` open.
- Put required reviewers on `pypi` so production publishing needs explicit approval.

## Pre-release checklist

Before cutting a release:

1. Ensure [`pyproject.toml`](/home/derrick/Gits/derzug/pyproject.toml) has the correct metadata.
2. Ensure [`README.md`](/home/derrick/Gits/derzug/README.md) is suitable for the PyPI project page.
3. Commit all release-related changes.
4. Make sure the release commit is on the branch you want to tag.

## Local verification

Run these commands from the repo root.

### 1. Clean old build artifacts

```bash
rm -rf build dist .venv-wheel-smoke .venv-sdist-smoke
```

### 2. Build the distributions

```bash
uv build
```

Expected outputs:

- `dist/derzug-0.0.1.tar.gz`
- `dist/derzug-0.0.1-py3-none-any.whl`

### 3. Check distribution metadata

```bash
uv run --isolated --no-project --with twine twine check dist/*
```

### 4. Smoke test the wheel without pulling runtime dependencies

```bash
uv venv --python 3.12 .venv-wheel-smoke
uv pip install --python .venv-wheel-smoke/bin/python --no-deps dist/*.whl
.venv-wheel-smoke/bin/python -c "from derzug.version import __version__; print(__version__)"
.venv-wheel-smoke/bin/python -m derzug.cli --help
```

### 5. Smoke test the sdist

```bash
uv venv --python 3.12 .venv-sdist-smoke
uv pip install --python .venv-sdist-smoke/bin/python --no-deps dist/*.tar.gz
.venv-sdist-smoke/bin/python -c "from derzug.version import __version__; print(__version__)"
```

## TestPyPI rehearsal

Use a prerelease tag to exercise the workflow without publishing a final release.

### 1. Create and push a rehearsal tag

```bash
git tag v0.0.1rc1
git push origin v0.0.1rc1
```

### 2. Confirm the workflow behavior

The GitHub Actions workflow should:

1. Build the distributions with `uv build`.
2. Run `twine check`.
3. Run the wheel and sdist smoke tests.
4. Publish to TestPyPI.
5. Stop before PyPI because the tag is a prerelease.

### 3. Verify install from TestPyPI

In a clean environment:

```bash
python -m venv /tmp/derzug-testpypi
/tmp/derzug-testpypi/bin/pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple \
  derzug==0.0.1rc1
```

Then verify:

```bash
/tmp/derzug-testpypi/bin/python -c "from derzug.version import __version__; print(__version__)"
```

## Production release

Once the TestPyPI rehearsal looks good, cut the real release.

### 1. Create and push the real tag

```bash
git tag v0.0.1
git push origin v0.0.1
```

### 2. Approve the PyPI environment

If the `pypi` GitHub environment requires approval:

1. Open the running `Release` workflow.
2. Approve the `pypi` environment.

### 3. Verify the published package

After the workflow completes:

1. Open the PyPI project page and confirm the README renders correctly.
2. Install the published package in a clean environment:

```bash
python -m venv /tmp/derzug-pypi
/tmp/derzug-pypi/bin/pip install derzug==0.0.1
/tmp/derzug-pypi/bin/python -c "from derzug.version import __version__; print(__version__)"
```

## Tag conventions

- Final release: `v0.0.1`
- Rehearsal prerelease: `v0.0.1rc1`
- Future patch release: `v0.0.2`

## Notes

- Do not upload manually from a developer machine once trusted publishing is configured.
- Keep the release workflow file name as `.github/workflows/release.yml`, since PyPI trusted publishing is configured against that exact workflow.
- If the release fails after a file is uploaded to PyPI, do not overwrite the same version. Cut a new version instead.
