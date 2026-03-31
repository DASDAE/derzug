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

> [!TIP]
> DerZug can be installed on any of the listed Python versions, but Qt-related issues are still possible.
> The smoothest experience is generally on Python 3.13. It may help to first create a mamba/conda environment 
> with Orange3 installed, then install DerZug into that. 

## Basic Usage

DerZug is a full-fledged application that can be launched from the command line like so:

```bash
derzug
```

Conversely, DerZug can be used interactively in code: 

```python
import dascore as dc

patch = dc.get_example_patch("example_event_2")

# Launches a waterfall window for viewing a patch 
patch.zug.waterfall()
```


## Defining you own widgets

Simple, processing type widgets can be defined simply like so:

```python
import dascore as dc

import derzug

class MyWidget(derzug.ZugWidget):
    """A custom widget which just wraps a task or callable."""
    
    name # comes from function/task name
    description # First line of docstring
    icon = "myicon.svg"
    category = "Processing"
    keywords = ("processing")
    priority = 21
    
    _task = dc.processing.pass_filter


# A more complex multiwidget. This will a single drop down 
# to select which sub process is used. Derzug should automatically
# handle creating a simple paramter input based on function inputs. 
class MultiWidget(derzug.ZugWidget):
    """A custom widget which just wraps a task or callable."""
    
    name = "smooth"  # needs to be manually set
    description = "smooth patch along dimension" # First line of docstring
    icon = "myicon.svg"
    category = "Processing"
    keywords = ("processing")
    priority = 21
    
    _task = {
        "pass_filter": dc.processing.pass_filter,
        "savgol_filter: dc.processing.savgol_filter,
    }


```
