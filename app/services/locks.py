"""Verrous de concurrence locaux (Qdrant embarqué : un seul process/thread à la fois).

L'indexation, le watcher et l'audit partagent le meme verrou applicatif pour ne jamais ouvrir
Qdrant en parallele (mode embedded : le dossier de stockage est verrouille par le premier
client). Le verrou est in-process ; pour plusieurs processus independants, utiliser
qdrant_mode='server'.
"""
from __future__ import annotations

import threading
from functools import wraps

INDEX_LOCK = threading.RLock()


def qdrant_locked(fn):
    """Execute fn sous le verrou global de Qdrant."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        with INDEX_LOCK:
            return fn(*args, **kwargs)

    return wrapper
