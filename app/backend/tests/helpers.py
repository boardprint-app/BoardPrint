"""Utilidades comunes de los tests: una pizarra sobre un proyecto en un workspace temporal."""
import tempfile
import unittest
from pathlib import Path

from pizarra.board import Board
from pizarra.storage import LocalWorkspace

# Los paquetes del repo (`demo`, `robotica`...), que estos tests cargan por defecto (`__init__.py`).
# El repo público no los lleva: lo que los necesita se salta allí, y aquí corre igual que siempre.
REPO_PACKS = Path(__file__).resolve().parents[3] / "packs"
necesita_paquetes = unittest.skipUnless(REPO_PACKS.is_dir(), "sin packs/: necesita los paquetes del repo")


def new_board(name="Proyecto"):
    ws = LocalWorkspace.open(Path(tempfile.mkdtemp()) / "Personal", trash=lambda p: None)
    return Board(ws, ws.create_project("", name).id, connectors=frozenset())   # sin Fusion, aunque esté abierto


def reopen(board):
    """La misma pizarra leída otra vez del almacenamiento, como al volver a abrir la app."""
    return Board(board.ws, board.project_id, connectors=board.connectors)
