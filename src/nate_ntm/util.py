"""Miscellaneous utility helpers for :mod:`nate_ntm`.

This module currently contains only a placeholder ``replace_me``
function used by early scaffolding tests in ``tests/test_util.py``.
The implementation intentionally depends only on the Python standard
library so that importing :mod:`nate_ntm` remains lightweight.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def replace_me() -> None:
    """Placeholder function used by initial scaffolding tests.

    The body simply logs the module name at DEBUG level.
    """

    logger.debug("replace_me called from %s", __name__)
