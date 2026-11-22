"""Archivos de OneDrive y SharePoint en la pizarra (docs/PLAN_M365.md §4, §5, §9: M6-M9).

Reglas: traer nunca escribe fuera de `<proyecto>/microsoft365/`, aunque el nombre traiga `..`
o `/`; un nombre que ya está da `_n` y nunca pisa; el mismo `item_id` dos veces no duplica la
tarjeta ni descarga otra vez. En el sondeo, el mismo `cTag` nunca descarga; un `cTag` nuevo con
la copia sin tocar descarga; con la copia cambiada aquí da `conflicto` y nunca descarga encima,
salvo *Traer la de la nube*, que manda la local a la papelera. Toda subida lleva
`conflictBehavior=rename`; más de 4 MB va por sesión en trozos múltiplos de 320 KiB.

Ejecutar desde app/backend:  python -m unittest tests.test_m365_files -v
"""
import json
import tempfile
import unittest
from pathlib import Path

from pizarra import m365_files, scene
from pizarra.m365_files import (AL_DIA, CONFLICTO, DESCARGAR, bring, refresh, refresh_action,
                                safe_name, upload)
from pizarra.validation import ValidationError

from tests.helpers import new_board


class FakeGraph:
    """Una unidad con archivos en memoria: `items[(drive, id)] = (metadatos, bytes)`."""

    def __init__(self):
        self.items = {}
        self.calls = []

    def add(self, item_id, name, data, ctag="c1", drive="d1", folder=False):
        meta = {"id": item_id, "name": name, "size": len(data), "cTag": ctag,
                "webUrl": f"https://onedrive.live.com/{item_id}",
                "parentReference": {"driveId": drive}}
        if folder:
            meta["folder"] = {"childCount": 0}
        else:
            meta["file"] = {}
        self.items[(drive, item_id)] = (meta, data)

    def _key(self, path):
        parts = path.split("?")[0].split("/")
        return parts[2], parts[4]

    def get(self, path, **kw):
        self.calls.append(("GET", path))
        return self.items[self._key(path)][0]

    def download(self, path, **kw):
        self.calls.append(("DOWNLOAD", path))
        return self.items[self._key(path)][1]

    def put(self, path, data, content_type="", **kw):
        self.calls.append(("PUT", path, len(data)))
        return {"id": "nuevo"}

    def post(self, path, payload, **kw):
        self.calls.append(("POST", path, payload))
        return {"uploadUrl": "https://subida.example/sesion"}

    def request(self, method, url, body=None, auth=True, headers=None, **kw):
        self.calls.append(("CHUNK", url, auth, headers["Content-Range"], len(body)))

        class R:
            content = b'{"id": "grande"}'

            def json(self):
                return {"id": "grande"}
        return R()

    def downloads(self):
        return [c for c in self.calls if c[0] == "DOWNLOAD"]


class Nombres(unittest.TestCase):
    def test_sin_carpetas_ni_caracteres_prohibidos(self):
        self.assertEqual(safe_name("../../etc/passwd"), "_.._etc_passwd")
        self.assertEqual(safe_name('a<b>c:"d|e?f*.xlsx'), "a_b_c__d_e_f_.xlsx")
        self.assertNotIn("/", safe_name("x/y\\z.txt"))

    def test_reservados_vacios_y_largos(self):
        self.assertEqual(safe_name("CON.txt"), "CON_.txt")
        self.assertEqual(safe_name("   ...  "), "archivo")
        long = safe_name("a" * 300 + ".xlsx")
        self.assertEqual(len(long), m365_files.NAME_MAX)
        self.assertTrue(long.endswith(".xlsx"))


class Traer(unittest.TestCase):
    def setUp(self):
        self.board = new_board()
        self.g = FakeGraph()
        self.folder = Path(self.board.dir) / m365_files.FOLDER

    def test_trae_a_microsoft365_con_su_m365(self):
        self.g.add("i1", "Cálculo.xlsx", b"datos")
        el, new = bring(self.board, self.g, "d1", "i1", 0, 0)
        self.assertTrue(new)
        path = self.board.card_path(el)
        self.assertEqual(path.parent.resolve(), self.folder.resolve())
        self.assertEqual(path.read_bytes(), b"datos")
        m = el["customData"]["m365"]
        self.assertEqual((m["drive_id"], m["item_id"], m["ctag"]), ("d1", "i1", "c1"))
        self.assertEqual(m["sha256"], m365_files.sha256(b"datos"))

    def test_nombre_malicioso_no_sale_de_la_carpeta(self):
        self.g.add("i1", "..\\..\\fuera.txt", b"x")
        el, _ = bring(self.board, self.g, "d1", "i1", 0, 0)
        self.assertEqual(self.board.card_path(el).parent.resolve(), self.folder.resolve())
        self.assertEqual(list(Path(self.board.dir).parent.glob("fuera.txt")), [])

    def test_nombre_cogido_da_n_y_no_pisa(self):
        self.folder.mkdir(parents=True)
        (self.folder / "plano.pdf").write_bytes(b"mio")
        self.g.add("i1", "plano.pdf", b"nube")
        el, _ = bring(self.board, self.g, "d1", "i1", 0, 0)
        self.assertEqual(self.board.card_path(el).name, "plano_1.pdf")
        self.assertEqual((self.folder / "plano.pdf").read_bytes(), b"mio")

    def test_el_mismo_item_no_se_duplica_ni_se_descarga_otra_vez(self):
        self.g.add("i1", "a.txt", b"x")
        first, _ = bring(self.board, self.g, "d1", "i1", 0, 0)
        again, new = bring(self.board, self.g, "d1", "i1", 0, 0)
        self.assertFalse(new)
        self.assertEqual(again["id"], first["id"])
        self.assertEqual(len(self.g.downloads()), 1)

    def test_una_tarjeta_nueva_nunca_cae_encima_de_otra(self):
        # E2E de FF 7.5: el panel pide el centro de la vista, y lo segundo que se traía pasados
        # 5 s caía encima de lo primero (M14: donde se pide o en un hueco).
        self.g.add("i1", "a.xlsx", b"x")
        self.g.add("i2", "b.xlsx", b"y")
        first, _ = bring(self.board, self.g, "d1", "i1", 100, 100)
        second, _ = bring(self.board, self.g, "d1", "i2", 100, 100)
        self.assertEqual((first["x"], first["y"]), (100, 100))
        ax0, ay0, ax1, ay1 = scene.bbox(first)
        bx0, by0, bx1, by1 = scene.bbox(second)
        self.assertTrue(bx0 >= ax1 or bx1 <= ax0 or by0 >= ay1 or by1 <= ay0)
        self.assertEqual(second["x"], 100)          # debajo, en la misma columna: a la vista
        self.assertGreater(second["y"], 100)

    def test_una_carpeta_no_se_trae(self):
        self.g.add("f1", "Carpeta", b"", folder=True)
        with self.assertRaises(ValidationError):
            bring(self.board, self.g, "d1", "f1", 0, 0)


class Refrescar(unittest.TestCase):
    def test_tabla(self):
        self.assertEqual(refresh_action("c1", "c1", "h", "h"), AL_DIA)
        self.assertEqual(refresh_action("c1", "c1", "h", "otra"), AL_DIA)
        self.assertEqual(refresh_action("c1", None, "h", "h"), AL_DIA)
        self.assertEqual(refresh_action("c1", "c2", "h", "h"), DESCARGAR)
        self.assertEqual(refresh_action("c1", "c2", "h", None), DESCARGAR)
        self.assertEqual(refresh_action("c1", "c2", "h", "otra"), CONFLICTO)

    def setUp(self):
        self.board = new_board()
        self.trashed = []
        self.board.ws._trash_fn = lambda p: (self.trashed.append(p), Path(p).unlink())
        self.g = FakeGraph()
        self.g.add("i1", "a.txt", b"v1")
        self.el, _ = bring(self.board, self.g, "d1", "i1", 0, 0)
        self.path = self.board.card_path(self.el)

    def _card(self):
        return next(e for e in self.board.elements if e["id"] == self.el["id"])

    def test_mismo_ctag_nunca_descarga(self):
        self.assertEqual(refresh(self.board, self.g, self._card()), AL_DIA)
        self.assertEqual(len(self.g.downloads()), 1)

    def test_ctag_nuevo_y_sin_tocar_descarga(self):
        self.g.add("i1", "a.txt", b"v2", ctag="c2")
        self.assertEqual(refresh(self.board, self.g, self._card()), "descargada")
        self.assertEqual(self.path.read_bytes(), b"v2")
        self.assertEqual(self._card()["customData"]["m365"]["ctag"], "c2")
        self.assertEqual(refresh(self.board, self.g, self._card()), AL_DIA)

    def test_cambiada_aqui_y_en_la_nube_es_conflicto_y_no_pisa(self):
        self.path.write_bytes(b"mio")
        self.g.add("i1", "a.txt", b"v2", ctag="c2")
        self.assertEqual(refresh(self.board, self.g, self._card()), CONFLICTO)
        self.assertEqual(self.path.read_bytes(), b"mio")
        self.assertEqual(len(self.g.downloads()), 1)

    def test_traer_la_de_la_nube_manda_la_local_a_la_papelera(self):
        self.path.write_bytes(b"mio")
        self.g.add("i1", "a.txt", b"v2", ctag="c2")
        self.assertEqual(refresh(self.board, self.g, self._card(), force=True), "descargada")
        self.assertEqual(self.path.read_bytes(), b"v2")
        self.assertEqual(self.trashed, [str(self.path)])


class Subir(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_pequeno_put_con_rename(self):
        p = self.dir / "informe.docx"
        p.write_bytes(b"x" * 10)
        g = FakeGraph()
        upload(g, p, "d1", "carpeta")
        method, path, size = g.calls[0]
        self.assertEqual(method, "PUT")
        self.assertIn("conflictBehavior=rename", path)
        self.assertTrue(path.startswith("/drives/d1/items/carpeta:/informe.docx:/content"))

    def test_grande_por_sesion_en_trozos_de_320k_y_sin_auth(self):
        p = self.dir / "modelo.step"
        total = m365_files.SIMPLE_UPLOAD_MAX + m365_files.CHUNK + 123
        p.write_bytes(b"y" * total)
        g = FakeGraph()
        self.assertEqual(upload(g, p), {"id": "grande"})
        post = g.calls[0]
        self.assertEqual(post[0], "POST")
        self.assertEqual(post[2]["item"]["@microsoft.graph.conflictBehavior"], "rename")
        chunks = [c for c in g.calls if c[0] == "CHUNK"]
        self.assertEqual(sum(c[4] for c in chunks), total)
        for c in chunks[:-1]:
            self.assertEqual(c[4] % (320 * 1024), 0)
        self.assertTrue(all(c[2] is False for c in chunks))
        self.assertTrue(chunks[-1][3].endswith(f"/{total}"))


if __name__ == "__main__":
    unittest.main()
