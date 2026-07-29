"""Path setup so the tests import synaptic from the repo root without an install.

These unit tests never touch a live SynapCores instance; the live end-to-end path
is exercised by the demo and by the opt-in integration test.
"""

import os
import sys

_HERE = os.path.dirname(__file__)
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
