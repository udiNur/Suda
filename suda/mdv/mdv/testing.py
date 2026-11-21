"""For the viewer's tests in the Suda repository (test_mdv_*.py, test_adv_mdv_*.py)."""
import socket
from pathlib import Path

from . import sync

PACKAGE = Path(__file__).resolve().parent          # mdv/mdv
REPO = PACKAGE.parent.parent                        # Suda's app folder (suda/), with suda.html
SAMPLES = PACKAGE.parent / 'samples'


def prepare() -> None:
    """Suda's pieces in mdv/static, from the repository's suda.html (they are generated, not committed)."""
    sync.write(PACKAGE.parent / 'static', REPO / 'suda.html')


def free_port() -> int:
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port
