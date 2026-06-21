# Make generated proto modules importable by adding this package dir to sys.path.
import sys
import os

_pkg_dir = os.path.dirname(__file__)
if _pkg_dir not in sys.path:
    sys.path.insert(0, _pkg_dir)
