"""Catálogos de traducción de un paquete (docs/PLAN_PUBLICACION.md O15).

Reglas:
- `locales/<idioma>.toml` se carga con el paquete y llega a la interfaz en el catálogo
  (`describe()["packs"][i]["i18n"]`), también por el trabajador (`pack_data`) y en un
  `.bppack` exportado e instalado.
- Sin `locales/`, el paquete no tiene traducciones; nunca es un error.
- Un catálogo ilegible o una entrada mal hecha **es un aviso, nunca impide la carga**: se deja
  fuera y el paquete carga.
- La validación (exportar, instalar, proponer) **rechaza** un catálogo que no es una tabla
  plana de textos, una entrada cuyos marcadores `{nombre}` no son los mismos en el texto y en
  la traducción, una clave que es solo marcadores y un fichero que no se llama como un idioma.

Ejecutar desde app/backend:  python -m unittest tests.test_pack_locales -v
"""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from pizarra import pack_data, pack_install, pack_locales, pack_validate, packs
from tests.test_pack_load import load, write

GOOD = '''
"B" = "Block"
"Masa (kg)" = "Mass (kg)"
"Falla por {x} mm" = "Fails by {x} mm"
"{a} de {b}" = "{b}'s {a}"
'''


def put(folder, name, text):
    p = Path(folder) / "locales" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.d = write(self.root / "src", "p")

    def tearDown(self):
        self.tmp.cleanup()

    def loaded(self):
        reg, info, logs = load(self.root / "src")
        self.assertIsNone(info["p"].error)          # nunca deja de cargar por un catálogo
        return reg, info["p"], logs


class Carga(Base):
    def test_el_catalogo_se_carga_y_llega_a_la_interfaz(self):
        put(self.d, "en.toml", GOOD)
        reg, info, logs = self.loaded()
        self.assertEqual(info.i18n["en"]["Masa (kg)"], "Mass (kg)")
        self.assertEqual(info.i18n["en"]["Falla por {x} mm"], "Fails by {x} mm")
        shown = next(p for p in reg.describe()["packs"] if p["id"] == "p")
        self.assertEqual(shown["i18n"], info.i18n)
        self.assertFalse([m for m in logs if "aviso" in m])
        self.assertEqual(pack_validate.validate(self.d), [])

    def test_ajustes_paquetes_lleva_el_catalogo_de_cada_paquete(self):
        # Ajustes → Paquetes se abre también desde el inicio, sin ningún catálogo de bloques
        # cargado: el nombre y la descripción se traducen con lo que da `GET /api/packs`.
        from pizarra.pack_install_api import pack_list
        put(self.d, "en.toml", GOOD)
        reg, info, logs = self.loaded()
        shown = next(p for p in pack_list(reg) if p["id"] == "p")
        self.assertEqual(shown["i18n"], info.i18n)

    def test_sin_locales_no_hay_traducciones(self):
        reg, info, logs = self.loaded()
        self.assertEqual(info.i18n, {})
        self.assertEqual(next(p for p in reg.describe()["packs"] if p["id"] == "p")["i18n"], {})

    def test_un_catalogo_ilegible_es_un_aviso_y_el_paquete_carga(self):
        put(self.d, "en.toml", '"sin cerrar = "x"\n')
        reg, info, logs = self.loaded()
        self.assertNotIn("en", info.i18n)
        self.assertTrue(any("aviso" in m and "locales/en.toml" in m for m in logs), logs)
        self.assertIn("p.b", reg)

    def test_una_entrada_mal_hecha_se_deja_fuera_y_las_demas_valen(self):
        put(self.d, "en.toml", '"Falla por {x} mm" = "Fails by {y} mm"\n"B" = "Block"\n')
        _, info, logs = self.loaded()
        self.assertEqual(info.i18n["en"], {"B": "Block"})
        self.assertTrue(any("marcadores" in m for m in logs), logs)

    def test_por_el_trabajador_llega_lo_mismo(self):
        put(self.d, "en.toml", GOOD)
        reg, info, _ = self.loaded()
        again = pack_data.from_data(json.loads(json.dumps(pack_data.to_data(reg))))
        self.assertEqual(again.describe()["packs"], reg.describe()["packs"])
        self.assertEqual(again.pack("p").i18n, info.i18n)


class Validacion(Base):
    def problems(self, text, name="en.toml"):
        put(self.d, name, text)
        return pack_locales.problems(self.d)

    def test_los_marcadores_tienen_que_ser_los_mismos(self):
        self.assertTrue(self.problems('"Falla por {x} mm" = "Fails by {y} mm"\n'))
        self.assertTrue(self.problems('"Falla por {x} mm" = "Fails"\n'))
        self.assertTrue(self.problems('"Falla" = "Fails by {x} mm"\n'))
        # repetido en la traducción y en otro orden, sí
        self.assertEqual(self.problems('"{a} de {b}" = "{b}: {a} ({a})"\n'), [])

    def test_la_validacion_lo_rechaza(self):
        put(self.d, "en.toml", '"Falla por {x} mm" = "Fails by {y} mm"\n')
        probs = pack_validate.validate(self.d)
        self.assertTrue(any("locales/en.toml" in p and "marcadores" in p for p in probs), probs)
        with self.assertRaises(ValueError):
            pack_install.export(self.d, self.root / "out")

    def test_tiene_que_ser_una_tabla_plana_de_textos(self):
        self.assertTrue(self.problems('[seccion]\n"a" = "b"\n'))
        self.assertTrue(self.problems('a.b = "c"\n'))
        self.assertTrue(self.problems('"a" = 3\n'))
        self.assertTrue(self.problems('"a" = ["b"]\n'))
        self.assertTrue(self.problems('"a" = ""\n'))

    def test_una_clave_solo_de_marcadores_no_vale(self):
        self.assertTrue(self.problems('"{x}" = "{x}"\n'))
        self.assertTrue(self.problems('"{x} {y}" = "{y} {x}"\n'))

    def test_el_fichero_se_llama_como_un_idioma(self):
        self.assertEqual(self.problems('"a" = "b"\n', name="pt-BR.toml"), [])
        self.assertTrue(self.problems('"a" = "b"\n', name="ingles.toml"))

    def test_un_toml_ilegible_no_pasa(self):
        self.assertTrue(self.problems('"a = "b"\n'))


class Archivo(Base):
    def test_exportar_e_instalar_lleva_los_catalogos(self):
        put(self.d, "en.toml", GOOD)
        arch = pack_install.export(self.d, self.root / "out")
        with zipfile.ZipFile(arch) as z:
            self.assertIn("p/locales/en.toml", z.namelist())
        user = self.root / "user"
        user.mkdir()
        origins = [("usuario", user)]
        plan = pack_install.inspect([arch], "usuario", origins, loaded=[],
                                    trial=lambda o, v: pack_install._trial(o, v))
        self.assertTrue(plan.ok, plan.view())
        pack_install.install(plan)
        self.assertEqual((user / "p" / "locales" / "en.toml").read_text(encoding="utf-8"), GOOD)
        reg = packs.load(origins, log=lambda m: None)
        self.assertEqual(reg.pack("p").i18n["en"]["Masa (kg)"], "Mass (kg)")


if __name__ == "__main__":
    unittest.main()
