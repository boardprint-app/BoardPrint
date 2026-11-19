"""La sesión de Claude Code con la que trabajan los agentes (docs/PLAN_PIZARRA.md R4, D186).

`status` corre `claude auth status --json` del CLI que lleva la app (el de `--claude-cli`; en
desarrollo, el que trae el Agent SDK o el del PATH): no gasta tokens. `login` abre
`claude auth login` en una consola, porque el inicio de sesión es interactivo (navegador y
código). `parse` es puro y lo prueban los tests: **sin el CLI o con una salida ilegible, la
sesión sale `no_comprobada`, nunca `conectada`**.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

from pizarra import i18n

CONNECTED, NO_SESSION, UNCHECKED = "conectada", "sin_sesion", "no_comprobada"
# Sin Claude Code instalado (PLAN_PUBLICACION O13: el instalador ya no lo trae)
NO_CLI = "sin_cli"
INSTALL_URL = "https://claude.com/claude-code"
TIMEOUT = 20


def find_cli(cli_path=None):
    if cli_path and Path(cli_path).is_file():
        return str(cli_path)
    try:
        import claude_agent_sdk
        name = "claude.exe" if sys.platform == "win32" else "claude"
        bundled = Path(claude_agent_sdk.__file__).parent / "_bundled" / name
        if bundled.is_file():
            return str(bundled)
    except ImportError:
        pass
    found = shutil.which("claude")
    if found:
        return found
    # El instalador nativo de Claude Code lo deja en ~/.local/bin, que una app abierta desde el
    # escritorio no siempre tiene en el PATH (O13)
    local = Path.home() / ".local" / "bin" / ("claude.exe" if sys.platform == "win32" else "claude")
    return str(local) if local.is_file() else None


def parse(returncode, stdout):
    """`{estado, cuenta, plan, motivo}` a partir de lo que dio `claude auth status --json`."""
    try:
        data = json.loads(stdout or "")
    except ValueError:
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("loggedIn"), bool):
        return {"estado": UNCHECKED, "cuenta": None, "plan": None,
                "motivo": i18n.t("sesion.respuesta_cli", codigo=returncode)}
    if not data["loggedIn"]:
        return {"estado": NO_SESSION, "cuenta": None, "plan": None, "motivo": None}
    account = data.get("email") if isinstance(data.get("email"), str) else None
    plan = data.get("subscriptionType") if isinstance(data.get("subscriptionType"), str) else None
    return {"estado": CONNECTED, "cuenta": account, "plan": plan, "motivo": None}


def status(cli_path=None, run=subprocess.run):
    cli = find_cli(cli_path)
    if cli is None:
        return {"estado": NO_CLI, "cuenta": None, "plan": None, "motivo": None}
    try:
        r = run([cli, "auth", "status", "--json"], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=TIMEOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"estado": UNCHECKED, "cuenta": None, "plan": None, "motivo": str(exc)}
    return parse(r.returncode, r.stdout)


def login(cli_path=None):
    """Abre el inicio de sesión en una consola. False si no hay CLI o no se pudo abrir."""
    cli = find_cli(cli_path)
    if cli is None:
        return False
    try:
        if sys.platform == "win32":
            subprocess.Popen([cli, "auth", "login", "--claudeai"],
                             creationflags=subprocess.CREATE_NEW_CONSOLE)
        elif sys.platform == "darwin":
            cmd = f"'{cli}' auth login --claudeai".replace('"', '\\"')
            subprocess.Popen(["osascript", "-e", f'tell application "Terminal" to do script "{cmd}"'])
        else:
            return False
    except OSError:
        return False
    return True
