"""Imágenes y enlaces pegados (docs/PLAN_PIZARRA.md §3, §10, D84, D137, D140).

Una imagen se reconoce por sus bytes, nunca por el tipo que declara la petición; un enlace solo
se abre si es http o https y con la URL que hay en la escena. La foto suelta se ancla como un
post-it, y una copia pegada de una foto o un enlace recibe su propio enlace interno. Que la
imagen pegada siga al reabrir y se guarde una vez, por HTTP: test_server.py. Qué texto pegado
es una URL, el título por defecto y pegar sobre un post-it: frontend/src/paste.test.ts.
Ejecutar desde app/backend:  python -m unittest discover -s tests -t .
"""
import unittest

from pizarra import pasted, scene, validation
from tests.helpers import new_board, reopen

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def element(kind, eid, **cd):
    link = scene.CARD_LINKS[kind] + eid
    return {"id": eid, "type": "embeddable", "x": 0, "y": 0, "width": 200, "height": 40,
            "version": 1, "link": link, "customData": {"kind": kind, **cd}}


class ImagenPorSusBytes(unittest.TestCase):
    def test_png_jpeg_gif_webp_y_bmp_se_reconocen(self):
        cases = {PNG: "png", b"\xff\xd8\xff\xe0" + b"0" * 8: "jpg", b"GIF89a" + b"0" * 8: "gif",
                 b"GIF87a" + b"0" * 8: "gif", b"RIFF\x10\x00\x00\x00WEBPVP8 ": "webp",
                 b"BM" + b"0" * 8: "bmp"}
        for data, ext in cases.items():
            self.assertEqual(pasted.image_ext(data), ext, data[:8])

    def test_lo_que_no_es_una_imagen_nunca_pasa_por_una(self):
        for data in (b"", b"<svg xmlns='http://www.w3.org/2000/svg'/>", b"%PDF-1.4",
                     b"\x89PNG\r\n\x1a\n", b"RIFF\x10\x00\x00\x00WAVEfmt ", b"MZ\x90\x00"):
            self.assertIsNone(pasted.image_ext(data), data[:8])


class UrlQueSeAbre(unittest.TestCase):
    def test_http_y_https_con_dominio(self):
        for url in ("https://docs.google.com/document/d/1/edit", "http://localhost:8000/x",
                    "  https://harmonicdrive.de  "):
            self.assertEqual(pasted.safe_url(url), url.strip())

    def test_nunca_otro_esquema_ni_algo_sin_dominio(self):
        for url in ("javascript:alert(1)", "file:///C:/Windows/notepad.exe", "C:\\datos\\a.pdf",
                    "ms-settings:privacy", "https://", "https://a b.com", "", None, 42,
                    "ftp://servidor/archivo"):
            self.assertIsNone(pasted.safe_url(url), url)


class AbrirUnEnlace(unittest.TestCase):
    def setUp(self):
        self.b = new_board()

    def test_la_url_sale_de_la_escena(self):
        self.b.apply_client_elements([element("link", "l1", url="https://docs.google.com/x",
                                              title="Requisitos")])
        self.assertEqual(self.b.link_url("l1"), "https://docs.google.com/x")

    def test_un_enlace_con_otro_esquema_nunca_se_abre(self):
        self.b.apply_client_elements([element("link", "l1", url="file:///C:/Windows/notepad.exe")])
        with self.assertRaises(validation.ValidationError):
            self.b.link_url("l1")

    def test_solo_un_enlace_vivo(self):
        self.b.apply_client_elements([element("image", "f1", image={"file": "x"}),
                                      {**element("link", "l2", url="https://a.com"),
                                       "isDeleted": True}])
        for eid in ("f1", "l2", "no-existe"):
            with self.assertRaises(validation.ValidationError, msg=eid):
                self.b.link_url(eid)


class FotoSuelta(unittest.TestCase):
    def setUp(self):
        self.b = new_board()
        self.p = self.b.user_add_postit("nota", 0, 0)
        self.f = element("image", "f1", image={"file": "ab" * 32 + ".png"}, anchor=None)
        self.b.apply_client_elements([self.f])

    def anchor_to(self, el, target):
        cur = next(e for e in self.b.elements if e["id"] == el["id"])
        return {**cur, "version": cur["version"] + 1,
                "customData": {**cur["customData"], "anchor": target}}

    def test_se_ancla_como_un_post_it(self):
        self.b.apply_client_elements([self.anchor_to(self.f, self.p["id"])])
        cd = next(e for e in self.b.elements if e["id"] == "f1")["customData"]
        self.assertEqual(cd["anchor"], self.p["id"])

    def test_y_con_las_mismas_reglas_un_ciclo_se_rechaza(self):
        self.b.apply_client_elements([self.anchor_to(self.f, self.p["id"])])
        self.b.apply_client_elements([self.anchor_to(self.p, "f1")])
        cd = next(e for e in self.b.elements if e["id"] == self.p["id"])["customData"]
        self.assertIsNone(cd["anchor"])
        self.assertFalse(validation.anchor_ok(self.p["id"], "f1", self.b.elements))

    def test_sigue_ahi_al_reabrir(self):
        self.b.save()
        el = next(e for e in reopen(self.b).elements if e["id"] == "f1")
        self.assertEqual(el["customData"]["image"]["file"], "ab" * 32 + ".png")


class CopiaPegada(unittest.TestCase):
    def test_una_foto_o_un_enlace_pegados_reciben_su_propio_enlace(self):
        for kind in ("image", "link"):
            copy = {**element(kind, "orig"), "id": "copia"}
            fixed, _ = scene.adopt_pasted_card(copy)
            self.assertEqual(fixed["link"], scene.CARD_LINKS[kind] + "copia", kind)


if __name__ == "__main__":
    unittest.main()
