# DerZug

**Experimental:** DerZug is an early-stage DAS application with frequent breaking
changes and limited compatibility guarantees. It is best suited for evaluation,
internal workflows, and contributor testing.

<img src="https://raw.githubusercontent.com/dasdae/derzug/main/docs/static/logo_v2.png" width="500">

DerZug is powered by the [Orange3](https://orangedatamining.com/),
[PyQtGraph](https://www.pyqtgraph.org/), and [DASDAE](https://dasdae.org)
ecosystems.

It has the following goals:

- Provide interactive visualizations of fiber-optic sensing datasets.
- Allow users to interactively create, modify, and share reproducible workflows.

It can be launched as a standalone application, or used for interactive exploration (in code).

## Installation

Install from PyPI with:

```bash
pip install derzug
```

For example, launching the full application:

```bash
derzug
```

Conversely, you can use DerZug directly from python for some quick interactive visualization:

```python
import dascore as dc

patch = dc.get_example_patch("example_event_2")

# Launches a waterfall window for viewing a patch 
patch.zug.waterfall()
```

## Development

Install the development dependencies, then install the git hooks with `prek`:

```bash
uv sync --extra test
uv run prek install -f
```

The repo hook configuration lives in `prek.toml`.

Run the repo checks locally with:

```bash
uv run prek run --all-files
```
