"""Repo-root pytest configuration.

Puts both workspace packages on ``sys.path`` so ``pytest`` can be run from the
repository root without a colcon install or a manually-set ``PYTHONPATH``:

    pytest src/urdf_live_editor/test src/urdf_ai_agents/test
"""

import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
for _pkg in ("urdf_live_editor", "urdf_ai_agents"):
    _path = os.path.join(_ROOT, "src", _pkg)
    if _path not in sys.path:
        sys.path.insert(0, _path)
