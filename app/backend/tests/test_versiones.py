"""Versiones con nombre (docs/PLAN_PIZARRA.md §3, D22, D76).

Guardar una versión nunca cambia la pizarra; restaurar guarda antes la actual («antes de
restaurar <nombre>») y deja escena y estado de bloques como en la versión; comparar da la
lista de cambios. Ejecutar desde app/backend:  python -m unittest discover -s tests -t .
"""
import copy
import unittest

from pizarra import scene
from tests.helpers import new_board, reopen

VOLATILE = ("version", "versionNonce", "updated")


def content(elements):
    """Lo que se ve de la escena: lo vivo, sin los campos que solo cuentan para sincronizar."""
    return {e["id"]: {k: v for k, v in e.items() if k not in VOLATILE}
            for e in elements if not e.get("isDeleted")}


class Versiones(unittest.TestCase):
    def setUp(self):
        self.b = new_board()
        self.tubo = scene.block_element("prueba.tubo", 0, 0)
        self.b.apply_client_elements([self.tubo])
        self.nota = self.b.user_add_postit("nota", 0, 300)
        self.b.save()

    def edit(self):
        """Cambios después de la versión: un parámetro, un post-it nuevo y la nota movida."""
        self.b.set_params(self.tubo["id"], {"L": 250})
        self.b.user_add_postit("riesgo", 400, 0)
        n = next(e for e in self.b.elements if e["id"] == self.nota["id"])
        self.b.apply_client_elements([{**n, "x": 99, "version": n["version"] + 1}])
        self.b.save()

    def test_guardar_una_version_nunca_cambia_la_pizarra(self):
        els, st = copy.deepcopy(self.b.elements), copy.deepcopy(self.b.state)
        v = self.b.save_version("Primer encaje")
        self.assertEqual((self.b.elements, self.b.state), (els, st))
        self.assertEqual([x["name"] for x in self.b.list_versions()], ["Primer encaje"])
        self.assertEqual(self.b.ws.load_version(self.b.project_id, v["id"])["elements"], els)

    def test_restaurar_deja_escena_y_estado_como_en_la_version(self):
        v = self.b.save_version("Primer encaje")
        saved = self.b.ws.load_version(self.b.project_id, v["id"])
        self.edit()
        self.b.restore_version(v["id"])
        self.assertEqual(content(self.b.elements), content(saved["elements"]))
        self.assertEqual(self.b.state[self.tubo["id"]]["params"]["L"], 300)
        self.assertEqual(content(reopen(self.b).elements), content(saved["elements"]))

    def test_restaurar_guarda_antes_la_actual_como_automatica(self):
        v = self.b.save_version("Primer encaje")
        self.edit()
        before = content(self.b.elements)
        auto = self.b.restore_version(v["id"])
        self.assertTrue(auto["auto"])
        self.assertEqual(auto["name"], "antes de restaurar «Primer encaje»")
        back = self.b.ws.load_version(self.b.project_id, auto["id"])
        self.assertEqual(content(back["elements"]), before)
        # Restaurar la automática deshace la restauración (y su copia no anida nombres).
        again = self.b.restore_version(auto["id"])
        self.assertEqual(again["name"], "antes de deshacer una restauración")
        self.assertEqual(content(self.b.elements), before)
        self.assertEqual(self.b.state[self.tubo["id"]]["params"]["L"], 250)

    def test_lo_restaurado_gana_a_cualquier_ventana_que_vaya_por_detras(self):
        v = self.b.save_version("Primer encaje")
        self.edit()
        stale = {e["id"]: e["version"] for e in self.b.elements}
        self.b.restore_version(v["id"])
        for e in self.b.elements:
            self.assertGreater(e["version"], stale.get(e["id"], 0))
        # Lo que no estaba en la versión queda borrado (no vuelve si otra ventana lo reenvía).
        extra = [e for e in self.b.elements if e.get("isDeleted")]
        self.assertEqual(len(extra), 1)

    def test_comparar_una_version_con_la_pizarra_de_ahora(self):
        v = self.b.save_version("Primer encaje")
        self.edit()
        d = self.b.compare(v["id"], "now")
        kinds = {(c["change"], c["element"]["kind"]) for c in d}
        self.assertEqual(kinds, {("added", "postit"), ("modified", "block"), ("minor", "postit")})
        mod = next(c for c in d if c["change"] == "modified")
        self.assertEqual(mod["fields"], {"params": {"L": [300, 250]}})


if __name__ == "__main__":
    unittest.main()
