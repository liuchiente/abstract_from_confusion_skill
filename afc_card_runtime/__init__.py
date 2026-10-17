"""AFC Card Experiment runtime.

The version is whatever VERSION says; a literal here went stale at 0.2.0 while
the package shipped 0.8.6.
"""
from .config import package_version


def __getattr__(name):
    if name == '__version__':
        return package_version()
    raise AttributeError(name)
