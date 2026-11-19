"""El actualizador (docs/PLAN_V020.md §4, V9-V13).

Reglas:
- El backend solo hace de puente: lee `update.json` del shell (roto o ausente = desconocido,
  nunca un fallo) y escribe `update.request` **solo** con `check` o `install`.
- La configuración del shell apunta al `latest.json` de boardprint-app/BoardPrint, con su clave
  pública, y la clave privada nunca está en un fichero versionado.
- Una sola versión: `scripts/set_version.py` deja la misma en todos los manifiestos y el
  `latest.json` que escribe `scripts/latest_json.py` lleva la firma de cada instalador.

Ejecutar desde app/backend:  python -m unittest tests.test_actualizador -v
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pizarra import update_api

REPO = Path(__file__).resolve().parents[3]
CONF = REPO / "app" / "shell" / "src-tauri" / "tauri.conf.json"
sys.path.insert(0, str(REPO / "scripts"))
import set_version  # noqa: E402
import latest_json  # noqa: E402


class Puente(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_sin_fichero_o_roto_es_desconocido_nunca_un_fallo(self):
        self.assertEqual(update_api.state(self.dir), {"estado": "desconocido"})
        (self.dir / "update.json").write_text("{roto", encoding="utf-8")
        self.assertEqual(update_api.state(self.dir), {"estado": "desconocido"})
        (self.dir / "update.json").write_text("[1]", encoding="utf-8")
        self.assertEqual(update_api.state(self.dir), {"estado": "desconocido"})

    def test_da_lo_que_escribe_el_shell(self):
        got = {"estado": "disponible", "version": "0.2.0", "actual": "0.1.0", "notas": "x"}
        (self.dir / "update.json").write_text(json.dumps(got), encoding="utf-8")
        self.assertEqual(update_api.state(self.dir), got)

    def test_solo_pide_buscar_o_instalar(self):
        update_api.request(self.dir, "install")
        self.assertEqual((self.dir / "update.request").read_text(encoding="utf-8"), "install")
        with self.assertRaises(ValueError):
            update_api.request(self.dir, "rm -rf")
        self.assertEqual((self.dir / "update.request").read_text(encoding="utf-8"), "install")


# partidas para que este fichero no se encuentre a sí mismo
SECRET, COMMENT = "secret " + "key", "untrusted " + "comment"


class Configuracion(unittest.TestCase):
    def test_apunta_al_latest_json_de_boardprint_con_su_clave_publica(self):
        conf = json.loads(CONF.read_text(encoding="utf-8"))
        upd = conf["plugins"]["updater"]
        self.assertEqual(upd["endpoints"],
                         ["https://github.com/boardprint-app/BoardPrint/releases/latest/download/latest.json"])
        self.assertGreater(len(upd["pubkey"]), 40)
        self.assertTrue(conf["bundle"]["createUpdaterArtifacts"])

    def test_ninguna_clave_privada_en_un_fichero_versionado(self):
        files = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True,
                               check=True).stdout.split("\n")
        found = []
        for name in files:
            path = REPO / name
            if not name or path.suffix in (".png", ".ico", ".icns", ".wasm", ".lock") or not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if SECRET in text and COMMENT in text:
                found.append(name)
        self.assertEqual(found, [])


class Version(unittest.TestCase):
    def test_todos_los_manifiestos_dicen_la_misma(self):
        self.assertEqual(len(set(set_version.current(REPO).values())), 1, set_version.current(REPO))

    def test_set_version_la_escribe_en_todos_sin_tocar_lo_demas(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in set_version.FILES:
                dst = root / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes((REPO / rel).read_bytes())
            before = {rel: (root / rel).read_text(encoding="utf-8") for rel in set_version.FILES}
            set_version.write(root, "9.8.7")
            self.assertEqual(set(set_version.current(root).values()), {"9.8.7"})
            for rel in set_version.FILES:          # solo cambia la línea de la versión
                old = before[rel].splitlines()
                new = (root / rel).read_text(encoding="utf-8").splitlines()
                self.assertEqual(len(old), len(new), rel)
                self.assertLessEqual(sum(a != b for a, b in zip(old, new)), 2, rel)   # lock: raíz y packages[""]
        with self.assertRaises(ValueError):
            set_version.write(REPO, "1.2")


class LatestJson(unittest.TestCase):
    def test_lleva_la_firma_y_la_url_de_cada_instalador(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "BoardPrint_0.2.0_x64-setup.exe").write_bytes(b"x")
            (d / "BoardPrint_0.2.0_x64-setup.exe.sig").write_text("FIRMA-WIN", encoding="utf-8")
            (d / "BoardPrint.app.tar.gz").write_bytes(b"y")
            (d / "BoardPrint.app.tar.gz.sig").write_text("FIRMA-MAC", encoding="utf-8")
            (d / "huerfano.exe").write_bytes(b"z")          # sin firma: no entra
            got = latest_json.build(d, "0.2.0", "notas", "2026-11-22T18:00:00Z")
        self.assertEqual(got["version"], "0.2.0")
        win = got["platforms"]["windows-x86_64"]
        self.assertEqual(win["signature"], "FIRMA-WIN")
        self.assertEqual(win["url"], "https://github.com/boardprint-app/BoardPrint/releases/download/"
                                     "v0.2.0/BoardPrint_0.2.0_x64-setup.exe")
        self.assertEqual(got["platforms"]["darwin-aarch64"]["signature"], "FIRMA-MAC")
        self.assertNotIn("huerfano", json.dumps(got))


if __name__ == "__main__":
    unittest.main()
