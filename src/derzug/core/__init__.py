"""
DerZug core modules.
"""
from derzug.core.zugmodel import DerZugModel as DerZugModel
from derzug.core.patchdimwidget import PatchDimWidget as PatchDimWidget
from derzug.core.zugwidget import ZugWidget as ZugWidget
from derzug.exceptions import DerZugError as DerZugError
from derzug.exceptions import DerZugWarning as DerZugWarning

# Workflow code currently imports these historical spellings. Keep them as
# compatibility aliases until the workflow rename is cleaned up properly.
DerzugModel = DerZugModel
DerzugBaseModel = DerZugModel
SlanRodModel = DerZugModel
SlanRodBaseModel = DerZugModel

__all__ = (
    "DerZugError",
    "DerZugModel",
    "DerZugWarning",
    "DerzugBaseModel",
    "DerzugModel",
    "PatchDimWidget",
    "SlanRodBaseModel",
    "SlanRodModel",
    "ZugWidget",
)
