"""Tests de contrato del almacenamiento (docs/PLAN_PIZARRA.md §2, §10, D64-D66, D68).

Fijan lo que cualquier implementación de `pizarra.storage.Workspace` tiene que cumplir: la
local de hoy y la del servidor del futuro. Cada implementación los hereda con su
`make_workspace()` (ver test_storage_local.py). Lo que depende de tocar el disco a mano (una
carpeta copiada o renombrada desde el Explorador) va en los tests de cada implementación.

El nombre del fichero no empieza por `test`: así `unittest discover` no lo ejecuta suelto.
"""
from pizarra.storage import Conflict, InvalidName, NotFound, StorageError


class StorageContract:
    """Mezcla para un `unittest.TestCase`; la subclase define `make_workspace()` y, si
    quiere comprobar la papelera, deja en `self.trashed` lo que se mandó a ella. La mezcla va
    primero en las bases, así que no define `make_workspace()`: taparía el de la subclase."""

    def setUp(self):
        super().setUp()
        self.trashed = []
        self.ws = self.make_workspace()

    # ------------------------------------------------------------------ helpers
    def names(self, node):
        return [c.name for c in node.children]

    def find(self, node, name):
        return next(c for c in node.children if c.name == name)

    # ------------------------------------------------------------------- árbol
    def test_workspace_nuevo_tiene_id_y_el_arbol_vacio(self):
        info = self.ws.info()
        self.assertTrue(info.id)
        self.assertEqual(self.ws.tree().children, [])

    def test_carpetas_anidadas_y_proyectos_en_la_raiz(self):
        self.ws.create_folder("", "Terminales")
        self.ws.create_folder("Terminales", "Clientes")
        p = self.ws.create_project("Terminales/Clientes", "Pinza paralela")
        s = self.ws.create_project("", "Spike")
        tree = self.ws.tree()
        self.assertEqual(self.names(tree), ["Terminales", "Spike"])   # carpetas primero
        clientes = self.find(self.find(tree, "Terminales"), "Clientes")
        self.assertEqual(clientes.kind, "folder")
        self.assertEqual(clientes.path, "Terminales/Clientes")
        pinza = self.find(clientes, "Pinza paralela")
        self.assertEqual((pinza.kind, pinza.id), ("project", p.id))
        self.assertEqual(self.ws.project(s.id).path, "Spike")
        self.assertEqual(self.ws.project(p.id).folder, "Terminales/Clientes")

    def test_lo_de_dentro_de_un_proyecto_nunca_sale_como_carpeta(self):
        p = self.ws.create_project("", "Brazo")
        self.ws.save_scene(p.id, [{"id": "a", "version": 1}])
        self.ws.save_block_state(p.id, {"b": {"params": {}}})
        node = self.find(self.ws.tree(), "Brazo")
        self.assertEqual(node.kind, "project")
        self.assertEqual(node.children, [])
        with self.assertRaises(NotFound):
            self.ws.create_folder("Brazo", "Dentro")          # un proyecto no es una carpeta

    # --------------------------------------------------------- identidad (D64)
    def test_dos_proyectos_nunca_comparten_id(self):
        ids = {self.ws.create_project("", f"P{i}").id for i in range(5)}
        self.assertEqual(len(ids), 5)

    def test_renombrar_y_mover_conservan_el_id(self):
        self.ws.create_folder("", "Brazos")
        p = self.ws.create_project("", "Brazo")
        self.ws.rename_project(p.id, "Brazo pinza")
        self.ws.move_project(p.id, "Brazos")
        got = self.ws.project(p.id)
        self.assertEqual((got.name, got.path), ("Brazo pinza", "Brazos/Brazo pinza"))

    def test_renombrar_una_carpeta_no_pierde_sus_proyectos(self):
        self.ws.create_folder("", "Brazos")
        p = self.ws.create_project("Brazos", "Brazo")
        self.assertEqual(self.ws.rename_folder("Brazos", "Robots"), "Robots")
        self.assertEqual(self.ws.project(p.id).path, "Robots/Brazo")

    def test_un_id_desconocido_es_no_encontrado(self):
        with self.assertRaises(NotFound):
            self.ws.project("no-existe")

    # ----------------------------------------------- nombres y movimientos (D65)
    def test_nunca_un_nombre_que_windows_no_admite(self):
        for bad in ["", "   ", "a/b", "a\\b", "a:b", "a*", "a?", 'a"b', "a<b", "a|b",
                    "CON", "nul", "com1", "LPT9", "con.txt", "fin.", "fin. ", ".oculta",
                    "..", "x" * 300, "tab\tdentro"]:
            with self.subTest(nombre=bad):
                with self.assertRaises(InvalidName):
                    self.ws.create_project("", bad)
                with self.assertRaises(InvalidName):
                    self.ws.create_folder("", bad)
        self.assertEqual(self.ws.tree().children, [])

    def test_los_espacios_a_los_lados_se_quitan_en_vez_de_llegar_al_disco(self):
        self.assertEqual(self.ws.create_project("", "  Brazo pinza ").name, "Brazo pinza")
        self.assertEqual(self.ws.create_folder("", " Brazos "), "Brazos")

    def test_en_la_raiz_profile_y_packs_estan_reservados(self):
        for bad in ["profile", "Packs"]:
            with self.assertRaises(InvalidName):
                self.ws.create_folder("", bad)
        self.ws.create_folder("", "Brazos")
        self.ws.create_folder("Brazos", "packs")              # dentro de una carpeta, sí

    def test_nunca_se_pisa_una_carpeta_que_ya_existe(self):
        self.ws.create_folder("", "Brazos")
        p = self.ws.create_project("", "Spike")
        with self.assertRaises(Conflict):
            self.ws.create_project("", "brazos")              # sin distinguir mayúsculas
        with self.assertRaises(Conflict):
            self.ws.create_folder("", "SPIKE")
        with self.assertRaises(Conflict):
            self.ws.rename_project(p.id, "Brazos")
        self.ws.create_project("Brazos", "Spike")
        with self.assertRaises(Conflict):
            self.ws.move_project(p.id, "Brazos")
        self.assertEqual(self.ws.project(p.id).path, "Spike")

    def test_cambiar_solo_mayusculas_es_renombrar_no_un_choque(self):
        p = self.ws.create_project("", "spike")
        self.assertEqual(self.ws.rename_project(p.id, "Spike").name, "Spike")
        self.assertEqual(self.names(self.ws.tree()), ["Spike"])

    def test_mover_una_carpeta_dentro_de_si_misma_se_rechaza(self):
        self.ws.create_folder("", "A")
        self.ws.create_folder("A", "B")
        for dest in ["A", "A/B"]:
            with self.assertRaises(Conflict):
                self.ws.move_folder("A", dest)
        self.assertEqual(self.ws.move_folder("A/B", ""), "B")

    def test_nunca_se_sale_del_workspace(self):
        p = self.ws.create_project("", "Spike")
        for bad in ["..", "../fuera", "/abs", "C:/abs", "C:", "a/../..", "./a", "a//b",
                    ".oculta", "a\\b"]:
            with self.subTest(ruta=bad):
                with self.assertRaises((NotFound, InvalidName)):
                    self.ws.create_folder(bad, "X")
                with self.assertRaises((NotFound, InvalidName)):
                    self.ws.move_project(p.id, bad)

    # ------------------------------------------------------------ borrar (D66)
    def test_borrar_un_proyecto_lo_manda_a_la_papelera(self):
        p = self.ws.create_project("", "Spike")
        self.ws.trash_project(p.id)
        self.assertEqual(len(self.trashed), 1)
        self.assertEqual(self.ws.tree().children, [])
        with self.assertRaises(NotFound):
            self.ws.project(p.id)

    def test_borrar_una_carpeta_dice_que_proyectos_se_van_con_ella(self):
        self.ws.create_folder("", "A")
        self.ws.create_folder("A", "B")
        p1 = self.ws.create_project("A", "Uno")
        p2 = self.ws.create_project("A/B", "Dos")
        keep = self.ws.create_project("", "Fuera")
        self.assertEqual(set(self.ws.projects_under("A")), {p1.id, p2.id})
        self.assertEqual(set(self.ws.trash_folder("A")), {p1.id, p2.id})
        self.assertEqual(len(self.trashed), 1)
        self.assertEqual(self.names(self.ws.tree()), ["Fuera"])
        self.assertEqual(self.ws.project(keep.id).name, "Fuera")

    def test_la_raiz_del_workspace_no_se_borra_ni_se_mueve(self):
        with self.assertRaises(InvalidName):
            self.ws.trash_folder("")
        with self.assertRaises(InvalidName):
            self.ws.rename_folder("", "Otro")

    # ------------------------------------------------- contenido del proyecto
    def test_escena_estado_y_miniatura_vuelven_tal_cual(self):
        p = self.ws.create_project("", "Spike")
        self.assertEqual(self.ws.load_scene(p.id), [])
        self.assertEqual(self.ws.load_block_state(p.id), {})
        self.assertIsNone(self.ws.load_thumbnail(p.id))
        els = [{"id": "a", "version": 3, "text": "Ménsula Ø6"}]
        self.ws.save_scene(p.id, els)
        self.ws.save_block_state(p.id, {"a": {"params": {"L": 300}}})
        self.ws.save_thumbnail(p.id, b"\x89PNG...")
        self.ws.move_project(p.id, "")                        # no-op: misma carpeta
        self.assertEqual(self.ws.load_scene(p.id), els)
        self.assertEqual(self.ws.load_block_state(p.id), {"a": {"params": {"L": 300}}})
        self.assertEqual(self.ws.load_thumbnail(p.id), b"\x89PNG...")

    def test_las_propuestas_vuelven_tal_cual_y_sin_ninguna_es_una_lista_vacia(self):
        pid = self.ws.create_project("", "Con propuestas").id
        self.assertEqual(self.ws.load_proposals(pid), [])
        props = [{"id": "p1", "target": "e1", "change": {"text": "ñandú"}, "state": "pendiente"}]
        self.ws.save_proposals(pid, props)
        self.assertEqual(self.ws.load_proposals(pid), props)

    def test_el_lock_de_paquetes_vuelve_tal_cual_y_sin_el_es_vacio(self):
        # P25: sin lock (un proyecto de antes de FF 10.1) es como no haber usado ninguno
        pid = self.ws.create_project("", "Con paquetes").id
        self.assertEqual(self.ws.load_pack_lock(pid), {})
        lock = {"robotica": {"version": "0.1.0", "digest": "ab" * 32}}
        self.ws.save_pack_lock(pid, lock)
        self.assertEqual(self.ws.load_pack_lock(pid), lock)

    def test_la_conversacion_del_agente_se_anade_en_orden_y_vuelve_tal_cual(self):
        # D164: el chat se añade (nunca se reescribe); sessions/usage, un JSON cada uno
        pid = self.ws.create_project("", "Con chat").id
        self.assertEqual((self.ws.load_agent_chat(pid), self.ws.load_agent_file(pid, "usage")),
                         ([], {}))
        self.ws.append_agent_chat(pid, [{"kind": "user", "text": "ñandú"}])
        self.ws.append_agent_chat(pid, [{"kind": "text", "text": "a\nb"}, {"kind": "done"}])
        self.assertEqual([e["kind"] for e in self.ws.load_agent_chat(pid)],
                         ["user", "text", "done"])
        self.assertEqual(self.ws.load_agent_chat(pid)[1]["text"], "a\nb")
        self.ws.save_agent_file(pid, "sessions", {"chat": {"session_id": "s1"}})
        self.assertEqual(self.ws.load_agent_file(pid, "sessions"), {"chat": {"session_id": "s1"}})
        with self.assertRaises(InvalidName):
            self.ws.load_agent_file(pid, "../board/scene")

    def test_los_mensajes_de_cada_hilo_van_aparte_y_se_borran_solos(self):
        # D165: el historial de un hilo se lee sin cargar los demás ni el chat
        pid = self.ws.create_project("", "Con hilos").id
        self.ws.append_agent_thread(pid, "h_a", [{"kind": "user", "text": "uno"}])
        self.ws.append_agent_thread(pid, "h_b", [{"kind": "user", "text": "otro"}])
        self.ws.append_agent_thread(pid, "h_a", [{"kind": "text", "text": "dos"}])
        self.assertEqual([e["text"] for e in self.ws.load_agent_thread(pid, "h_a")],
                         ["uno", "dos"])
        self.assertEqual(self.ws.load_agent_chat(pid), [])
        self.ws.delete_agent_thread(pid, "h_a")
        self.ws.delete_agent_thread(pid, "h_a")             # ya no está: no pasa nada
        self.assertEqual(self.ws.load_agent_thread(pid, "h_a"), [])
        self.assertEqual(len(self.ws.load_agent_thread(pid, "h_b")), 1)
        for malo in ("../chat", "a/b", "", "h.1", None):
            with self.assertRaises(InvalidName, msg=malo):
                self.ws.append_agent_thread(pid, malo, [{"kind": "user"}])

    def test_los_ajustes_del_agente_del_proyecto_vuelven_y_no_le_cambian_el_id(self):
        pid = self.ws.create_project("", "Con ajustes").id
        self.assertEqual(self.ws.load_project_agent_settings(pid), {})
        self.ws.save_project_agent_settings(pid, {"tope_usd": 8.0, "excluir_adjuntos": True})
        self.assertEqual(self.ws.load_project_agent_settings(pid),
                         {"tope_usd": 8.0, "excluir_adjuntos": True})
        self.assertEqual(self.ws.project(pid).id, pid)

    # ---------------------------------------------------------------- versiones (D76)
    def test_una_version_guarda_escena_estado_y_miniatura_y_vuelve_tal_cual(self):
        pid = self.ws.create_project("", "Con versiones").id
        self.assertEqual(self.ws.list_versions(pid), [])
        els, st = [{"id": "a", "version": 3, "text": "ñandú"}], {"b1": {"params": {"L": 300}}}
        v = self.ws.save_version(pid, "Primer encaje", els, st, b"\x89PNG fake")
        self.assertEqual((v["name"], v["auto"]), ("Primer encaje", False))
        got = self.ws.load_version(pid, v["id"])
        self.assertEqual((got["elements"], got["blocks"]), (els, st))
        self.assertEqual(self.ws.load_version_thumbnail(pid, v["id"]), b"\x89PNG fake")
        self.assertEqual([x["id"] for x in self.ws.list_versions(pid)], [v["id"]])

    def test_dos_versiones_nunca_se_pisan_aunque_tengan_el_mismo_nombre(self):
        pid = self.ws.create_project("", "Gemelas").id
        a = self.ws.save_version(pid, "Igual", [{"id": "a"}], {}, None)
        b = self.ws.save_version(pid, "Igual", [{"id": "b"}], {}, None, auto=True)
        self.assertNotEqual(a["id"], b["id"])
        self.assertEqual(self.ws.load_version(pid, a["id"])["elements"], [{"id": "a"}])
        self.assertEqual(self.ws.load_version(pid, b["id"])["elements"], [{"id": "b"}])
        self.assertEqual([v["auto"] for v in self.ws.list_versions(pid)], [True, False])  # la más nueva primero
        self.assertIsNone(self.ws.load_version_thumbnail(pid, a["id"]))

    def test_el_nombre_de_una_version_pasa_la_misma_validacion_que_un_proyecto(self):
        pid = self.ws.create_project("", "Nombres").id
        for bad in ("", "a/b", "CON", "x" * 300, ".oculta"):
            with self.assertRaises(InvalidName):
                self.ws.save_version(pid, bad, [], {}, None)
        self.assertEqual(self.ws.list_versions(pid), [])

    def test_renombrar_y_mandar_a_la_papelera_una_version(self):
        pid = self.ws.create_project("", "Renombrar").id
        v = self.ws.save_version(pid, "Vieja", [], {}, None)
        self.assertEqual(self.ws.rename_version(pid, v["id"], "Nueva")["name"], "Nueva")
        self.assertEqual(self.ws.list_versions(pid)[0]["name"], "Nueva")
        self.ws.trash_version(pid, v["id"])
        self.assertEqual(self.ws.list_versions(pid), [])
        with self.assertRaises(NotFound):
            self.ws.load_version(pid, v["id"])

    def test_una_version_que_no_existe_o_fuera_de_su_carpeta_es_no_encontrada(self):
        pid = self.ws.create_project("", "Fuera").id
        for bad in ("no-existe", "../scene.json", "..", "a/b"):
            with self.assertRaises(StorageError):
                self.ws.load_version(pid, bad)

    # ------------------------------------------- archivos de salida de los bloques (D93)
    def _run_files(self, pid, bid, files):
        """Una ejecución que escribe `files` ({nombre: texto}) y termina bien."""
        d = self.ws.block_scratch(pid, bid)
        for name, text in files.items():
            (d / name).parent.mkdir(parents=True, exist_ok=True)
            (d / name).write_text(text, encoding="utf-8")
        self.ws.commit_block_files(pid, bid, d)

    def read(self, pid, bid, name):
        return self.ws.block_file(pid, bid, name).read_text(encoding="utf-8")

    def test_los_archivos_de_un_bloque_solo_aparecen_al_terminar_y_sustituyen_a_los_de_antes(self):
        pid = self.ws.create_project("", "Archivos").id
        self._run_files(pid, "b1", {"arm.toml": "v1", "viejo.txt": "x"})
        d = self.ws.block_scratch(pid, "b1")
        (d / "arm.toml").write_text("v2", encoding="utf-8")
        self.assertEqual(self.read(pid, "b1", "arm.toml"), "v1", "a medias nadie lo ve")
        self.ws.commit_block_files(pid, "b1", d)
        self.assertEqual(self.read(pid, "b1", "arm.toml"), "v2")
        with self.assertRaises(NotFound):
            self.ws.block_file(pid, "b1", "viejo.txt")

    def test_una_ejecucion_tirada_deja_los_archivos_como_estaban(self):
        pid = self.ws.create_project("", "Tirada").id
        self._run_files(pid, "b1", {"arm.toml": "v1"})
        d = self.ws.block_scratch(pid, "b1")
        (d / "arm.toml").write_text("a medias", encoding="utf-8")
        self.ws.discard_block_scratch(d)
        self.assertEqual(self.read(pid, "b1", "arm.toml"), "v1")
        self.assertFalse(d.exists())

    def test_un_archivo_de_un_bloque_nunca_sale_de_su_carpeta(self):
        pid = self.ws.create_project("", "Contenido").id
        self._run_files(pid, "b1", {"sub/informe.html": "<p>"})
        self._run_files(pid, "b2", {"otro.txt": "x"})
        self.assertEqual(self.read(pid, "b1", "sub/informe.html"), "<p>")
        for bad in ("../b2/otro.txt", "../state.json", "..", "", "C:/Windows/win.ini",
                    "/etc/passwd"):
            with self.assertRaises(StorageError, msg=bad):
                self.ws.block_file(pid, "b1", bad)
        for bad in ("../b2", "a/b", "", ".run-x"):
            with self.assertRaises(InvalidName, msg=bad):
                self.ws.block_scratch(pid, bad)
        with self.assertRaises(InvalidName):
            self.ws.discard_block_scratch(self.ws.block_file(pid, "b2", "otro.txt").parent)

    def test_una_version_se_lleva_los_archivos_de_los_bloques_y_los_devuelve(self):
        pid = self.ws.create_project("", "Versionado").id
        self._run_files(pid, "b1", {"arm.toml": "v1"})
        v = self.ws.save_version(pid, "Con brazo", [], {}, None)
        self._run_files(pid, "b1", {"arm.toml": "v2"})
        self._run_files(pid, "b2", {"nuevo.txt": "x"})
        self.ws.restore_block_files(pid, v["id"])
        self.assertEqual(self.read(pid, "b1", "arm.toml"), "v1")
        with self.assertRaises(NotFound):
            self.ws.block_file(pid, "b2", "nuevo.txt")
        self.ws.clear_block_files(pid, "b1")
        with self.assertRaises(NotFound):
            self.ws.block_file(pid, "b1", "arm.toml")

    # --------------------------------------------- archivos de la pizarra (D84, D140)
    def test_la_misma_imagen_guardada_dos_veces_es_un_solo_archivo(self):
        pid = self.ws.create_project("", "Fotos").id
        png = b"\x89PNG\r\n\x1a\n" + b"pixeles"
        a = self.ws.save_board_file(pid, png, "png")
        self.assertEqual(self.ws.save_board_file(pid, png, "png"), a)
        self.assertRegex(a, r"^[0-9a-f]{64}\.png$")
        self.assertEqual(self.ws.board_file(pid, a).read_bytes(), png)
        self.assertEqual(len(list(self.ws.board_file(pid, a).parent.iterdir())), 1)
        self.assertNotEqual(self.ws.save_board_file(pid, png + b"!", "png"), a)

    def test_un_archivo_de_la_pizarra_solo_se_nombra_por_su_hash(self):
        pid = self.ws.create_project("", "Fotos").id
        for bad in ("../project.toml", "scene.json", "AB" * 32 + ".png", "ab" * 32 + ".exe",
                    "ab" * 32 + ".png/../../x", None):
            with self.assertRaises(InvalidName, msg=bad):
                self.ws.board_file(pid, bad)
        with self.assertRaises(InvalidName):
            self.ws.save_board_file(pid, b"x", "exe")
        with self.assertRaises(NotFound):
            self.ws.board_file(pid, "ab" * 32 + ".png")

    def test_el_respaldo_de_una_escena_se_guarda_una_vez_y_nunca_se_pisa(self):
        p = self.ws.create_project("", "Viejo")
        self.assertIsNone(self.ws.load_scene_backup(p.id, "r2"))
        self.assertTrue(self.ws.backup_scene_once(p.id, "r2", [{"id": "a", "version": 1}]))
        self.assertFalse(self.ws.backup_scene_once(p.id, "r2", [{"id": "b", "version": 9}]))
        self.assertEqual(self.ws.load_scene_backup(p.id, "r2"), [{"id": "a", "version": 1}])
        with self.assertRaises(StorageError):
            self.ws.backup_scene_once(p.id, "../fuera", [])

    def test_el_contenido_sigue_al_proyecto_al_moverlo(self):
        self.ws.create_folder("", "Brazos")
        p = self.ws.create_project("", "Brazo")
        self.ws.save_scene(p.id, [{"id": "a", "version": 1}])
        self.ws.move_project(p.id, "Brazos")
        self.assertEqual(self.ws.load_scene(p.id), [{"id": "a", "version": 1}])
