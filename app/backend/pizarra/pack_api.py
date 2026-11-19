"""Lo que un paquete puede hacer en la pizarra (docs/PLAN_PAQUETES.md P39, SDK 1.2).

Es lo que hay detrás de los métodos de pizarra de `RunContext` (`block`, `upstream`,
`set_params`, `postits`, `add_postit`, `clear_error`, `block_file`, `block_type`) en una acción de paquete
(`Board.action`). El paquete nunca ve el `Board`: solo esta API estrecha, para que un cambio
interno de la pizarra no lo rompa y para que no pueda hacer cualquier cosa con la escena.

Reglas (§10, «API del conector»):
- Un cambio de parámetros pasa **por la misma validación** que uno de la tarjeta
  (`Board.set_params`: solo los suyos, cada valor con el tipo del de por defecto, P49).
- Un post-it **nunca** se ancla a un bloque que no existe.

Apunta lo que cambia (`changed`, `new`) para que el servidor guarde y avise a las ventanas.
"""
import copy

from pizarra import graph, scene, validation
from pizarra.config import AUTHOR_USER


class BoardAPI:
    def __init__(self, board):
        self._board = board
        self.changed = False          # algo de la pizarra cambió: hay que guardar y avisar
        self.new = []                 # elementos nuevos (los post-its)

    def _block(self, block_id):
        if not isinstance(block_id, str):
            return None
        return graph.blocks_in(self._board.elements, self._board.registry).get(block_id)

    def _need(self, block_id):
        el = self._block(block_id)
        if el is None:
            raise validation.ValidationError(f"no hay ningún bloque {block_id!r}")
        return el

    def block(self, block_id):
        el = self._block(block_id)
        if el is None:
            return None
        b = self._board
        st = b.state.get(block_id) or {}
        kind = el["customData"]["blockType"]
        return copy.deepcopy({
            "id": block_id, "type": kind,
            "params": {**b.default_params(kind), **(st.get("params") or {})},
            "outputs": st.get("outputs"), "status": b.statuses().get(block_id),
            "error": st.get("error"), "busy": b.job is not None})

    def upstream(self, block_id, port):
        self._need(block_id)
        edges, _ = graph.build(self._board.elements, self._board.registry)
        src = (edges.get(block_id) or {}).get(port)
        return src[0] if src else None

    def set_params(self, block_id, params):
        self._board.set_params(block_id, params)
        self.changed = True

    def postits(self, block_id):
        out = []
        for e in self._board.elements:
            cd = e.get("customData") or {}
            if e.get("isDeleted") or cd.get("kind") != "postit":
                continue
            sync = cd.get("sync") or {}
            if cd.get("anchor") == block_id or sync.get("block") == block_id:
                out.append({"id": e["id"], "text": cd.get("text", ""),
                            "kind": cd.get("postitKind"), "state": cd.get("state"),
                            "keys": list(sync.get("keys") or [])})
        return copy.deepcopy(out)

    def add_postit(self, block_id, text, kind="nota", keys=()):
        self._need(block_id)
        if not isinstance(text, str) or not text.strip():
            raise validation.ValidationError("post-it vacío")
        if kind not in validation.POSTIT_KINDS:
            raise validation.ValidationError(
                f"tipo de post-it desconocido: {kind!r} (válidos: {validation.POSTIT_KINDS})")
        keys = [keys] if isinstance(keys, str) else list(keys)
        if not all(isinstance(k, str) for k in keys):
            raise validation.ValidationError("las marcas de un post-it (keys) son textos")
        b, text = self._board, text.strip()
        x, y = b._free_spot(scene.POSTIT_WIDTH, scene.postit_height(text), block_id)
        # Lo crea una acción que pide el usuario (aplicar, fijar…): es suyo, y sus cifras citan
        # el bloque (D51), como el post-it de riesgo de *Traer*.
        el = scene.postit_element({"text": text, "kind": kind, "state": "abierto",
                                   "author": AUTHOR_USER, "estimate": False, "anchor": block_id,
                                   "sources": [{"kind": "bloque", "ref": f"bloque:{block_id}"}]},
                                  x, y)
        if keys:
            el["customData"]["sync"] = {"block": block_id, "keys": keys}
        b.elements = b.elements + [el]
        self.new.append(el)
        self.changed = True
        return el["id"]

    def clear_error(self, block_id, action):
        self._need(block_id)
        st = self._board.state.get(block_id) or {}
        if (st.get("error_action") or {}).get("action") != action:
            return False
        st.update(error=None, error_action=None)
        self.changed = True
        return True

    def block_type(self, block_id):
        el = self._block(block_id)
        return None if el is None else self._board.registry[el["customData"]["blockType"]]

    def block_file(self, block_id, name):
        self._need(block_id)
        b = self._board
        return b.ws.block_file(b.project_id, block_id, name)
