"""The MD Viewer, as the board server imports it (answer_server.py: THREADS_MDV_DIR, else
~/.local/share/threads/mdv, put there by `threads install`). See mdv/mdv/web.py."""
from mdv.web import config, handle, owns, unavailable  # noqa: F401
