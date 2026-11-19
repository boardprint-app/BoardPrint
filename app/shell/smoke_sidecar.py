"""Prueba de humo del backend empaquetado (lo usa el CI antes de compilar el instalador).

    python app/shell/smoke_sidecar.py

Arranca el sidecar como lo haría el shell y comprueba: que arranca en menos de 10 s (plan
§12), que sin token rechaza la API, que con token responde, que sirve la interfaz y que el
primer arranque crea los ajustes y el workspace por defecto; que arranca sin paquetes y los
instala desde su `.bppack` (PLAN_PAQUETES P11, P83: la carga de prueba va en un proceso
aparte, también dentro del ejecutable congelado); que un bloque se ejecuta en su proceso de
cálculo (plan D92); estas dos, solo si el repo trae `packs/`. Y que, al matar al lanzador, no queda ningún backend huérfano.
"""
import glob
import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

SHELL = Path(__file__).resolve().parent
BIN = SHELL / "src-tauri" / "binaries"
ROOT = SHELL.parents[1]
# El entorno de paquetes, como lo pasa el shell (PLAN_PAQUETES P93): el Python y uv de la app
# (`fetch_pyenv.py`), el trabajador (aquí, `app/backend`, que lleva lo mismo que `worker/`) y el
# motor común.
PYENV = SHELL / "src-tauri" / "pyenv"
WORKER = ROOT / "app" / "backend"
ENGINE = ROOT / "engine"
PORT, TOKEN = 8797, "humo"
PACKS = ("demo", "robotica_base", "fusion", "robotica")   # lo que necesita run_blocks


def get(path, token=None, body=None, timeout=2):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}",
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-Token": token, "Content-Type": "application/json"}
                                 if token else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""


def run_chain(name, chain):
    """Crea los bloques `chain` = [(tipo, puerto que da al siguiente)] en un proyecto nuevo,
    los une y ejecuta el último por el WebSocket, como lo hace la interfaz."""
    from websockets.sync.client import connect      # viene con uvicorn[standard]
    status, body = get("/api/projects", TOKEN, {"folder": "", "name": name})
    assert status == 200, f"no se crea el proyecto ({status})"
    pid = json.loads(body)["id"]
    with connect(f"ws://127.0.0.1:{PORT}/ws?project={pid}&token={TOKEN}", open_timeout=5) as ws:
        assert json.loads(ws.recv(timeout=5))["type"] == "init"
        ids = []
        for i, (kind, _) in enumerate(chain):
            status, body = get(f"/api/projects/{pid}/blocks", TOKEN, {"type": kind, "x": 400 * i})
            assert status == 200, f"no se crea el bloque {kind} ({status})"
            ids.append(json.loads(body)["id"])
        arrows = [{"id": f"humo{i}", "type": "arrow", "version": 1, "isDeleted": False,
                   "startBinding": {"elementId": ids[i]}, "endBinding": {"elementId": ids[i + 1]},
                   "customData": {"kind": "connection", "from": port, "to": port}}
                  for i, (_, port) in enumerate(chain[:-1])]
        if arrows:
            ws.send(json.dumps({"type": "scene", "elements": arrows}))
        t0 = time.time()
        ws.send(json.dumps({"type": "run", "block": ids[-1]}))
        while True:
            msg = json.loads(ws.recv(timeout=60))
            if msg["type"] == "error":
                sys.exit(f"ejecutar {name}: {msg['message']}")
            if msg["type"] == "run_finished":
                break
        assert msg["done"] == ids and not msg.get("error"), f"{name}: la ejecución dio {msg}"
    print(f"{name}: {len(ids)} bloque(s) ejecutados en su proceso en {time.time() - t0:.1f} s")


def install_packs(tmp):
    """Instala `PACKS` como lo haría el usuario: sus `.bppack` (los de *Exportar*), el resumen
    y *Instalar*."""
    from build_packs import build
    archives = [str(a) for a in build(tmp / "bppacks", PACKS)]
    t0 = time.time()
    status, body = get("/api/packs/inspect", TOKEN, {"paths": archives, "target": "usuario"}, 120)
    assert status == 200, f"el resumen de instalar da {status}"
    plan = json.loads(body)
    assert plan["ok"], f"no se pueden instalar: {[i['problems'] for i in plan['items']]}"
    status, body = get("/api/packs/install", TOKEN, {"token": plan["token"]}, 120)
    assert status == 200 and sorted(json.loads(body)["installed"]) == sorted(PACKS), \
        f"instalar da {status}"
    print(f"paquetes instalados desde su .bppack en {time.time() - t0:.1f} s")


def run_blocks():
    run_chain("Humo", [("demo.tubo", None)])
    # El brazo entero: el paquete robotica (datos del sidecar, P64) y el motor común congelado,
    # del requisito al informe HTML.
    run_chain("Humo brazo", [("robotica.requisitos", "requisitos"),
                             ("robotica.arquitectura", "arquitectura"),
                             ("robotica.dimensionado", "brazo"),
                             ("robotica.comprobaciones", "analisis"),
                             ("robotica.informe", None)])
    run_template("Humo detalle", "robotica.brazo")


def run_template(name, template):
    """La plantilla del paquete y *Ejecutar lo desactualizado*: el brazo de detalle
    (`packs/robotica/robotarm/detail`) desde los paquetes del sidecar, hasta la lista de
    materiales."""
    from websockets.sync.client import connect
    status, body = get("/api/projects", TOKEN, {"folder": "", "name": name})
    assert status == 200, f"no se crea el proyecto ({status})"
    pid = json.loads(body)["id"]
    with connect(f"ws://127.0.0.1:{PORT}/ws?project={pid}&token={TOKEN}", open_timeout=5) as ws:
        assert json.loads(ws.recv(timeout=5))["type"] == "init"
        status, body = get(f"/api/projects/{pid}/templates", TOKEN, {"template": template})
        assert status == 200, f"no se pone la plantilla ({status})"
        t0 = time.time()
        ws.send(json.dumps({"type": "run_stale"}))
        while True:
            msg = json.loads(ws.recv(timeout=120))
            if msg["type"] == "error":
                sys.exit(f"ejecutar {name}: {msg['message']}")
            if msg["type"] == "run_finished":
                break
        assert not msg["failed"] and not msg.get("error") and len(msg["done"]) >= 6, f"{name}: {msg}"
    print(f"{name}: {len(msg['done'])} bloques ejecutados en su proceso en {time.time() - t0:.1f} s")


def main():
    exe = glob.glob(str(BIN / "pizarra-backend-*"))
    if len(exe) != 1:
        sys.exit(f"se esperaba un sidecar en {BIN}, hay {exe}")
    tmp = Path(tempfile.mkdtemp())
    if not (PYENV / "pyenv.json").is_file():
        sys.exit(f"falta el entorno de paquetes en {PYENV}: python app/shell/fetch_pyenv.py")
    proc = subprocess.Popen([exe[0], "--port", str(PORT), "--token", TOKEN,
                             "--settings", str(tmp / "settings.toml"),
                             "--documents", str(tmp / "Documentos"),
                             "--pyenv-dir", str(PYENV), "--worker-dir", str(WORKER),
                             "--engine-dir", str(ENGINE), "--cache-dir", str(tmp / "cache")])
    t0 = time.time()
    try:
        while True:
            try:
                status, _ = get("/api/health", TOKEN)
                if status == 200:
                    break
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                pass
            if time.time() - t0 > 10:
                sys.exit("el sidecar no responde en 10 s")
            time.sleep(0.1)
        print(f"arranque: {time.time() - t0:.1f} s")
        # La app no trae paquetes (P11): arranca sin ninguno
        packs = json.loads(get("/api/health", TOKEN)[1]).get("packs")
        assert packs == {}, f"el sidecar trae paquetes: {packs}"
        assert get("/api/health")[0] == 401, "la API responde sin token"
        status, body = get("/")
        assert status == 200 and b'id="root"' in body, "no sirve la interfaz"
        # Primer arranque: crea el workspace por defecto y va a la pantalla de inicio (D63).
        assert get("/api/start", TOKEN)[0] == 200, "el arranque no responde"
        assert get("/api/workspace", TOKEN)[0] == 200, "el workspace no se lee"
        assert (tmp / "settings.toml").is_file(), "no se guardan los ajustes"
        assert list(tmp.glob("Documentos/*/Personal/workspace.toml")), \
            "no se crea el workspace por defecto en Documentos"
        # Instalar paquetes y ejecutar bloques necesita los del repo: el repo público no los lleva.
        if (ROOT / "packs").is_dir():
            install_packs(tmp)
            packs = json.loads(get("/api/health", TOKEN)[1]).get("packs") or {}
            assert all(packs.get(p, "falta") is None for p in PACKS), f"paquetes cargados: {packs}"
            run_blocks()
        else:
            print("sin packs/: se salta instalar paquetes y ejecutar bloques")
        print("prueba de humo del sidecar: OK")
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    # PyInstaller --onefile: terminate() mata al lanzador; el backend real (hijo) tiene que
    # salir solo gracias al watchdog y liberar el puerto (plan R5).
    t0 = time.time()
    while time.time() - t0 < 5:
        try:
            get("/api/health", TOKEN)
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            print(f"sin huérfanos: el puerto queda libre en {time.time() - t0:.1f} s")
            return
        time.sleep(0.2)
    sys.exit("el backend sigue respondiendo tras matar al lanzador: proceso huérfano")


if __name__ == "__main__":
    main()
