"""El backend nunca queda huérfano: si muere quien lo arrancó, sale (plan R5).

Reproduce lo que pasa con PyInstaller --onefile: un proceso "lanzador" arranca al backend y
luego muere de golpe (como cuando el shell lo mata al cerrar la app).
"""
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from pizarra import watchdog

BACKEND = str(Path(__file__).resolve().parents[1])
# En un venv de Windows, python.exe es un redirector que lanza el intérprete real como hijo:
# con el base, la cadena es lanzador -> backend, igual que en el ejecutable empaquetado.
PY = getattr(sys, "_base_executable", sys.executable)

HIJO = textwrap.dedent("""
    import os, sys, time
    sys.path.insert(0, sys.argv[2])
    from pizarra import watchdog
    watchdog.watch([os.getppid()], interval=0.2)
    open(sys.argv[1], "w").write(str(os.getpid()))
    time.sleep(60)
""")

LANZADOR = textwrap.dedent("""
    import subprocess, sys, time
    subprocess.Popen([sys.executable, "-c", sys.argv[1], sys.argv[2], sys.argv[3]])
    time.sleep(60)
""")


class SinHuerfanos(unittest.TestCase):
    def test_el_backend_sale_cuando_matan_a_su_lanzador(self):
        pidfile = Path(tempfile.mkdtemp()) / "hijo.pid"
        lanzador = subprocess.Popen([PY, "-c", LANZADOR, HIJO, str(pidfile), BACKEND])
        t0 = time.time()
        while not pidfile.exists() and time.time() - t0 < 15:
            time.sleep(0.1)
        hijo = int(pidfile.read_text())
        self.assertTrue(watchdog.alive(hijo))
        lanzador.kill()                       # el padre muere de golpe, sin avisar al hijo
        lanzador.wait()
        t0 = time.time()
        while watchdog.alive(hijo) and time.time() - t0 < 5:
            time.sleep(0.1)
        self.assertFalse(watchdog.alive(hijo), "el backend sigue vivo sin su lanzador")

    def test_alive_distingue_proceso_vivo_de_inexistente(self):
        self.assertTrue(watchdog.alive(os.getpid()))
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        self.assertFalse(watchdog.alive(p.pid))

    def test_sin_procesos_que_vigilar_no_arranca_nada(self):
        self.assertIsNone(watchdog.watch([None, 0]))


if __name__ == "__main__":
    unittest.main()
