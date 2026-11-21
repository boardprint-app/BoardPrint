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

    def test_aplana_lo_que_llega_en_subcarpetas(self):
        # Cómo llegan los artefactos de App desde el 20/11: cada uno bajo su carpeta de bundle/.
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            for rel, data in {"nsis/BoardPrint_0.2.2_x64-setup.exe": "x",
                              "nsis/BoardPrint_0.2.2_x64-setup.exe.sig": "FIRMA-WIN",
                              "dmg/BoardPrint_0.2.2_aarch64.dmg": "d",
                              "macos/BoardPrint.app.tar.gz": "y",
                              "macos/BoardPrint.app.tar.gz.sig": "FIRMA-MAC"}.items():
                (d / rel).parent.mkdir(exist_ok=True)
                (d / rel).write_text(data, encoding="utf-8")
            latest_json.aplanar(d)
            self.assertEqual(sorted(p.name for p in d.iterdir()), [
                "BoardPrint.app.tar.gz", "BoardPrint.app.tar.gz.sig",
                "BoardPrint_0.2.2_aarch64.dmg", "BoardPrint_0.2.2_x64-setup.exe",
                "BoardPrint_0.2.2_x64-setup.exe.sig"])
            got = latest_json.build(d, "0.2.2")
        self.assertEqual(set(got["platforms"]), {"windows-x86_64", "darwin-aarch64"})

    def test_aplanar_no_pisa_un_nombre_repetido(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            for sub in ("a", "b"):
                (d / sub).mkdir()
                (d / sub / "BoardPrint.app.tar.gz").write_text(sub, encoding="utf-8")
            with self.assertRaises(SystemExit):
                latest_json.aplanar(d)


class Notas(unittest.TestCase):
    """PLAN_EXCEL §3.6: el aviso de actualización lleva las notas del Release. Hasta v0.5.0,
    `latest.json` se escribía sin ellas y las notas se ponían después con `gh release edit`."""

    def run_script(self, *args):
        return subprocess.run([sys.executable, str(REPO / "scripts" / "latest_json.py"), *args],
                              capture_output=True, text=True, encoding="utf-8")

    def test_el_latest_json_lleva_las_notas_del_fichero(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "release"
            d.mkdir()
            (d / "BoardPrint_0.6.0_x64-setup.exe").write_bytes(b"x")
            (d / "BoardPrint_0.6.0_x64-setup.exe.sig").write_text("FIRMA", encoding="utf-8")
            notes = Path(tmp) / "notas.md"
            notes.write_text("## New since v0.5.0\n\n- Link arrow «Excel»\n", encoding="utf-8")
            r = self.run_script(str(d), "0.6.0", "--notas", str(notes))
            self.assertEqual(r.returncode, 0, r.stderr)
            got = json.loads((d / "latest.json").read_text(encoding="utf-8"))
        self.assertEqual(got["notes"], "## New since v0.5.0\n\n- Link arrow «Excel»\n")

    def test_poner_notas_cambia_solo_las_notas_de_un_latest_json_ya_publicado(self):
        # Lo que hace el workflow `notas` cuando se edita el Release (`gh release edit`).
        with tempfile.TemporaryDirectory() as tmp:
            latest = Path(tmp) / "latest.json"
            before = {"version": "0.6.0", "notes": "BoardPrint installer.", "pub_date": "2026-11-21T10:00:00Z",
                      "platforms": {"windows-x86_64": {"signature": "FIRMA", "url": "https://x/y.exe"}}}
            latest.write_text(json.dumps(before), encoding="utf-8")
            notes = Path(tmp) / "body.md"
            notes.write_text("Notas nuevas", encoding="utf-8")
            r = self.run_script("--poner-notas", str(latest), "--notas", str(notes))
            self.assertEqual(r.returncode, 0, r.stderr)
            got = json.loads(latest.read_text(encoding="utf-8"))
        self.assertEqual(got, {**before, "notes": "Notas nuevas"})

    def test_poner_notas_sin_notas_se_niega(self):
        with tempfile.TemporaryDirectory() as tmp:
            latest = Path(tmp) / "latest.json"
            latest.write_text("{}", encoding="utf-8")
            self.assertNotEqual(self.run_script("--poner-notas", str(latest)).returncode, 0)
        self.assertNotEqual(self.run_script().returncode, 0, "sin carpeta ni versión")

    def test_los_workflows_las_ponen_al_crear_y_al_editar_el_release(self):
        app = (REPO / ".github" / "workflows" / "app.yml").read_text(encoding="utf-8")
        step = app[app.index("- name: latest.json"):app.index("- name: Release v")]
        self.assertIn("--notas", step, "latest.json con las mismas notas que el Release")
        notas = (REPO / ".github" / "workflows" / "notas.yml").read_text(encoding="utf-8")
        self.assertIn("types: [edited]", notas)
        self.assertIn("--poner-notas", notas)
        self.assertIn("--clobber", notas)
        uses = [ln.strip() for ln in notas.splitlines() if "github.event.release.body" in ln]
        self.assertTrue(uses)
        for ln in uses:     # el cuerpo va en una variable de entorno, nunca pegado en el script
            self.assertRegex(ln, r"^[A-Z_]+: \$\{\{ github\.event\.release\.body \}\}$")


if __name__ == "__main__":
    unittest.main()
