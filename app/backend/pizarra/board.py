"""Estado de la pizarra de un proyecto: escena + estado de los bloques.

Se lee y se guarda a través del almacenamiento (`pizarra.storage`, D68), nunca con rutas:
    escena                elementos de Excalidraw
    estado de los bloques por bloque: params, last_hash, outputs, outputs_hash, error
    propuestas            de los agentes, pendientes y resueltas (D75, `pizarra.proposals`)

Las tarjetas de archivo y de carpeta (D131) guardan una ruta del disco del usuario: lo que se
sabe de ellas (`sources`) lo da el sondeo (`probe`, D134), que no se guarda.
"""
import copy
import os
import threading
import uuid
from pathlib import Path

from pizarra import connectors as connectors_mod, diff as diff_mod, files, graph, ink, packs, pasted, proposals as props, scene, validation
from pizarra import i18n
from pizarra.config import AUTHOR_USER
from pizarra import blocks as blocks_mod
from pizarra.pack_host import HostError


class Board:
    def __init__(self, workspace, project_id, registry=None, connectors=None):
        self.ws = workspace
        self.project_id = project_id
        # el de la app si no se da otro: se mira ahora, `blocks.configure` lo puede recargar
        self.registry = blocks_mod.REGISTRY if registry is None else registry
        # Conectores disponibles (D35, D106): sin el que pide un bloque, sale no_disponible. Sin
        # `connectors` (la app) se pregunta cada vez: Fusion se abre y se cierra con la pizarra
        # abierta. Con ellos (tests), fijos.
        self._connectors = None if connectors is None else frozenset(connectors)
        self.elements = workspace.load_scene(project_id)
        self.state = workspace.load_block_state(project_id)
        self.proposals = workspace.load_proposals(project_id)
        self.pack_lock = workspace.load_pack_lock(project_id)    # P25: lo de la última ejecución
        # Ejecución en curso (`execution.Job`), una por proyecto (D89). No se guarda.
        self.job = None
        # Sondeo de las tarjetas (D134). Nada de esto se guarda: al abrir, todo sale «sin
        # comprobar» hasta el primer sondeo, nunca con un hash de otra sesión.
        self.prober = files.Prober()
        self.sources = {}          # {tarjeta: FileState}
        self.param_files = {}      # {bloque: {parámetro: hash}}: parámetros que son un archivo
        self.copy_notices = {}     # {carpeta: aviso} de la última copia que falló (D109)
        self._probe_lock = threading.Lock()   # el sondeo corre en un hilo; antes de ejecutar, otro
        # Post-its de R2 a tarjetas (D71). La escena de antes se guarda aparte una sola vez,
        # antes de escribir la migrada.
        migrated, changed = scene.migrate_postits(self.elements)
        if changed:
            workspace.backup_scene_once(project_id, "r2", self.elements)
            self.elements = migrated
            workspace.save_scene(project_id, self.elements)
        # Bloques sin el relleno ni el trazo de Excalidraw (D77). Solo colores: sin copia aparte.
        self.elements, changed = scene.migrate_blocks(self.elements)
        if changed:
            workspace.save_scene(project_id, self.elements)
        # Bloques con el id de antes de su paquete (P59: `cad.modelo_fusion` → `fusion.modelo`),
        # antes que las flechas: estas leen los puertos del tipo.
        if hasattr(self.registry, "renamed"):
            self.elements, changed = scene.migrate_kinds(self.elements, self.registry.renamed())
            if changed:
                workspace.save_scene(project_id, self.elements)
        # Flechas y líneas que Excalidraw no puede pintar (OP 4.1): con una, la pizarra en blanco.
        self.elements, changed = scene.repair_lines(self.elements)
        if changed:
            workspace.save_scene(project_id, self.elements)
        # Flechas del spike sin puertos: el único par posible queda escrito en la flecha (D88).
        self.elements, changed = scene.migrate_connections(self.elements, self.registry)
        if changed:
            workspace.save_scene(project_id, self.elements)
        # Salidas del spike (campos sueltos, sin puerto): no se pueden leer con el contrato de
        # FF 4.4. Se descartan y el bloque vuelve a «nunca»; sus parámetros se quedan.
        for st in self.state.values():
            if st.get("outputs") is not None and not graph.is_port_outputs(st["outputs"]):
                st.update(outputs=None, outputs_hash=None, last_hash=None)

    def use_registry(self, registry):
        """El registro nuevo tras instalar o desinstalar un paquete (§7): un bloque con el id
        de antes de un paquete recién instalado se migra ahora (P59), como al abrir."""
        self.registry = registry
        if hasattr(registry, "renamed"):
            self.elements, changed = scene.migrate_kinds(self.elements, registry.renamed())
            if changed:
                self.ws.save_scene(self.project_id, self.elements)

    @property
    def connectors(self):
        return connectors_mod.available(self.registry) if self._connectors is None else self._connectors

    def default_params(self, kind):
        return {k: p.default for k, p in self.registry[kind].params.items()}

    @property
    def dir(self):
        """Carpeta de trabajo del agente (su `cwd`). Se pregunta cada vez: el proyecto se
        puede renombrar o mover con la pizarra abierta."""
        return self.ws.workdir(self.project_id)

    # ------------------------------------------------------------ persistencia
    def save(self):
        self.ws.save_scene(self.project_id, self.elements)
        self.ws.save_block_state(self.project_id, self.state)
        self.ws.save_proposals(self.project_id, self.proposals)

    # --------------------------------------------- paquetes del proyecto (P13, P25)
    def _packs_in_scene(self):
        """{paquete: {bloque: tipo}} de todos los bloques de la escena, también los de un
        paquete que no está cargado."""
        used = {}
        for bid, el in graph.blocks_in(self.elements).items():
            kind = el["customData"].get("blockType")
            used.setdefault(packs.pack_id_of(kind), {})[bid] = kind
        return used

    def packs_check(self):
        """Lo que el proyecto usa y no cuadra con lo cargado (§3):
        `missing`: paquetes que no están (sus bloques salen *paquete no instalado*, con todo
        intacto); `changed`: los que tienen otra versión que la del lock (sus bloques salen
        desactualizados por su `pack_version`)."""
        lock = self.pack_lock
        missing, changed = [], []
        for pid, kinds in sorted(self._packs_in_scene().items()):
            info = self.registry.pack(pid) if hasattr(self.registry, "pack") else None
            locked = (lock.get(pid) or {}).get("version") or ""
            # un tipo que está en el registro es de un paquete cargado (o de un test que lo
            # registra a mano): no falta nada
            if info is None and not any(k in self.registry for k in kinds.values()):
                missing.append({"id": pid, "version": locked, "blocks": sorted(kinds)})
            elif info is not None and locked and locked != info.version:
                changed.append({"id": pid, "locked": locked, "installed": info.version})
        return {"missing": missing, "changed": changed}

    def write_pack_lock(self):
        """Reescribe `board/packs.lock` con los paquetes que usan los bloques de la escena. El
        de un paquete que ahora falta se queda como estaba: el proyecto sigue diciendo con qué
        versión se hizo."""
        if not hasattr(self.registry, "pack"):
            return
        old = self.pack_lock
        lock = {}
        for pid in self._packs_in_scene():
            info = self.registry.pack(pid)
            if info is not None:
                lock[pid] = {"version": info.version, "digest": info.digest}
            elif pid in old:
                lock[pid] = old[pid]
        if lock != old:
            self.ws.save_pack_lock(self.project_id, lock)
            self.pack_lock = lock

    # ------------------------------------------------------------------ lectura
    def statuses(self):
        return self.explain()[0]

    def explain(self):
        """(estados, motivos) de los bloques, con lo último que dio el sondeo."""
        return graph.explain(self.elements, self.registry, self.state, self.connectors,
                             self.sources, self.param_files)

    # ------------------------------------------------------------- archivos (D131)
    def card(self, card_id):
        """La tarjeta de archivo o de carpeta viva `card_id`, o ValidationError."""
        el = graph.sources_in(self.elements).get(card_id)
        if el is None:
            raise validation.ValidationError(i18n.t("tarjeta.no_existe", id=repr(card_id)))
        return el

    def card_path(self, el):
        """Ruta absoluta de lo que guarda una tarjeta (D138)."""
        return files.resolve(el["customData"]["path"], self.ws.root)

    def readable_file(self, card_id, rel=None):
        """Ruta del archivo que el agente puede leer con `leer_archivo` (R5): el de una tarjeta
        de archivo o, en una carpeta, uno de lo marcado (`rel`, su ruta relativa, D142). Nunca
        otro: una ruta que no es de la pizarra no se puede pedir. ValidationError si no."""
        el = self.card(card_id)
        base = self.card_path(el)
        if el["customData"]["kind"] == "file":
            if not base.is_file():
                raise validation.ValidationError(f"{base.name}: no encontrado en {base.parent}")
            return base
        rel = str(rel or "").replace("\\", "/").strip("/")
        if not rel:
            raise validation.ValidationError(
                "es una carpeta: pide sin `file` la lista de lo que entra y lee uno de ellos")
        if rel not in self.folder_files(card_id):
            raise validation.ValidationError(
                f"{rel!r} no es de lo marcado en la carpeta {base.name}: solo se lee lo que "
                "el ingeniero ha dejado entrar")
        return base / rel

    def folder_files(self, card_id):
        """Rutas relativas de lo marcado de la carpeta `card_id` (D136, D142), en orden."""
        el = self.card(card_id)
        base = self.card_path(el)
        if el["customData"]["kind"] != "folder":
            raise validation.ValidationError(f"{card_id!r} no es una carpeta")
        if not base.is_dir():
            raise validation.ValidationError(f"{base.name}: carpeta no encontrada en {base.parent}")
        content = files.Content.from_card(el["customData"].get("content"))
        return [rel for rel, _ in files.marked(base, content)]

    def link_url(self, card_id):
        """La URL del enlace `card_id` (D137), tal como está en la escena, si se puede abrir en
        el navegador; si no, ValidationError. Nunca una URL que mande la interfaz."""
        el = self._element(card_id)
        cd = (el or {}).get("customData") or {}
        if el is None or el.get("type") != "embeddable" or cd.get("kind") != "link":
            raise validation.ValidationError(i18n.t("tarjeta.enlace_no_existe", id=repr(card_id)))
        url = pasted.safe_url(cd.get("url"))
        if url is None:
            raise validation.ValidationError(i18n.t("tarjeta.enlace_no_http"))
        return url

    def _file_params(self):
        """`{(bloque, parámetro): ruta}` de los parámetros que son un archivo (su `widget`
        empieza por `archivo`, como el del *STEP de referencia*) y tienen ruta (D133)."""
        out = {}
        for bid, el in graph.blocks_in(self.elements, self.registry).items():
            btype = self.registry[el["customData"]["blockType"]]
            params = (self.state.get(bid) or {}).get("params") or {}
            for name, spec in btype.params.items():
                value = str(params.get(name) or "").strip()
                if (getattr(spec, "widget", "") or "").startswith("archivo") and value:
                    out[(bid, name)] = files.resolve(value, self.ws.root)
        return out

    def probe(self, fresh=False):
        """Sondea las tarjetas y los parámetros que son un archivo (D134): solo vuelve a leer lo
        que ha cambiado de fecha o de tamaño, salvo con `fresh` (antes de ejecutar). Devuelve si
        cambió algo de lo que se enseña. Bloquea mientras lee: se llama desde un hilo."""
        with self._probe_lock:
            cards = graph.sources_in(self.elements)
            sources = {}
            for cid, el in cards.items():
                cd, path = el["customData"], self.card_path(el)
                if cd["kind"] == "file":
                    sources[cid] = self.prober.probe_file(path, fresh)
                else:
                    sources[cid] = self.prober.probe_folder(
                        path, files.Content.from_card(cd.get("content")), fresh,
                        allow_big=bool(cd.get("allowBig")))
            wanted = self._file_params()
            param_files = {}
            for (bid, name), path in wanted.items():
                param_files.setdefault(bid, {})[name] = self.prober.probe_file(path, fresh).hash
            self.prober.forget([self.card_path(el) for el in cards.values()] + list(wanted.values()))
            changed = sources != self.sources or param_files != self.param_files
            self.sources, self.param_files = sources, param_files
            return changed

    def sources_view(self):
        """Lo que la interfaz enseña de cada tarjeta: si se puede usar y, si no, por qué
        («No encontrado», D139), el tamaño, cuántos archivos entran de una carpeta, si espera a
        que se confirme el hash (D136) y el aviso de una copia que falló (D109). `type`, el de
        su salida (`archivo.<ext>` o `carpeta`); en una carpeta, `total` (cuántos archivos tiene)
        y `peek`, los tipos de los tres primeros que entran (los papeles que asoman, D139)."""
        out = {}
        for cid, el in graph.sources_in(self.elements).items():
            st = self.sources.get(cid)
            out[cid] = {"checked": st is not None, "ok": bool(st and st.hash),
                        "reason": st.reason if st else None,
                        "type": next(iter(graph.source_type(el).outputs.values())),
                        "hash": st.hash if st else None,
                        "size": st.size if st else 0, "mtime_ns": st.mtime_ns if st else 0,
                        "files": len(st.files) if st else 0, "total": st.total if st else 0,
                        "peek": [files.port_type(f) for f in (st.files if st else ())[:3]],
                        "big": bool(st and st.big),
                        "notice": self.copy_notices.get(cid)}
        return out

    def add_cards(self, paths, x=0, y=0, author=AUTHOR_USER):
        """Una tarjeta por ruta (del diálogo o arrastradas desde el explorador), en columna
        desde (x, y). Una ruta que no existe se rechaza; nunca se copia nada al proyecto (D59)."""
        new, gap = [], 16
        for p in paths:
            p = Path(p)
            if not p.exists():
                raise validation.ValidationError(i18n.t("tarjeta.ruta_no_encontrada", ruta=p))
            kind = "folder" if p.is_dir() else "file"
            el = scene.card_element(kind, files.stored_path(p, self.ws.root), x, y, author=author)
            y += el["height"] + gap
            new.append(el)
        self.elements = self.elements + new
        return new

    def card_for(self, path):
        """La tarjeta viva que ya apunta a `path` (la misma ruta; en Windows, sin distinguir
        mayúsculas), o None. Añadir otra vez lo que ya está la reutiliza (O17)."""
        def key(p):
            return os.path.normcase(str(Path(p).resolve()))
        want = key(path)
        return next((e for e in graph.sources_in(self.elements).values()
                     if key(files.resolve(e["customData"]["path"], self.ws.root)) == want), None)

    def relocate_card(self, card_id, path):
        """«Buscar de nuevo» o «Buscar otro archivo…» (D138): la misma tarjeta (el mismo id, así
        que las conexiones siguen) con otra ruta, del mismo tipo que la que tenía."""
        el = self.card(card_id)
        p = Path(path)
        kind = el["customData"]["kind"]
        if kind == "folder" and not p.is_dir() or kind == "file" and not p.is_file():
            raise validation.ValidationError(
                i18n.t("tarjeta.no_es_carpeta" if kind == "folder" else "tarjeta.no_es_archivo", ruta=p))
        cd = {**el["customData"], "path": files.stored_path(p, self.ws.root)}
        new = scene.bumped({**el, "customData": cd})
        self.elements = [new if e["id"] == card_id else e for e in self.elements]
        return new

    def confirm_big(self, card_id):
        """El usuario confirma calcular el hash de una carpeta de más de 500 MB (D136): queda en
        la tarjeta, no hay que volver a confirmar."""
        el = self.card(card_id)
        if el["customData"]["kind"] != "folder":
            raise validation.ValidationError(i18n.t("tarjeta.confirmar_solo_carpeta"))
        new = scene.bumped({**el, "customData": {**el["customData"], "allowBig": True}})
        self.elements = [new if e["id"] == card_id else e for e in self.elements]
        return new

    def save_to(self, block_id, folder, author=AUTHOR_USER):
        """*Guardar también en…* (D109, D139): la tarjeta de la carpeta, a la derecha del
        bloque, y la flecha de sus salidas puesta. La flecha es la única fuente de a dónde va
        cada cosa. Si la carpeta ya está en la pizarra, se usa esa tarjeta, y si el bloque ya
        llega a ella, esa flecha: una segunda copiaría cada archivo dos veces. Si esa flecha
        solo llevaba una salida, pasa a llevarlas todas."""
        block = graph.blocks_in(self.elements, self.registry).get(block_id)
        if block is None:
            raise validation.ValidationError(i18n.t("bloque.no_existe", id=repr(block_id)))
        folder = Path(folder)
        if not folder.is_dir():
            raise validation.ValidationError(i18n.t("tarjeta.no_es_carpeta", ruta=folder))
        stored = files.stored_path(folder, self.ws.root)
        card = next((e for e in graph.sources_in(self.elements).values()
                     if e["customData"]["kind"] == "folder" and e["customData"]["path"] == stored),
                    None)
        fresh = card is None
        if not fresh:
            old = next((a for a in sorted(self.elements, key=lambda e: e["id"])
                        if a.get("type") == "arrow" and not a.get("isDeleted")
                        and graph.arrow_ends(a, {block_id: block, card["id"]: card})
                        == (block_id, card["id"])), None)
            if old is not None:
                if graph.arrow_ports(old)[0] is None:
                    return [card, old]
                old = scene.bumped({**old, "customData": {**old["customData"], "from": None}})
                self.elements = [old if e["id"] == old["id"] else e for e in self.elements]
                return [card, old]
        if fresh:
            w, h = scene.FOLDER_SIZE
            x, y = self._free_spot(w, h, block_id, gap=120)   # sitio para la flecha y su etiqueta
            card = scene.card_element("folder", stored, x, y, author=author)
        arrow = scene.connection_element(block, card, None, None, author=author)

        def bound(el):
            return {**el, "boundElements": (el.get("boundElements") or [])
                    + [{"id": arrow["id"], "type": "arrow"}]}
        new = [scene.bumped(bound(block)), bound(card) if fresh else scene.bumped(bound(card)), arrow]
        ids = {e["id"] for e in new}
        self.elements = [e for e in self.elements if e["id"] not in ids] + new
        return new

    def copy_outputs(self, block_id):
        """Tras una ejecución del bloque que termina bien: copia sus archivos de salida a las
        carpetas de sus flechas (D109). Por archivo, el nombre en `overwrite` de la flecha pisa
        el que haya; el resto va al primer `_n` libre. Una copia que falla deja aviso en la
        tarjeta de la carpeta y nunca marca error en el bloque. Devuelve las copias."""
        _, copies, _ = graph.connections(self.elements, self.registry)
        cards = graph.sources_in(self.elements)
        arrows = {e["id"]: e for e in self.elements if e.get("type") == "arrow"}
        outputs = (self.state.get(block_id) or {}).get("outputs") or {}
        done = []
        for folder_id, links in copies.items():
            errors = []
            for src, port, arrow_id in links:
                if src != block_id:
                    continue
                names = sorted({f["file"] for p, payload in outputs.items()
                                if port is None or p == port
                                for f in payload.values() if isinstance(f, dict) and "file" in f})
                try:
                    paths = [self.ws.block_file(self.project_id, block_id, n) for n in names]
                except Exception as exc:            # noqa: BLE001 nunca un error del bloque
                    errors.append(i18n.t("tarjeta.salidas_no_encontradas", motivo=exc))
                    continue
                overwrite = (arrows.get(arrow_id, {}).get("customData") or {}).get("overwrite") or ()
                for r in files.copy_outputs(paths, self.card_path(cards[folder_id]), overwrite):
                    done.append(r)
                    if r.error:
                        errors.append(f"{r.source.name}: {r.error}")
            if any(src == block_id for src, _, _ in links):
                if errors:
                    self.copy_notices[folder_id] = "; ".join(errors)
                else:
                    self.copy_notices.pop(folder_id, None)
        return done

    def blocks_view(self):
        """Estado de cada bloque para la interfaz. Mientras hay una ejecución, el bloque en
        curso sale `ejecutando` y lo que espera, `en_cola` (no se guarda), y `run` dice cuál va
        y su progreso; sin ejecución, `run` es None."""
        edges, problems = graph.build(self.elements, self.registry)
        sts, reasons = self.explain()
        run = self.job.view() if self.job is not None else None
        if run is not None:
            sts = {**sts, **{b: "en_cola" for b in run["queued"]}}
            if run["block"] in sts:
                sts[run["block"]] = "ejecutando"
        blocks = {}
        for bid, el in graph.blocks_in(self.elements, self.registry).items():
            st = self.state.get(bid) or {}
            kind = el["customData"]["blockType"]
            blocks[bid] = {"type": kind, "status": sts[bid], "reason": reasons.get(bid),
                           "params": st.get("params"), "outputs": st.get("outputs"),
                           "error": st.get("error"), "error_action": st.get("error_action"),
                           "inputs": {ip: {"block": src, "port": op}
                                      for ip, (src, op) in edges.get(bid, {}).items()}}
            # Traer (D116): hay algo enviado aunque el último intento diera error y el bloque
            # se quedara sin salidas. Lo de dentro del registro lo lee su conector (la tabla de
            # un Modelo de Fusion tras un error, `fusion.table`, P60).
            if self.registry[kind].pull is not None:
                blocks[bid]["synced"] = self.ws.sync_file(self.project_id, bid).is_file()
        return {"blocks": blocks, "problems": problems, "run": run, "sources": self.sources_view(),
                "packs": self.packs_check()}

    def summary(self):
        out = scene.summary(self.elements, self.statuses(), self.state)
        # las tarjetas, para que el agente sepa qué puede leer con `leer_archivo` (R36)
        out["files"] = [{"id": cid, "kind": "carpeta" if el["customData"]["kind"] == "folder"
                         else "archivo", "name": Path(el["customData"]["path"]).name,
                         "type": next(iter(graph.source_type(el).outputs.values()))}
                        for cid, el in graph.sources_in(self.elements).items()]
        out["proposals"] = [{k: v[k] for k in ("id", "target", "change", "reason", "stale")}
                            for v in self.proposals_view()]
        out["tinta"] = ink.describe(self.elements, self.registry)    # a qué apunta (D193)
        return out

    def _element(self, eid, live=True):
        e = next((e for e in self.elements if e["id"] == eid), None)
        return None if e is None or (live and e.get("isDeleted")) else e

    def proposals_view(self):
        """Las pendientes que se pueden enseñar (su elemento existe), con lo que hay ahora en
        sus campos (`current`) y si está desfasada (`stale`: ya no es lo que había)."""
        out = []
        for p in self.proposals:
            el = self._element(p["target"])
            if p["state"] != "pendiente" or el is None:
                continue
            now = props.content(el, self.state, p["change"])
            out.append({**p, "current": now, "stale": now != p["base"]})
        return out

    # ---------------------------------------------------------- cambios del usuario
    def apply_client_elements(self, incoming):
        """Fusiona un envío del cliente. Devuelve `(ganados, reescritos)`: lo que ganó, para
        las demás ventanas (D69), y lo que el backend corrigió, que vuelve también a la que lo
        mandó: una tarjeta pegada (D85), un autor, origen o estado que el cliente no puede
        poner (D72, D73) o un anclaje no válido (D74)."""
        won = scene.accepted(self.elements, incoming)
        before = {e["id"]: e for e in self.elements}
        self.elements = scene.merge(self.elements, incoming)
        rewritten = {}
        now = scene.now_iso()
        by_id = {e["id"]: e for e in self.elements if not e.get("isDeleted")}
        for e in won:
            prev = before.get(e["id"])
            fixed, params = scene.adopt_pasted_card(e)
            # una flecha sin puntos (de la API, del agente) dejaría la pizarra en blanco (OP 4.1)
            line = scene.repair_line(fixed or e, by_id)
            if line is not None:
                fixed = line
            # la tinta, siempre con opacity 0: la que se ve va en customData.ink (D188)
            inked = ink.normalized(fixed or e)
            if inked is not (fixed or e):
                fixed = scene.bumped(inked) if fixed is None else inked
            cand = fixed or e
            cd = validation.client_authorship(prev, cand, now)
            if cd is not None:
                cand = {**cand, "customData": cd}
            cd = validation.client_anchor(prev, cand, self.elements) or cd
            if cd is not None:
                fixed = {**fixed, "customData": cd} if fixed else scene.bumped({**e, "customData": cd})
            if fixed is None:
                continue
            rewritten[e["id"]] = fixed
            kind = (fixed.get("customData") or {}).get("blockType")
            # Los parámetros de la copia solo valen para un bloque nuevo: nunca pisan los suyos.
            if params is not None and kind in self.registry and e["id"] not in self.state:
                allowed = self.registry[kind].params
                self.state[e["id"]] = {"params": {**self.default_params(kind),
                                                  **{k: v for k, v in params.items() if k in allowed}}}
        if rewritten:
            self.elements = [rewritten.get(e["id"], e) for e in self.elements]
            won = [rewritten.get(e["id"], e) for e in won]
        for bid, el in graph.blocks_in(self.elements, self.registry).items():
            st = self.state.setdefault(bid, {})
            st.setdefault("params", self.default_params(el["customData"]["blockType"]))
        return won, list(rewritten.values())

    def set_params(self, block_id, params):
        block = graph.blocks_in(self.elements, self.registry).get(block_id)
        if block is None:
            raise validation.ValidationError(i18n.t("bloque.no_existe", id=repr(block_id)))
        if not isinstance(params, dict):
            raise validation.ValidationError(i18n.t("bloque.parametros_no_objeto"))
        st = self.state.setdefault(block_id, {})
        kind = block["customData"]["blockType"]
        allowed = self.registry[kind].params
        params = {k: v for k, v in params.items() if k in allowed}
        for k, v in params.items():            # todo o nada: un valor malo no deja los otros
            validation.check_param(k, allowed[k], v)
        merged = dict(st.get("params") or self.default_params(kind))
        merged.update(params)
        st["params"] = merged

    def preview(self, block_id, draft=None):
        """La vista previa de un bloque que la tiene (PLAN_TERMINALES T26) con sus parámetros
        más los que se están editando (`draft`), sin guardar ni ejecutar nada.
        Las entradas son lo último que dio cada bloque de delante; una sin resultado no entra
        (el panel lo dice)."""
        return self.preview_job(block_id, draft)()

    def preview_job(self, block_id, draft=None):
        """La vista previa de `preview` en dos tiempos: lee ya el bloque y sus entradas y
        devuelve la función que la calcula, que se puede llamar en un hilo sin tocar la
        pizarra (la propuesta de un agente, D177). `ValidationError` si no tiene."""
        kind, params, inputs = self._live(block_id, draft)
        btype = self.registry[kind]
        if btype.preview is None:
            raise validation.ValidationError(i18n.t("bloque.sin_vista_previa", bloque=btype.title))
        host = self.registry.host
        env = self.run_env(block_id)    # con la carpeta de la librería del workspace (V15)

        def job():
            try:                        # en el trabajador, en la app (PLAN_PAQUETES P89)
                return host.preview(kind, params, inputs, env)
            except (ValueError, TypeError, KeyError) as exc:
                raise validation.ValidationError(str(exc)) from None
        return job

    def _live(self, block_id, draft=None):
        """`(tipo, parámetros, entradas)` de un bloque tal y como está: sus parámetros (más los
        de `draft` que sean suyos) y lo último que dio cada bloque de delante (una entrada sin
        resultado no entra). Copias: quien las use no toca el estado."""
        block = graph.blocks_in(self.elements, self.registry).get(block_id)
        if block is None:
            raise validation.ValidationError(i18n.t("bloque.no_existe", id=repr(block_id)))
        kind = block["customData"]["blockType"]
        allowed = self.registry[kind].params
        params = {**self.default_params(kind), **((self.state.get(block_id) or {}).get("params") or {}),
                  **{k: v for k, v in (draft or {}).items() if k in allowed}}
        edges, _ = graph.build(self.elements, self.registry)
        inputs = {}
        for ip, (src, op) in edges.get(block_id, {}).items():
            out = (self.state.get(src) or {}).get("outputs") or {}
            if op in out:
                inputs[ip] = copy.deepcopy(out[op])
        return kind, copy.deepcopy(params), inputs

    def action(self, block_id, name, args=None, effects=None):
        """Una acción de paquete (`pack.action`, docs/PLAN_PAQUETES.md §5, P40) pedida desde la
        interfaz propia del bloque `block_id`. Solo llega a las acciones del **paquete del
        bloque** y, si el bloque declara un conector (P41), a las del paquete del conector: la
        interfaz de un paquete nunca llama a otro. No guarda nada por su cuenta: lo que cambie
        en la pizarra va por la API de P39 (`ctx.set_params`, `ctx.add_postit`…, con la
        validación de siempre), y `effects`, si se pasa un dict, recibe `changed` y `new` (los
        elementos nuevos) para que el servidor guarde y avise. Devuelve lo que dé la acción,
        que tiene que poder pasar a JSON; cualquier fallo es un `ValidationError` con el
        motivo."""
        from pizarra.pack_api import BoardAPI
        kind, params, inputs = self._live(block_id)
        own = packs.pack_id_of(kind)
        allowed = {own} | ({self.registry[kind].connector} if self.registry[kind].connector else set())
        if not isinstance(name, str) or packs.pack_id_of(name) not in allowed:
            raise validation.ValidationError(
                i18n.t("bloque.accion_ajena", accion=repr(name), paquete=own))
        if name not in self.registry.actions:
            raise validation.ValidationError(i18n.t("bloque.accion_no_existe", paquete=packs.pack_id_of(name),
                                                    accion=repr(name)))
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise validation.ValidationError(i18n.t("bloque.argumentos_no_objeto"))
        api = BoardAPI(self)
        try:                            # en el trabajador, en la app (PLAN_PAQUETES P89, P91)
            return self.registry.host.action(name, params, inputs, copy.deepcopy(args),
                                             self.run_env(block_id), board=api,
                                             block_id=block_id)
        except HostError as exc:        # el motivo del paquete, tal cual
            raise validation.ValidationError(str(exc)) from None
        finally:
            if effects is not None:     # lo hecho antes de un fallo también hay que guardarlo
                effects.update(changed=api.changed, new=list(api.new))

    def run_env(self, block_id):
        """Lo que un bloque necesita del entorno al ejecutarse (plan §7): el nombre del
        proyecto, su registro de sincronización, la configuración de los conectores y la
        carpeta de la librería del workspace (`library_dir`, PLAN_V020 V15; "" si el
        almacenamiento no tiene carpeta local)."""
        lib = self.ws.library_dir()
        return {"project_name": self.ws.project(self.project_id).name,
                "sync_file": str(self.ws.sync_file(self.project_id, block_id)),
                "connectors": connectors_mod.config(self.registry),
                "library_dir": str(lib) if lib is not None else ""}

    def run(self, block_id=None, options=None):
        """Ejecuta el bloque y, antes, lo que tenga delante que no esté al día; sin bloque, todo
        lo que no está al día. En este mismo proceso: el servidor usa `execution.run_job` con
        un proceso aparte (D92). Devuelve el resumen (`Job.summary`).

        Solo se llama por una acción explícita del usuario: nada se ejecuta solo (D14).
        """
        from pizarra import execution
        self.probe(fresh=True)            # el hash de los archivos, leído de nuevo (D134)
        return execution.run_inline(execution.Job.plan(self, block_id, options))

    def add_template(self, template_id, x=None, y=None, author=AUTHOR_USER, near=None):
        """Pone una plantilla del paquete (D91): sus bloques, con los parámetros por defecto, y
        sus conexiones con los puertos. Va donde se pide si cabe ahí, si no junto a `near` (un
        id) y, si tampoco, en un sitio libre: nunca encima de lo que ya hay. Devuelve los
        elementos nuevos."""
        t = self.registry.templates.get(template_id)
        if t is None:
            raise validation.ValidationError(i18n.t("plantilla.no_existe", id=repr(template_id)))
        self._need_element(near)
        W, H = 280, 220                              # tamaño de un bloque nuevo (block_element)
        w = max(b[2] for b in t.blocks) + W
        h = max(b[3] for b in t.blocks) + H
        ox, oy = self._free_spot(w, h, near, prefer=(x, y))
        made = {b[0]: scene.block_element(b[1], ox + b[2], oy + b[3], author=author) for b in t.blocks}
        preset = {b[0]: b[4] for b in t.blocks if len(b) == 5}       # parámetros de la plantilla
        arrows = []
        for src, frm, dst, to in t.links:
            a = scene.connection_element(made[src], made[dst], frm, to, author=author)
            arrows.append(a)
            for el in (made[src], made[dst]):
                el["boundElements"] = (el["boundElements"] or []) + [{"id": a["id"], "type": "arrow"}]
        for key, el in made.items():
            kind = el["customData"]["blockType"]
            self.state[el["id"]] = {"params": {**self.default_params(kind), **preset.get(key, {})}}
        new = list(made.values()) + arrows
        self.elements = self.elements + new
        return new

    def _need_element(self, eid):
        if eid is not None and self._element(eid) is None:
            raise validation.ValidationError(
                f"no hay ningún elemento {eid!r}: usa el `id` que devuelve leer_pizarra")

    def add_block(self, kind, params=None, near=None, author=AUTHOR_USER):
        """Un bloque nuevo de un tipo cargado (D170), en un sitio libre junto a `near` (un id) o
        a la derecha de todo: nunca encima de nada. Parámetros por defecto y los de `params`,
        todo o nada (`set_params`). Devuelve el elemento."""
        if kind not in self.registry:
            raise validation.ValidationError(f"tipo de bloque desconocido: {kind!r}")
        self._need_element(near)
        el = scene.block_element(kind, 0, 0, author=author)
        el["x"], el["y"] = self._free_spot(el["width"], el["height"], near)
        before = self.elements
        self.elements = before + [el]
        self.state[el["id"]] = {"params": self.default_params(kind)}
        try:
            if params:
                self.set_params(el["id"], params)
        except validation.ValidationError:
            self.elements = before
            del self.state[el["id"]]
            raise
        return el

    def connect(self, src, frm, dst, to, author=AUTHOR_USER):
        """Une la salida `frm` de `src` con la entrada `to` de `dst` (D88) con las mismas reglas
        que una flecha de la interfaz (`graph.connections`): si la flecha no sería una conexión
        válida, o quitaría el sitio a otra (una entrada ya ocupada), `ValidationError` con el
        motivo y nada cambia. Sin un puerto, el grafo elige el único posible y se escribe en la
        flecha. Devuelve los elementos nuevos o cambiados (la flecha y los dos extremos)."""
        nodes = {**graph.blocks_in(self.elements, self.registry), **graph.sources_in(self.elements)}
        for nid in (src, dst):
            if nid not in nodes:
                raise validation.ValidationError(
                    f"no hay ningún bloque ni tarjeta {nid!r}: usa el `id` de leer_pizarra")
        arrow = scene.connection_element(nodes[src], nodes[dst], frm, to, author=author)
        old_edges, _, old_problems = graph.connections(self.elements, self.registry)
        edges, _, problems = graph.connections(self.elements + [arrow], self.registry)
        known = {p["arrow"] for p in old_problems}
        why = next((p["reason"] for p in problems if p["arrow"] == arrow["id"]), None) \
            or next((p["reason"] for p in problems if p["arrow"] not in known), None)
        if why:
            raise validation.ValidationError(f"no se conecta: {why}")
        for ip, link in edges.get(dst, {}).items():
            if link[0] == src and old_edges.get(dst, {}).get(ip) != link:
                arrow["customData"].update({"from": link[1], "to": ip})
        ends = [scene.bumped({**nodes[n], "boundElements": (nodes[n].get("boundElements") or [])
                              + [{"id": arrow["id"], "type": "arrow"}]}) for n in (src, dst)]
        by_id = {e["id"]: e for e in ends}
        self.elements = [by_id.get(e["id"], e) for e in self.elements] + [arrow]
        return [arrow, *ends]

    def user_add_postit(self, kind, x, y):
        """Post-it nuevo del usuario, vacío y abierto, donde lo pide la interfaz (D71)."""
        if kind not in validation.POSTIT_KINDS:
            raise validation.ValidationError(
                f"tipo de post-it desconocido: {kind!r} (válidos: {validation.POSTIT_KINDS})")
        el = scene.postit_element({"text": "", "kind": kind, "state": "abierto",
                                   "author": AUTHOR_USER, "sources": [], "estimate": False,
                                   "anchor": None}, x, y)
        self.elements = self.elements + [el]
        return el

    # ------------------------------------------------------------------- versiones
    def list_versions(self):
        return self.ws.list_versions(self.project_id)

    def save_version(self, name, auto=False):
        """Copia de la escena, el estado de los bloques y la miniatura (D76). Nunca cambia la
        pizarra."""
        return self.ws.save_version(self.project_id, name, self.elements, self.state,
                                    self.ws.load_thumbnail(self.project_id), auto=auto)

    def restore_version(self, version_id):
        """Guarda antes la pizarra actual como «antes de restaurar <nombre>» (así restaurar se
        deshace restaurando esa) y deja escena y estado como en la versión. Lo restaurado sube
        de versión por encima de lo actual y lo que no estaba en ella queda borrado: una ventana
        que vaya por detrás no lo pisa ni lo resucita (D69). Devuelve la versión automática."""
        if self.job is not None:
            raise validation.ValidationError(i18n.t("version.restaurar_en_ejecucion"))
        v = self.ws.load_version(self.project_id, version_id)
        label = v["info"]["name"]
        label = label if len(label) <= 60 else label[:59] + "…"
        # Restaurar una automática es deshacer una restauración: sin nombres anidados.
        name = i18n.t("version.antes_de_deshacer") if v["info"]["auto"] \
            else i18n.t("version.antes_de_restaurar", nombre=label)
        auto = self.save_version(name, auto=True)
        now = {e["id"]: e for e in self.elements}
        restored = []
        for e in v["elements"]:
            top = max(e.get("version", 0), now.get(e["id"], {}).get("version", 0))
            restored.append(scene.bumped({**e, "version": top}))
        kept = {e["id"] for e in restored}
        gone = [scene.bumped({**e, "isDeleted": True}) for e in self.elements
                if e["id"] not in kept and not e.get("isDeleted")]
        self.elements = restored + gone
        self.state = v["blocks"]
        self.ws.restore_block_files(self.project_id, version_id)
        self.save()
        return auto

    def compare(self, a, b="now"):
        """Cambios de `a` a `b` (ids de versión, o "now" para la pizarra de ahora)."""
        def side(x):
            if x == "now":
                return self.elements, self.state
            v = self.ws.load_version(self.project_id, x)
            return v["elements"], v["blocks"]
        (ea, sa), (eb, sb) = side(a), side(b)
        return diff_mod.diff(ea, eb, sa, sb)

    # ------------------------------------------------------------------ propuestas
    def agent_propose(self, agent, target, change, reason, sources=None, estimate=False):
        """Un agente quiere cambiar contenido o borrar (D20, D75). Sobre algo suyo lo edita
        directamente (`("aplicado", elemento)`); sobre lo demás deja una propuesta pendiente
        (`("propuesta", propuesta)`) y no toca el elemento."""
        el = self._element(target)
        if el is None:
            raise validation.ValidationError(
                f"no hay ningún elemento {target!r}: usa el `id` que devuelve leer_pizarra")
        change = props.check_change(el, change, self.registry)
        if not isinstance(reason, str) or not reason.strip():
            raise validation.ValidationError("una propuesta lleva siempre su motivo (`reason`)")
        sources = sources or []
        if not isinstance(sources, list):
            raise validation.ValidationError("`sources` tiene que ser una lista")
        for src in sources:
            validation.check_source(src)
        if "text" in change and validation.has_figures(change["text"]) and not sources \
                and not estimate:
            raise validation.ValidationError(
                "el texto propuesto contiene cifras y no lleva fuente: cita un bloque, una "
                "ficha o un dato vivo, o márcalo como estimación sin verificar")
        self._check_block_sources(sources)
        if validation.element_author(el) == agent:
            new = self._apply_change(el, change, sources, estimate)
            return "aplicado", new
        if any(p["target"] == target and p["state"] == "pendiente" for p in self.proposals):
            raise validation.ValidationError(
                f"ya hay una propuesta pendiente sobre {target!r}: espera a que el ingeniero "
                "la acepte o la rechace")
        p = {"id": uuid.uuid4().hex[:12], "author": agent, "target": target,
             "base_version": el.get("version"), "base": props.content(el, self.state, change),
             "change": change, "reason": reason.strip(), "sources": sources,
             "estimate": bool(estimate), "state": "pendiente", "created": scene.now_iso()}
        self.proposals = self.proposals + [p]
        return "propuesta", p

    def _apply_change(self, el, change, sources=(), estimate=False):
        """Aplica un cambio de contenido; devuelve el elemento cambiado (o None si solo
        cambian parámetros, que van al estado del bloque). Uno de archivo (D176) pasa la
        tarjeta al archivo nuevo, como «Buscar otro archivo…»: las conexiones siguen."""
        if "file" in change:
            return self.relocate_card(el["id"], files.resolve(change["file"]["nuevo"], self.ws.root))
        if "params" in change:
            self.set_params(el["id"], change["params"])
            if set(change) == {"params"}:
                return None
        new = props.apply(el, change)
        cd = new["customData"]
        if cd.get("kind") == "postit" and (sources or estimate):
            cd["sources"] = list(cd.get("sources") or []) + list(sources)
            cd["estimate"] = bool(cd.get("estimate")) or bool(estimate)
        new = scene.bumped(new)
        self.elements = [new if e["id"] == el["id"] else e for e in self.elements]
        return new

    def _pending(self, pid):
        p = next((p for p in self.proposals if p["id"] == pid), None)
        if p is None or p["state"] != "pendiente":
            raise validation.ValidationError(i18n.t("propuesta.no_pendiente"))
        return p

    def accept_proposal(self, pid, seen):
        """Aplica la propuesta si lo que hay es lo que el usuario vio (`seen`, el «antes» que
        se le enseñó). Si el elemento ha cambiado, no se aplica: queda desfasada y se vuelve a
        enseñar contra lo actual. Devuelve los elementos cambiados."""
        p = self._pending(pid)
        el = self._element(p["target"])
        if el is None:
            raise validation.ValidationError(i18n.t("propuesta.elemento_borrado"))
        if props.content(el, self.state, p["change"]) != seen:
            raise validation.ValidationError(i18n.t("propuesta.desfasada"))
        new = self._apply_change(el, p["change"], p.get("sources") or [], p.get("estimate"))
        self._resolve(p, "aceptada")
        return [new] if new else []

    def reject_proposal(self, pid):
        """Una de archivo (D176) manda a la papelera el archivo nuevo que escribió el agente, y
        solo ese: nunca el de la tarjeta. Si no se puede, sigue pendiente."""
        p = self._pending(pid)
        if "file" in p["change"]:
            new = files.resolve(p["change"]["file"]["nuevo"], self.ws.root).resolve()
            el = self._element(p["target"])
            if new.is_file() and (el is None or self.card_path(el).resolve() != new):
                self.ws.trash_file(new)
        self._resolve(p, "rechazada")

    def _resolve(self, p, state):
        self.proposals = [{**q, "state": state, "resolved": scene.now_iso()} if q is p else q
                          for q in self.proposals]

    # ----------------------------------------------------------- escrituras de agente
    def agent_add_postit(self, postit, x=None, y=None, animation=None):
        """`animation`: el HTML de la animación que va encima del texto (D143, D175). Se guarda
        en `board/files/<sha256>.html` solo si el post-it pasa todas sus reglas (el texto sigue
        necesitando sus fuentes: la animación nunca lo es, D19), y el post-it la nombra en
        `customData.animation` (`{file, width, height}`, como la imagen de D140)."""
        p = validation.validate_postit(postit)
        self._check_block_sources(p["sources"])
        if p.get("anchor") and not validation.anchor_ok(None, p["anchor"], self.elements):
            raise validation.ValidationError(
                f"no hay ningún elemento {p['anchor']!r} al que anclar el post-it: usa el `id` "
                "que devuelve leer_pizarra")
        html = validation.check_animation(animation) if animation is not None else None
        aw, ah = scene.ANIMATION_SIZE
        h = scene.postit_height(p["text"]) + (ah if html is not None else 0)
        x, y = self._free_spot(scene.POSTIT_WIDTH, h, p.get("anchor"), prefer=(x, y))
        el = scene.postit_element(p, x, y)
        if html is not None:
            name = self.ws.save_board_file(self.project_id, html, pasted.ANIMATION_EXT)
            el = {**el, "height": h,
                  "customData": {**el["customData"], "animation": {"file": name, "width": aw,
                                                                   "height": ah}}}
        new = [el]
        self.elements = self.elements + new
        return new

    def agent_add_ink(self, agent, target, marca, color=None):
        """La marca de tinta del agente sobre el elemento `target` (`marcar`, D194): suya,
        anclada al objetivo y con los puntos que da `ink.mark_element`."""
        el = self._element(target) if isinstance(target, str) else None
        if el is None or not ink.is_target(el):
            raise validation.ValidationError(
                f"no hay ningún elemento {target!r} que marcar: usa el `id` de un bloque, "
                "post-it, tarjeta, texto o forma que devuelve leer_pizarra")
        new = [ink.mark_element(el, marca, self.elements, agent, color)]
        self.elements = self.elements + new
        return new

    def agent_remove_ink(self, agent, eid):
        """Quita una marca de tinta del propio agente (`quitar_marca`, D194); nunca una del
        usuario (`check_agent_may_edit`) ni algo que no sea tinta."""
        el = self._element(eid) if isinstance(eid, str) else None
        if el is None or not ink.is_ink(el):
            raise validation.ValidationError(
                f"no hay ninguna marca de tinta {eid!r}: usa el `id` de `tinta` de leer_pizarra")
        validation.check_agent_may_edit(agent, el)
        gone = scene.bumped({**el, "isDeleted": True})
        self.elements = [gone if e["id"] == eid else e for e in self.elements]
        return [gone]

    def _check_block_sources(self, sources):
        """Una fuente de bloque (o la entrada de un cálculo del agente) tiene que ser un bloque
        que existe y ya tiene salidas; una de archivo, una tarjeta de la pizarra (R36)."""
        cards = graph.sources_in(self.elements)
        for src in sources:
            if src["kind"] == "archivo" and src["ref"].split(":", 1)[-1] not in cards:
                raise validation.ValidationError(
                    f"la fuente {src['ref']!r} no es ninguna tarjeta de archivo de la pizarra: "
                    "usa 'archivo:<id>' con el id que devuelve leer_pizarra")
        blocks = graph.blocks_in(self.elements, self.registry)
        refs = [r for src in sources
                for r in ([src["ref"]] if src["kind"] == "bloque"
                          else src.get("inputs", []) if src["kind"] == "calculo" else [])]
        for ref in refs:
            bid = ref.split(":", 1)[-1]
            if bid not in blocks:
                raise validation.ValidationError(
                    f"la fuente {ref!r} no es ningún bloque de la pizarra: usa el `cite` "
                    "del bloque que devuelve leer_pizarra")
            if not (self.state.get(bid) or {}).get("outputs"):
                raise validation.ValidationError(
                    f"el bloque {ref!r} no tiene resultados: no puede ser fuente de una "
                    "cifra hasta que se ejecute")

    def agent_update_element(self, agent, element):
        existing = next((e for e in self.elements if e["id"] == element["id"]), None)
        validation.check_agent_may_edit(agent, existing)
        validation.check_agent_keeps_state(existing, element)
        element = dict(element)
        element["customData"] = {**(element.get("customData") or {}), "author": agent}
        element["version"] = (existing or {}).get("version", 0) + 1
        self.elements = scene.merge(self.elements, [element])
        return element

    def _free_spot(self, w, h, anchor=None, gap=40, prefer=(None, None)):
        """Sitio libre para un post-it nuevo del agente, de tamaño w × h.

        Nunca tapa un elemento existente (bloques, formas, textos sueltos, trazos y líneas con
        su caja real). Prueba, por orden: la posición pedida, a la derecha y debajo del elemento
        anclado, y si nada cabe baja por una columna a la derecha de todo lo que no es del agente
        hasta encontrar hueco.
        """
        live = [e for e in self.elements
                if not e.get("isDeleted") and "x" in e and not e.get("containerId")]
        if not live:
            return prefer if None not in prefer else (0, 0)
        boxes = [scene.bbox(e) for e in live if e.get("type") != "arrow"]
        pad = gap / 2

        def free(x, y):
            return all(x + w + pad <= x0 or x1 + pad <= x or y + h + pad <= y0 or y1 + pad <= y
                       for x0, y0, x1, y1 in boxes)

        if None not in prefer and free(*prefer):
            return prefer
        target = next((e for e in live if e["id"] == anchor), None)
        if target is not None:
            right = (target["x"] + target.get("width", 0) + gap, target["y"])
            below = (target["x"], target["y"] + target.get("height", 0) + gap)
            for x, y in (right, below):
                if free(x, y):
                    return x, y
        design = [e for e in live
                  if not validation.element_author(e).startswith("agent:")] or live
        x = max(e["x"] + e.get("width", 0) for e in design) + gap
        y = min(e["y"] for e in design)
        while not free(x, y):
            y += 10
        return x, y

