import locale
import os

os.environ["PARTCAD_ROOT"] = os.getcwd()

try:
    locale.setlocale(locale.LC_ALL, "en_US.UTF-8")
except locale.Error:
    # Same fallback as the CLI and the wrappers: the test runner must not fail
    # at import time on a machine that has only "C" generated, which is the
    # common case for the minimal images CI runs behave in.
    try:
        locale.setlocale(locale.LC_ALL, "C.UTF-8")
    except locale.Error:
        pass
