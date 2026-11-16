# this_file: src/pypitrust/__init__.py
"""Set up PyPI Trusted Publishing for GitHub repositories."""

try:
    from .__version__ import __version__
except ImportError:  # running from a source tree that was never built
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
