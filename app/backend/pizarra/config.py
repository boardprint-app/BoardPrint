"""Constantes de la app. El nombre del producto vive solo aquí (D49, D158)."""

APP_NAME = "BoardPrint"       # nombre del producto (D158)
APP_ID = "boardprint"         # rutas, %APPDATA%, índice del workspace (D158)
# Antes de D158: carpetas de ajustes (el `identifier` de Tauri y el APP_ID viejo) y el índice
# del workspace. Se adoptan una vez al arrancar: los ajustes se copian y el índice se renombra.
LEGACY_APP_DIRS = ("dev.cadllm.pizarra", "cad-llm")
LEGACY_INDEX_DIRS = (".cad-llm",)

AUTHOR_USER = "user"
AGENT_AUTHORS = ("agent:design", "agent:review", "agent:onboarding")
