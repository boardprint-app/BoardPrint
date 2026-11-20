"""Ajustes de la app en `settings.toml` (docs/PLAN_PIZARRA.md §2, D70).

    schema = 1
    current_workspace = "<id>"
    spike_imported = true
    skin = "escuela"            # D58, D79; uno desconocido se lee como escuela
    [[workspaces]]
    id = "<id>"
    name = "Personal"
    path = "C:/Users/…/Documentos/BoardPrint/Personal"
    last_project = "<id de proyecto>"
    recent = [{id = "<id>", name = "Brazo pinza"}, …]
    [agentes]
    acceso = "sesion"           # O9: sesion de Claude Code o api_key (la clave, en el sistema)
    tope_proyecto_usd = 5       # D168: el tope de un proyecto que no tiene el suyo
    privacidad_vista = true     # D169: ya se ha pulsado *Entendido* en el aviso
    animaciones_automaticas = false   # D144: el agente no las hace por su cuenta (por
                                      # defecto, true); se lee al empezar cada mensaje
    intrusividad_revisor = "a_demanda"   # PLAN_V020 V5: apagado | a_demanda | hitos
    modelo_diseno = "opus"      # V7, D7: opus | sonnet (PIZARRA_MODEL manda en desarrollo)
    modelo_revisor = "opus"
    [paneles]
    derecho = 420               # D60, D174: ancho del panel derecho en px (nunca < 320)
    idioma = "es"               # D180: el de la interfaz y el de las respuestas del agente
    [ventana]                   # D50, D183: lo aplica el shell al abrir y al cambiar
    modo = "maximizada"         # maximizada | pantalla_completa | sin_bordes | ventana
    escala = 100                # %, de 80 a 150 de 10 en 10
    [fuentes]                   # D54, D184: interfaz, pizarra, chat y numeros
    pizarra = "Excalifont"
    [atajos]                    # D97, D185: acción = "Ctrl+Mayús+B"; "" es sin atajo
    "blocks.search" = "Ctrl+B"
    [bienvenida]
    vista = true                # D186: ya se terminó o se saltó la bienvenida

Un valor ilegible se lee como el de por defecto (nunca impide arrancar); los setters, en
cambio, rechazan con ValueError lo que no vale, para que la API diga el motivo (D179). Se
guarda siempre lo que se leyó, aunque esta versión no lo conozca.
"""
import math
import os
import sys
import tomllib
from datetime import datetime
from pathlib import Path

import tomli_w

from pizarra import i18n
from pizarra.storage.local import atomic_write

SCHEMA = 1
MAX_RECENT = 10
# Skins de la pizarra (D58). La interfaz tiene la misma lista en frontend/src/skins.ts.
SKINS = ("escuela", "corcho", "laboratorio", "cad", "calma")
DEFAULT_SKIN = "escuela"
AGENTS = "agentes"              # la tabla de los ajustes de los agentes
DEFAULT_PROJECT_LIMIT_USD = 5.0  # dólares equivalentes por proyecto (D168)
# Cuándo trabaja el revisor (PLAN_V020 V5, D17): nunca, cuando se le pide o, además, al guardar
# una versión con nombre. *Continuo* queda para después.
REVIEW_INTRUSIVENESS = ("apagado", "a_demanda", "hitos")
DEFAULT_REVIEW_INTRUSIVENESS = "a_demanda"
# El modelo de cada agente (V7, D7): el alias que entiende el CLI de Claude Code.
AGENT_MODELS = ("opus", "sonnet", "haiku")
DEFAULT_AGENT_MODEL = "opus"
MODEL_KEYS = {"diseno": "modelo_diseno", "revisor": "modelo_revisor",
              "proveedores": "modelo_proveedores"}
# El de proveedores lee fichas de producto: le basta Haiku (PLAN_APROVISIONAMIENTO A5).
DEFAULT_MODELS = {"proveedores": "haiku"}
OFFERS = "ofertas"              # la tabla de la caducidad de las ofertas (A10)
PANELS = "paneles"              # la tabla de los tamaños de los paneles (D60)
RIGHT_PANEL_MIN = 320           # px: el panel derecho nunca es más estrecho (D174)
RIGHT_PANEL_DEFAULT = 420       # px: el del prototipo
LANGUAGES = ("es", "en")        # D180, PLAN_PUBLICACION O11
WINDOW = "ventana"              # la tabla del modo de ventana y la escala (D183)
WINDOW_MODES = ("maximizada", "pantalla_completa", "sin_bordes", "ventana")
DEFAULT_WINDOW_MODE = "maximizada"
SCALE_MIN, SCALE_MAX, SCALE_STEP, DEFAULT_SCALE = 80, 150, 10, 100
FONTS = "fuentes"               # D184: una por tipo de texto
SYSTEM_FONT = "sistema"
UI_FONTS = (SYSTEM_FONT, "Arial", "Verdana", "Georgia", "Calibri", "Consolas", "Cascadia")
# En la pizarra, solo las que Excalidraw sabe medir (D54).
BOARD_FONTS = ("Excalifont", "Nunito", "Liberation Sans", "Comic Shanns", "Cascadia")
FONT_CHOICES = {"interfaz": UI_FONTS, "pizarra": BOARD_FONTS, "chat": UI_FONTS,
                "numeros": UI_FONTS}
DEFAULT_FONTS = {"interfaz": SYSTEM_FONT, "pizarra": "Excalifont", "chat": SYSTEM_FONT,
                 "numeros": SYSTEM_FONT}
SHORTCUTS = "atajos"            # D97, D185
# Las acciones que tienen atajo: la misma lista que `SHORTCUTS` de frontend/src/shortcuts.ts
# (si cambia una, cambia la otra; lo comprueba test_settings_api). Un atajo de otra acción no se
# guarda: no lo usaría nadie y taparía la combinación (O17).
SHORTCUT_ACTIONS = ("blocks.search", "view.fit_all", "view.fit_selection", "view.fit_viewport",
                    "tinta.activar")
WELCOME = "bienvenida"          # D186
_MODIFIERS = (("ctrl", "Ctrl"), ("mayús", "Mayús"), ("alt", "Alt"))
_MOD_ALIASES = {"ctrl": "ctrl", "cmd": "ctrl", "control": "ctrl", "mayús": "mayús",
                "mayus": "mayús", "shift": "mayús", "alt": "alt", "option": "alt"}


def positive_usd(value):
    """`value` si es un importe válido (un número mayor que cero y finito), si no None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if 0 < value < float("inf") else None


def _finite(value):
    """Un número de verdad (ni booleano, ni NaN, ni infinito)."""
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))


def normalize_combo(combo):
    """La forma canónica de un atajo (D97): los modificadores en orden Ctrl, Mayús, Alt (Cmd
    cuenta como Ctrl) y una letra o una cifra, «Ctrl+Mayús+B»; `""` es sin atajo. Lo que no
    es un atajo da ValueError."""
    if not isinstance(combo, str):
        raise ValueError(i18n.t("ajustes.atajo_no_valido", atajo=repr(combo)))
    if combo.strip() == "":
        return ""
    *mods, key = [p.strip().lower() for p in combo.split("+")]
    seen = set()
    for m in mods:
        alias = _MOD_ALIASES.get(m)
        if alias is None or alias in seen:
            raise ValueError(i18n.t("ajustes.atajo_no_valido", atajo=repr(combo)))
        seen.add(alias)
    if len(key) != 1 or not (key.isascii() and key.isalnum()):
        raise ValueError(i18n.t("ajustes.atajo_tecla", atajo=repr(combo)))
    return "+".join([label for m, label in _MODIFIERS if m in seen] + [key.upper()])


class Settings:
    def __init__(self, path, data, problem=None):
        self.path = Path(path)
        self.data = data
        self.problem = problem          # texto para el usuario si el fichero no se pudo leer

    @classmethod
    def load(cls, path):
        path = Path(path)
        if not path.exists():
            return cls(path, {"schema": SCHEMA})
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
            # Nunca impide arrancar ni se pierde: se aparta con otro nombre y se empieza de cero.
            aside = path.with_name(f"{path.name}.ilegible-{datetime.now():%Y%m%d-%H%M%S}")
            path.replace(aside)
            return cls(path, {"schema": SCHEMA},
                       problem=i18n.t("ajustes.ilegibles", system_language(), motivo=exc,
                                      fichero=aside.name))
        return cls(path, data)

    def save(self):
        atomic_write(self.path, tomli_w.dumps(self.data).encode("utf-8"))

    # --------------------------------------------------------------- workspaces
    def workspaces(self):
        ws = self.data.get("workspaces")
        if not isinstance(ws, list):
            ws = self.data["workspaces"] = []
        return [w for w in ws if isinstance(w, dict) and w.get("id") and w.get("path")]

    def workspace(self, ws_id):
        return next((w for w in self.workspaces() if w["id"] == ws_id), None)

    def add_workspace(self, ws_id, name, path):
        self.workspaces()
        self.data["workspaces"].append({"id": ws_id, "name": name, "path": str(path)})
        self.data.setdefault("current_workspace", ws_id)

    def current_workspace(self):
        return self.workspace(self.data.get("current_workspace")) or next(
            iter(self.workspaces()), None)

    @property
    def spike_imported(self):
        return bool(self.data.get("spike_imported"))

    @spike_imported.setter
    def spike_imported(self, value):
        self.data["spike_imported"] = bool(value)

    @property
    def skin(self):
        value = self.data.get("skin")
        return value if value in SKINS else DEFAULT_SKIN

    @skin.setter
    def skin(self, value):
        if value not in SKINS:
            raise ValueError(i18n.t("ajustes.skin_desconocido", valor=repr(value)))
        self.data["skin"] = value

    # ------------------------------------------------------------ idioma (D180)
    @property
    def language(self):
        value = self.data.get("idioma")
        return value if value in LANGUAGES else system_language()

    @language.setter
    def language(self, value):
        if value not in LANGUAGES:
            raise ValueError(i18n.t("ajustes.idioma_no_disponible", valor=repr(value)))
        self.data["idioma"] = value

    # -------------------------------------------------- ventana y escala (D183)
    def _table(self, name):
        table = self.data.get(name)
        if not isinstance(table, dict):
            table = self.data[name] = {}
        return table

    def _read(self, name, key):
        table = self.data.get(name)
        return table.get(key) if isinstance(table, dict) else None

    @property
    def window_mode(self):
        value = self._read(WINDOW, "modo")
        return value if value in WINDOW_MODES else DEFAULT_WINDOW_MODE

    @window_mode.setter
    def window_mode(self, value):
        if value not in WINDOW_MODES:
            raise ValueError(i18n.t("ajustes.modo_ventana_desconocido", valor=repr(value)))
        self._table(WINDOW)["modo"] = value

    @property
    def scale(self):
        """La escala de la interfaz en %: una ilegible vale 100; una fuera de 80-150 se lleva
        al borde y se redondea a la decena (un `settings.toml` a mano)."""
        value = self._read(WINDOW, "escala")
        if not _finite(value):
            return DEFAULT_SCALE
        # medio hacia arriba, como el shell (`window_mode.rs`): 125 es 130, no 120
        value = math.floor(value / SCALE_STEP + 0.5) * SCALE_STEP
        return min(SCALE_MAX, max(SCALE_MIN, value))

    @scale.setter
    def scale(self, value):
        if not _finite(value) or not SCALE_MIN <= value <= SCALE_MAX or value % SCALE_STEP:
            raise ValueError(i18n.t("ajustes.escala_no_valida", valor=repr(value), min=SCALE_MIN,
                                    max=SCALE_MAX, paso=SCALE_STEP))
        self._table(WINDOW)["escala"] = int(value)

    # ------------------------------------------------------------ fuentes (D184)
    @property
    def fonts(self):
        """Una fuente por tipo de texto; una que no está en su lista vale la de por defecto."""
        out = {}
        for kind, choices in FONT_CHOICES.items():
            value = self._read(FONTS, kind)
            out[kind] = value if value in choices else DEFAULT_FONTS[kind]
        return out

    def set_font(self, kind, value):
        if kind not in FONT_CHOICES:
            raise ValueError(i18n.t("ajustes.tipo_texto_desconocido", tipo=repr(kind)))
        if value not in FONT_CHOICES[kind]:
            raise ValueError(i18n.t("ajustes.fuente_no_disponible", tipo=kind, valor=repr(value)))
        self._table(FONTS)[kind] = value

    # ------------------------------------------------------------ atajos (D185)
    @property
    def shortcuts(self):
        """`{acción: atajo}` de los que el usuario cambió. Uno ilegible no cuenta (la interfaz
        usa el de por defecto) y, si dos acciones tienen el mismo atajo, ninguna se queda con
        él: nunca hay dos acciones con el mismo."""
        table = self.data.get(SHORTCUTS)
        if not isinstance(table, dict):
            return {}
        out = {}
        for action, combo in table.items():
            if action not in SHORTCUT_ACTIONS:
                continue                       # de una acción que ya no existe: no cuenta
            try:
                out[str(action)] = normalize_combo(combo)
            except ValueError:
                continue
        count = {}
        for combo in out.values():
            count[combo] = count.get(combo, 0) + 1
        return {a: c for a, c in out.items() if not c or count[c] == 1}

    def set_shortcuts(self, changes):
        """Guarda `{acción: atajo}` (los que no vienen se quedan). ValueError si uno no es un
        atajo o si dos acciones acabarían con el mismo: el choque confirmado (D97) manda
        también la otra acción, con `""`."""
        merged = dict(self.shortcuts)
        for action, combo in changes.items():
            if not isinstance(action, str) or not action:
                raise ValueError(i18n.t("ajustes.accion_no_valida", accion=repr(action)))
            if action not in SHORTCUT_ACTIONS:
                raise ValueError(i18n.t("ajustes.accion_desconocida", accion=action,
                                        acciones=", ".join(SHORTCUT_ACTIONS)))
            merged[action] = normalize_combo(combo)
        seen = {}
        for action, combo in merged.items():
            if combo and seen.setdefault(combo, action) != action:
                raise ValueError(i18n.t("ajustes.atajo_ocupado", atajo=combo, accion=seen[combo]))
        self.data[SHORTCUTS] = merged

    def reset_shortcuts(self):
        self.data.pop(SHORTCUTS, None)

    # --------------------------------------------------------- bienvenida (D186)
    @property
    def welcome_seen(self):
        return self._read(WELCOME, "vista") is True

    @welcome_seen.setter
    def welcome_seen(self, value):
        self._table(WELCOME)["vista"] = bool(value)

    # ------------------------------------------------------ agentes (D168, D169)
    def _agents(self):
        agents = self.data.get(AGENTS)
        if not isinstance(agents, dict):
            agents = self.data[AGENTS] = {}
        return agents

    @property
    def project_limit_usd(self):
        """El tope de un proyecto sin el suyo; uno que no es un importe vale el de por defecto."""
        agents = self.data.get(AGENTS)
        value = positive_usd(agents.get("tope_proyecto_usd")) if isinstance(agents, dict) else None
        return value or DEFAULT_PROJECT_LIMIT_USD

    @project_limit_usd.setter
    def project_limit_usd(self, value):
        if positive_usd(value) is None:
            raise ValueError(i18n.t("ajustes.tope_valor_no_valido", valor=repr(value)))
        self._agents()["tope_proyecto_usd"] = float(value)

    @property
    def search_limit_usd(self):
        """El tope de una búsqueda en proveedores (A5); uno que no es un importe vale 0,25."""
        from pizarra.supply import DEFAULT_SEARCH_BUDGET_USD
        value = positive_usd(self._read(AGENTS, "tope_busqueda_usd"))
        return value or DEFAULT_SEARCH_BUDGET_USD

    @search_limit_usd.setter
    def search_limit_usd(self, value):
        if positive_usd(value) is None:
            raise ValueError(i18n.t("ajustes.tope_valor_no_valido", valor=repr(value)))
        self._agents()["tope_busqueda_usd"] = float(value)

    @property
    def offers_expiry_days(self):
        """Los días que vale una oferta (A10): uno que no vale, 7."""
        from pizarra import supply
        try:
            return supply.check_expiry_days(self._read(OFFERS, "caducidad_dias"))
        except ValueError:
            return supply.DEFAULT_EXPIRY_DAYS

    @offers_expiry_days.setter
    def offers_expiry_days(self, value):
        from pizarra import supply
        self._table(OFFERS)["caducidad_dias"] = supply.check_expiry_days(value)

    @property
    def privacy_seen(self):
        agents = self.data.get(AGENTS)
        return isinstance(agents, dict) and agents.get("privacidad_vista") is True

    @privacy_seen.setter
    def privacy_seen(self, value):
        self._agents()["privacidad_vista"] = bool(value)

    @property
    def animations_auto(self):
        """«Animaciones automáticas» (D144): solo un `false` las apaga; sin el ajuste, o con
        un valor que no es true ni false, siguen activadas (el de por defecto)."""
        agents = self.data.get(AGENTS)
        return not (isinstance(agents, dict) and agents.get("animaciones_automaticas") is False)

    @animations_auto.setter
    def animations_auto(self, value):
        self._agents()["animaciones_automaticas"] = bool(value)

    @property
    def agent_access(self):
        """Cómo entra el agente (PLAN_PUBLICACION O9): «sesion» de Claude Code (por defecto, y
        con un valor que no se entiende) o «api_key» (la clave, en `api_key`, nunca aquí)."""
        from pizarra.api_key import ACCESS, DEFAULT_ACCESS
        agents = self.data.get(AGENTS)
        value = agents.get("acceso") if isinstance(agents, dict) else None
        return value if value in ACCESS else DEFAULT_ACCESS

    @agent_access.setter
    def agent_access(self, value):
        from pizarra.api_key import ACCESS
        if value not in ACCESS:
            raise ValueError(i18n.t("ajustes.acceso_desconocido", valor=repr(value)))
        self._agents()["acceso"] = value

    @property
    def review_intrusiveness(self):
        """Cuándo trabaja el revisor (V5): uno que no se entiende vale «a_demanda»."""
        value = self._read(AGENTS, "intrusividad_revisor")
        return value if value in REVIEW_INTRUSIVENESS else DEFAULT_REVIEW_INTRUSIVENESS

    @review_intrusiveness.setter
    def review_intrusiveness(self, value):
        if value not in REVIEW_INTRUSIVENESS:
            raise ValueError(i18n.t("ajustes.intrusividad_no_valida", valor=repr(value)))
        self._agents()["intrusividad_revisor"] = value

    def agent_model(self, agent):
        """El modelo de `agent` («diseno» o «revisor», V7): uno que no se entiende, «opus».
        `PIZARRA_MODEL` del entorno manda sobre el ajuste (desarrollo)."""
        return os.environ.get("PIZARRA_MODEL", "").strip() or self.saved_model(agent)

    def saved_model(self, agent):
        """El del ajuste, sin mirar el entorno (lo que enseña *Ajustes*)."""
        value = self._read(AGENTS, MODEL_KEYS[agent])
        return value if value in AGENT_MODELS else DEFAULT_MODELS.get(agent, DEFAULT_AGENT_MODEL)

    def set_agent_model(self, agent, value):
        if agent not in MODEL_KEYS:
            raise ValueError(i18n.t("ajustes.agente_desconocido", agente=repr(agent)))
        if value not in AGENT_MODELS:
            raise ValueError(i18n.t("ajustes.modelo_no_valido", clave=MODEL_KEYS[agent],
                                    valor=repr(value), modelos=", ".join(AGENT_MODELS)))
        self._agents()[MODEL_KEYS[agent]] = value

    # ------------------------------------------------------------- paneles (D60)
    @property
    def right_panel(self):
        """Ancho del panel derecho (D174): uno que no es un número vale el de por defecto, y
        uno por debajo del mínimo se lee como el mínimo (p. ej. un `settings.toml` a mano)."""
        panels = self.data.get(PANELS)
        value = panels.get("derecho") if isinstance(panels, dict) else None
        if not _finite(value):
            return RIGHT_PANEL_DEFAULT
        return max(RIGHT_PANEL_MIN, int(round(value)))

    @right_panel.setter
    def right_panel(self, value):
        """Nunca se guarda por debajo del mínimo: se guarda el mínimo. No numérico: ValueError."""
        if not _finite(value):
            raise ValueError(f"ancho de panel no válido: {value!r}")
        panels = self.data.get(PANELS)
        if not isinstance(panels, dict):
            panels = self.data[PANELS] = {}
        panels["derecho"] = max(RIGHT_PANEL_MIN, int(round(value)))

    # ------------------------------------------------------- recientes y último
    def recent(self, ws_id):
        w = self.workspace(ws_id) or {}
        rec = w.get("recent")
        return [{"id": r["id"], "name": str(r.get("name", ""))} for r in rec
                if isinstance(r, dict) and isinstance(r.get("id"), str)] if isinstance(rec, list) else []

    def last_project(self, ws_id):
        last = (self.workspace(ws_id) or {}).get("last_project")
        return last if isinstance(last, str) and last else None

    def touch_project(self, ws_id, project_id, name, opened=True):
        """Pone el proyecto el primero de recientes y, si se ha abierto, como el último."""
        w = self.workspace(ws_id)
        rec = [r for r in self.recent(ws_id) if r["id"] != project_id]
        w["recent"] = [{"id": project_id, "name": name}] + rec[:MAX_RECENT - 1]
        if opened:
            w["last_project"] = project_id

    def forget_project(self, ws_id, project_id):
        w = self.workspace(ws_id)
        w["recent"] = [r for r in self.recent(ws_id) if r["id"] != project_id]
        if w.get("last_project") == project_id:
            del w["last_project"]


# ------------------------------------------------- idioma del sistema (O11)
def language_from_locale(name):
    """«es» para un locale en español (`es_ES`, `es-419`, `Spanish_Spain`) o en otra lengua de
    España (catalán, gallego, euskera: quien la usa lee español), «en» para cualquier otro, y
    None si no dice nada."""
    name = (name or "").strip().lower()
    if not name or name in ("c", "posix"):
        return None
    lang = name.replace("-", "_").split("_")[0].split(".")[0]
    spain = ("es", "ca", "gl", "eu", "spanish", "catalan", "galician", "basque")
    return "es" if lang in spain else "en"


def system_language():
    """El idioma de la app sin ajuste guardado: el de la interfaz del sistema (Windows), o el
    de las variables de locale y `locale.getlocale()`; si nada lo dice, inglés."""
    import locale
    names = []
    if sys.platform == "win32":
        try:
            import ctypes
            lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            names.append(locale.windows_locale.get(lcid, ""))
        except (AttributeError, OSError):
            pass
    names += [os.environ.get(v, "") for v in ("LC_ALL", "LC_MESSAGES", "LANG")]
    try:
        names.append(locale.getlocale()[0] or "")
    except ValueError:
        pass
    for name in names:
        language = language_from_locale(name)
        if language:
            return language
    return "en"
