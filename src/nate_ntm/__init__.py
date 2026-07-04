"""Top-level :mod:`nate_ntm` package.

The package root is intentionally lightweight; most callers should import
submodules (for example :mod:`nate_ntm.cli`) directly.

During the early project bootstrap phase we also re-export the
:mod:`nate_ntm.util` module to satisfy legacy tests in ``tests/test_util``.
This can be revisited once those tests are replaced by spec-driven ones.
"""

from . import util

__all__ = [
    "__version__",
    "util",
]

__version__ = "0.1.0"