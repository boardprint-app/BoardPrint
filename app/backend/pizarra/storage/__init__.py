"""Almacenamiento de workspaces, carpetas y proyectos (docs/PLAN_PIZARRA.md §2, D68)."""
from pizarra.storage.base import (Conflict, InvalidName, Node, NotFound, ProjectInfo,
                                  StorageError, Workspace, WorkspaceInfo)
from pizarra.storage.local import LocalWorkspace

__all__ = ["Conflict", "InvalidName", "LocalWorkspace", "Node", "NotFound", "ProjectInfo",
           "StorageError", "Workspace", "WorkspaceInfo"]
