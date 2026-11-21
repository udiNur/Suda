"""tests/_paths.py, for a test started from this folder: that file is the one source, run here as this module."""
from pathlib import Path

_shared = Path(__file__).resolve().parents[1] / '_paths.py'
exec(compile(_shared.read_text(encoding='utf-8'), str(_shared), 'exec'))
