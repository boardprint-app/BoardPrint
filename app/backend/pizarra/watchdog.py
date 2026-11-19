"""El backend nunca sobrevive a quien lo arrancó (plan R5).

Empaquetado con PyInstaller --onefile, el ejecutable es un lanzador que arranca el Python de
verdad como proceso hijo. Si el shell mata al lanzador al cerrarse, o el shell muere de golpe,
el hijo quedaría huérfano con su puerto abierto. Un hilo vigila los procesos indicados y sale
en cuanto falta cualquiera.

Solo biblioteca estándar (ctypes en Windows, os.kill(pid, 0) en el resto).
"""
import os
import sys
import threading
import time


def alive(pid):
    if pid is None or pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        h = k32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = wintypes.DWORD()
            ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
            return bool(ok) and code.value == 259      # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def watch(pids, interval=0.5, on_exit=None):
    """Vigila `pids` en un hilo; si alguno deja de existir, llama a `on_exit` (sale del
    proceso por defecto)."""
    pids = [p for p in pids if p]
    if not pids:
        return None
    exit_now = on_exit or (lambda: os._exit(0))

    def loop():
        while True:
            if not all(alive(p) for p in pids) or (sys.platform != "win32" and os.getppid() == 1):
                exit_now()
                return
            time.sleep(interval)

    t = threading.Thread(target=loop, name="watchdog", daemon=True)
    t.start()
    return t
