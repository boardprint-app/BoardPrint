"""Hallazgos de la revisión independiente de FF 3.3 (plan R6), fijados como reglas."""
import tempfile
import unittest
from pathlib import Path

from pizarra import agent, desktop, scene, validation
from tests.helpers import new_board, reopen, necesita_paquetes
from pizarra.validation import ValidationError


def _board(*kinds):
    b = new_board()
    els = [scene.block_element(k, 400 * i, 0) for i, k in enumerate(kinds)]
    b.apply_client_elements(els)
    return b, [e["id"] for e in els]


def _overlap(a, c):
    return not (a[2] <= c[0] or c[2] <= a[0] or a[3] <= c[1] or c[3] <= a[1])


@necesita_paquetes
class BloqueDesconocido(unittest.TestCase):
    """Un bloque de un tipo que no existe nunca deja la pizarra inutilizable."""

    def test_la_pizarra_sigue_funcionando_con_un_bloque_de_tipo_desconocido(self):
        b, (t,) = _board("demo.tubo")
        b.apply_client_elements([scene.block_element("pack.inexistente", 0, 400)])
        self.assertEqual(b.statuses(), {t: "nunca"})
        b.blocks_view()
        b.summary()
        b.run(t)
        b.save()
        self.assertEqual(reopen(b).statuses(), {t: "al_dia"})


class ProyectoNuevo(unittest.TestCase):
    def test_un_proyecto_nuevo_tiene_carpeta_de_trabajo_antes_de_guardar_nada(self):
        # El agente trabaja con cwd en ella (R6): tiene que existir desde el principio.
        self.assertTrue(new_board("nuevo").dir.is_dir())


class EntradasMalFormadas(unittest.TestCase):
    def test_set_params_de_un_bloque_inexistente_se_rechaza_sin_dejar_rastro(self):
        b, _ = _board("demo.tubo")
        with self.assertRaises(ValidationError):
            b.set_params("noexiste", {"t": 4})
        self.assertNotIn("noexiste", b.state)

    def test_set_params_que_no_son_un_objeto_se_rechazan(self):
        b, (t,) = _board("demo.tubo")
        with self.assertRaises(ValidationError):
            b.set_params(t, [1, 2])

    def test_fuentes_que_no_son_objetos_se_rechazan_con_motivo(self):
        b, _ = _board("demo.tubo")
        result, new = agent.tool_crear_postit(b, {"text": "ok 3 mm", "kind": "nota",
                                                  "sources": ["bloque:x"]})
        self.assertTrue(result["is_error"])
        self.assertEqual(new, [])


class FuentesQueExisten(unittest.TestCase):
    """Una fuente de bloque tiene que existir y tener salidas (regla de los números)."""

    def test_fuente_de_un_bloque_que_no_existe_se_rechaza(self):
        b, _ = _board("demo.tubo")
        with self.assertRaises(ValidationError):
            b.agent_add_postit({"text": "Pesa 2 kg", "kind": "nota", "author": "agent:design",
                                "sources": [{"kind": "bloque", "ref": "bloque:noexiste"}]})

    def test_fuente_de_un_bloque_sin_ejecutar_se_rechaza(self):
        b, (t,) = _board("demo.tubo")
        with self.assertRaises(ValidationError):
            b.agent_add_postit({"text": "Pesa 2 kg", "kind": "nota", "author": "agent:design",
                                "sources": [{"kind": "bloque", "ref": f"bloque:{t}"}]})

    def test_fracciones_y_superindices_cuentan_como_cifras(self):
        for texto in ("Masa ½ kg", "Área en mm²", "Un ⅓ del total"):
            self.assertTrue(validation.has_figures(texto), texto)


class SinTapar(unittest.TestCase):
    """Un post-it del agente nunca tapa nada: tampoco textos sueltos, líneas ni trazos."""

    def _boxes(self, b):
        out = []
        for e in b.elements:
            if e.get("isDeleted") or e.get("containerId") or e.get("type") == "arrow":
                continue
            out.append((e["id"], scene.bbox(e)))
        return out

    def _sin_solapes(self, b):
        boxes = self._boxes(b)
        for i, (ia, a) in enumerate(boxes):
            for ic, c in boxes[i + 1:]:
                self.assertFalse(_overlap(a, c), f"{ia} tapa a {ic}")

    def test_no_tapa_un_texto_suelto_del_usuario(self):
        b, (t,) = _board("demo.tubo")
        tubo = next(e for e in b.elements if e["id"] == t)
        b.apply_client_elements([{"id": "txt", "type": "text", "version": 1, "text": "nota mía",
                                  "x": tubo["x"] + tubo["width"] + 50, "y": tubo["y"],
                                  "width": 200, "height": 40}])
        b.agent_add_postit({"text": "ojo", "kind": "riesgo", "author": "agent:design",
                            "anchor": t})
        self._sin_solapes(b)

    def test_no_tapa_una_linea_trazada_hacia_arriba_a_la_izquierda(self):
        b, (t,) = _board("demo.tubo")
        tubo = next(e for e in b.elements if e["id"] == t)
        x0 = tubo["x"] + tubo["width"] + 300
        b.apply_client_elements([{"id": "ln", "type": "freedraw", "version": 1,
                                  "x": x0, "y": tubo["y"] + 200, "width": 260, "height": 200,
                                  "points": [[0, 0], [-260, -200]]}])
        b.agent_add_postit({"text": "ojo", "kind": "riesgo", "author": "agent:design",
                            "anchor": t})
        self._sin_solapes(b)

    def test_una_posicion_pedida_que_tapa_algo_se_cambia_por_una_libre(self):
        b, (t,) = _board("demo.tubo")
        tubo = next(e for e in b.elements if e["id"] == t)
        b.agent_add_postit({"text": "ojo", "kind": "nota", "author": "agent:design"},
                           x=tubo["x"] + 10, y=tubo["y"] + 10)
        self._sin_solapes(b)


class RutasDeWindows(unittest.TestCase):
    def test_ruta_unc_extendida_queda_como_unc(self):
        self.assertEqual(desktop.clean_path("\\\\?\\UNC\\srv\\share\\engine"),
                         "\\\\srv\\share\\engine")


class GuardadoConFicheroOcupado(unittest.TestCase):
    """En Windows otro proceso (OneDrive, antivirus) puede tener el fichero un instante."""

    def test_guardar_reintenta_si_el_fichero_esta_ocupado_un_momento(self):
        b, _ = _board("demo.tubo")
        b.save()
        real = Path.replace
        fallos = {"n": 2}

        def ocupado(self, target):
            if fallos["n"] > 0:
                fallos["n"] -= 1
                raise PermissionError(5, "Acceso denegado")
            return real(self, target)

        Path.replace = ocupado
        try:
            b.save()
        finally:
            Path.replace = real
        self.assertEqual(fallos["n"], 0)


if __name__ == "__main__":
    unittest.main()
