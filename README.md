# DerZug

> [!WARNING]
> ## Experimental Software
> DerZug is an early-stage proof of concept.
> Expect bugs, incomplete behavior, data-loss risks, and frequent breaking changes.
> The creators make no promises of further development or maintenance.

<img src="https://raw.githubusercontent.com/dasdae/derzug/main/docs/static/logo_v2.png" width="500">

DerZug is powered by the [Orange3](https://orangedatamining.com/),
[PyQtGraph](https://www.pyqtgraph.org/), and [DASDAE](https://dasdae.org)
ecosystems.

It's goal is to allow users to **interactively create, debug, and share reproducible DFOS workflows**.

It can be launched as a standalone application, or used for interactive exploration (in code).

## Installation

Install from PyPI with:
```bash
pip install derzug
```

or mamba/conda:
```bash
mamba install derzug
```

> [!TIP]
> The PyQT stack can have some rough installation edges. The smoothest experience is generally on Python 3.13 with mamba.

## Getting Started

To get a quick introduction to DerZug, launch it in demo mode and load the quickstart workflow:

```bash
derzug --demo
```

DerZug can also be used interactively in code: 

```python
import dascore as dc

patch = dc.get_example_patch("example_event_2")

# Launches a waterfall window for viewing a patch 
patch.zug.waterfall()
```

