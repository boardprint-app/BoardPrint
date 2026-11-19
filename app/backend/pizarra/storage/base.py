"""Interfaz de almacenamiento de un workspace (docs/PLAN_PIZARRA.md §2, D68).

Operaciones del dominio, no de ficheros: el árbol de carpetas y proyectos, y el contenido de
cada proyecto (escena, estado de los bloques, miniatura). Hoy la implementa `LocalWorkspace`
sobre carpetas; un servidor la implementaría sobre su base de datos. Las dos tienen que pasar
los mismos tests de contrato (`tests/storage_contract.py`).

Direcciones: una carpeta se nombra por su ruta relativa al workspace, con `/` y `""` para la
raíz ("Terminales/Clientes"); un proyecto, por su id (D64), que no cambia al renombrarlo ni
al moverlo. La lista de workspaces no vive aquí sino en `settings.toml` (D70).
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

# Los ficheros de `agent/` aparte del chat (D164, D165): la sesión de cada conversación, el
# consumo y los hilos (estos, desde el paso 3 de FF 4.6; sus mensajes, en un fichero por hilo).
AGENT_FILES = ("sessions", "usage", "threads")
# Las conversaciones de `agent/` (un `.jsonl` cada una): `chat`, la del agente de diseño, y
# `review`, la del revisor (FF 6.1, PLAN_V020 V3), que nunca se mezclan.
AGENT_CHATS = ("chat", "review")


class StorageError(ValueError):
    """Error del almacenamiento con un mensaje que se puede enseñar al usuario."""


class InvalidName(StorageError):
    """Nombre o ruta que no se admite (caracteres, nombres reservados, la raíz…)."""


class NotFound(StorageError):
    """La carpeta o el proyecto no existe (o ya no está donde estaba)."""


class Conflict(StorageError):
    """Ya hay algo con ese nombre, o el movimiento es imposible (una carpeta en sí misma)."""


@dataclass(frozen=True)
class WorkspaceInfo:
    id: str
    name: str


@dataclass(frozen=True)
class ProjectInfo:
    id: str
    name: str
    path: str          # ruta del proyecto relativa al workspace: "Brazos/Brazo pinza"
    folder: str        # carpeta que lo contiene: "Brazos" ("" = la raíz)


@dataclass
class Node:
    """Nodo del árbol: una carpeta (con hijos) o un proyecto (sin hijos)."""
    kind: str                      # "folder" | "project"
    name: str
    path: str
    id: str | None = None          # solo proyectos; None si su project.toml no se puede leer
    modified: float = 0.0          # segundos epoch: lo más reciente de lo que hay dentro
    error: str | None = None       # proyecto que no se puede abrir, y por qué
    thumbnail: bool = False        # el proyecto tiene miniatura para la pantalla de inicio
    children: list = field(default_factory=list)


class Workspace(ABC):
    # ------------------------------------------------------------------- árbol
    @abstractmethod
    def info(self) -> WorkspaceInfo: ...

    @abstractmethod
    def tree(self) -> Node:
        """Raíz del workspace con todo lo que tiene; carpetas primero, luego por nombre."""

    @abstractmethod
    def create_folder(self, parent: str, name: str) -> str:
        """Crea una carpeta y devuelve su ruta."""

    @abstractmethod
    def create_project(self, folder: str, name: str) -> ProjectInfo: ...

    @abstractmethod
    def project(self, project_id: str) -> ProjectInfo:
        """Datos de un proyecto por su id; `NotFound` si ya no está en el workspace."""

    @abstractmethod
    def projects_under(self, folder: str) -> list[str]:
        """Ids de los proyectos que hay dentro de una carpeta, a cualquier profundidad."""

    @abstractmethod
    def rename_folder(self, path: str, name: str) -> str:
        """Renombra y devuelve la ruta nueva."""

    @abstractmethod
    def rename_project(self, project_id: str, name: str) -> ProjectInfo: ...

    @abstractmethod
    def move_folder(self, path: str, dest: str) -> str:
        """Mueve la carpeta dentro de `dest` y devuelve su ruta nueva."""

    @abstractmethod
    def move_project(self, project_id: str, dest: str) -> ProjectInfo: ...

    @abstractmethod
    def trash_folder(self, path: str) -> list[str]:
        """Manda la carpeta a la papelera (D66) y devuelve los ids de los proyectos que se
        fueron con ella, para cerrar antes sus sesiones."""

    @abstractmethod
    def trash_project(self, project_id: str) -> None: ...

    def trash_file(self, path) -> None:
        """Un archivo del disco a la papelera (D66): el nuevo de una propuesta de archivo que el
        usuario rechaza (D176). Solo lo tiene el almacenamiento local."""
        raise NotImplementedError("este almacenamiento no borra archivos del disco")

    # ---------------------------------------------------- contenido del proyecto
    @abstractmethod
    def load_scene(self, project_id: str) -> list: ...

    @abstractmethod
    def save_scene(self, project_id: str, elements: list) -> None: ...

    @abstractmethod
    def backup_scene_once(self, project_id: str, name: str, elements: list) -> bool:
        """Guarda una copia de la escena con un nombre (`board/scene.<name>.json` en local)
        solo si no existe ya: nunca pisa un respaldo. Dice si la ha guardado. Un nombre que no
        sea letras, cifras, guion o subrayado es `InvalidName`."""

    @abstractmethod
    def load_scene_backup(self, project_id: str, name: str) -> list | None: ...

    @abstractmethod
    def load_block_state(self, project_id: str) -> dict: ...

    @abstractmethod
    def save_block_state(self, project_id: str, state: dict) -> None: ...

    # ------------------------------------------- archivos de salida de los bloques (D93)
    # Cada bloque tiene sus archivos aparte (`blocks/<id>/` en local). Una ejecución escribe en
    # una carpeta de trabajo nueva (`block_scratch`) que nadie lee; solo si termina bien pasa a
    # ser la del bloque (`commit_block_files`). Así cancelar o fallar nunca deja archivos a
    # medias. Un nombre de archivo es relativo a la carpeta del bloque y nunca sale de ella.
    @abstractmethod
    def block_scratch(self, project_id: str, block_id: str):
        """Carpeta local nueva y vacía para la ejecución de ese bloque (`ctx.workdir`)."""

    @abstractmethod
    def commit_block_files(self, project_id: str, block_id: str, scratch) -> None:
        """Los archivos del bloque pasan a ser los de `scratch`, enteros; los de antes se van."""

    @abstractmethod
    def discard_block_scratch(self, scratch) -> None:
        """Tira una carpeta de trabajo que no se va a usar (cancelada o fallida)."""

    @abstractmethod
    def clear_block_files(self, project_id: str, block_id: str) -> None:
        """El bloque se queda sin archivos (su última ejecución falló: no tiene salidas)."""

    @abstractmethod
    def block_file(self, project_id: str, block_id: str, name: str):
        """Ruta local de un archivo de salida del bloque, para leerlo o abrirlo. `InvalidName`
        si el nombre sale de la carpeta del bloque; `NotFound` si no existe."""

    @abstractmethod
    def sync_file(self, project_id: str, block_id: str):
        """Ruta local del registro de sincronización del bloque con su herramienta
        (`sync/<bloque>.json`, plan §7). Puede no existir. Fuera de los archivos del bloque: ni
        las versiones ni copiar el bloque se lo llevan. `InvalidName` con un id no válido."""

    # Archivos de la pizarra (D84, D140, D175): las imágenes pegadas y las animaciones de los
    # post-its (`html`), por su contenido. Un nombre es `<sha256>.<ext>`: la misma imagen
    # pegada dos veces es un solo archivo, y nunca se borra uno (una versión vieja o un
    # deshacer pueden volver a necesitarlo).
    @abstractmethod
    def save_board_file(self, project_id: str, data: bytes, ext: str) -> str:
        """Guarda `data` y devuelve su nombre; si ya estaba, no lo vuelve a escribir."""

    @abstractmethod
    def board_file(self, project_id: str, name: str):
        """Ruta local de un archivo de la pizarra. `InvalidName` si el nombre no es
        `<sha256>.<ext>` de una imagen o una animación (`html`); `NotFound` si no existe."""

    @abstractmethod
    def load_proposals(self, project_id: str) -> list:
        """Propuestas de los agentes, pendientes y resueltas (D75); [] si no hay."""

    @abstractmethod
    def save_proposals(self, project_id: str, proposals: list) -> None: ...

    # Los paquetes que usa el proyecto (docs/PLAN_PAQUETES.md §3, P25): `board/packs.lock` en
    # local, `{id: {"version", "digest"}}`. Lo reescribe cada ejecución; al abrir se compara
    # con lo cargado (falta uno: *paquete no instalado*; otra versión: aviso).
    @abstractmethod
    def load_pack_lock(self, project_id: str) -> dict:
        """{id: {"version", "digest"}}; {} si no hay (proyectos de antes de FF 10.1)."""

    @abstractmethod
    def save_pack_lock(self, project_id: str, lock: dict) -> None: ...

    # La conversación con los agentes (D164): `agent/` en local, fuera de `board/` y `blocks/`,
    # así que ni las versiones la copian ni restaurar la toca. `chat.jsonl` son los eventos del
    # chat, uno por línea; `review.jsonl`, los del revisor (`AGENT_CHATS`); los demás son un
    # JSON cada uno (`AGENT_FILES`).
    @abstractmethod
    def load_agent_chat(self, project_id: str, name: str = "chat") -> list:
        """Los eventos de la conversación `name` (una de `AGENT_CHATS`; si no, `InvalidName`)
        en orden; [] si no hay. Una línea que no se puede leer (la última, cortada por un
        apagón a mitad de escribirla) se salta: nunca impide abrir."""

    @abstractmethod
    def append_agent_chat(self, project_id: str, events: list, name: str = "chat") -> None:
        """Añade eventos al final de la conversación `name`; nunca reescribe los de antes."""

    @abstractmethod
    def load_agent_file(self, project_id: str, name: str) -> dict:
        """`name` es uno de `AGENT_FILES` (si no, `InvalidName`); {} si no hay o no se lee."""

    @abstractmethod
    def save_agent_file(self, project_id: str, name: str, data: dict) -> None: ...

    # Los mensajes de cada hilo (D165), aparte de `threads.json`, para pedir el historial de
    # uno sin cargar los demás: `agent/threads/<id>.jsonl` en local. El id, como los de bloque
    # (`[A-Za-z0-9_-]`, hasta 64): otro nombre es `InvalidName`.
    @abstractmethod
    def load_agent_thread(self, project_id: str, thread_id: str) -> list:
        """Los eventos del hilo en orden; [] si no hay. Una línea cortada se salta."""

    @abstractmethod
    def append_agent_thread(self, project_id: str, thread_id: str, events: list) -> None:
        """Añade eventos al final del hilo; nunca reescribe los de antes."""

    @abstractmethod
    def delete_agent_thread(self, project_id: str, thread_id: str) -> None:
        """Borra los mensajes del hilo (no está, no pasa nada)."""

    # Los ajustes del agente de un proyecto (D168, D169): la tabla `[agentes]` de su
    # `project.toml` en local. Guardarlos nunca toca el resto del `project.toml` (el id).
    @abstractmethod
    def load_project_agent_settings(self, project_id: str) -> dict:
        """{} si el proyecto no tiene ninguno."""

    @abstractmethod
    def save_project_agent_settings(self, project_id: str, data: dict) -> None: ...

    # ------------------------------------------------------------ unidades (D182)
    @abstractmethod
    def load_units(self) -> dict:
        """Las unidades en pantalla del workspace tal como están guardadas ({} si no hay)."""

    @abstractmethod
    def save_units(self, units: dict) -> None: ...

    # ------------------------------------------- perfil de fabricación (D31, PLAN_V020 V8)
    # Un Markdown del workspace (`profile/fabricacion.md` en local) con lo que el ingeniero
    # puede fabricar: máquinas, materiales, tolerancias, qué se externaliza y a quién. Lo leen
    # los agentes en su prompt; ningún cálculo lo lee aún.
    @abstractmethod
    def load_manufacturing_profile(self) -> str | None:
        """El texto guardado, o None si no hay ninguno."""

    @abstractmethod
    def save_manufacturing_profile(self, text: str) -> None: ...

    # ----------------------------------------- librería del workspace (PLAN_V020 V14, V15)
    # Las fichas de componentes del usuario, en el formato de las de los paquetes (TOML), por
    # su clave (`names.check_ficha_key`; otra es `InvalidName`); en local,
    # `library/<tipo>s/<clave>.toml`. El almacenamiento guarda el texto tal cual: lo que valida
    # el núcleo (`[meta]`) es de `pizarra.library`. El stock va aparte, por clave (una ficha de
    # un paquete también puede tenerlo); `cantidad` None es «desconocida», nunca 0 (D33).
    @abstractmethod
    def library_dir(self):
        """Carpeta local de la librería, la que lee un paquete (`ctx.library`), o None si el
        almacenamiento no la tiene. Puede no existir aún."""

    @abstractmethod
    def list_library_fichas(self) -> dict:
        """{clave: texto TOML} de todas las fichas; {} si no hay ninguna."""

    @abstractmethod
    def load_library_ficha(self, key: str) -> str | None:
        """El texto de la ficha, o None si no está."""

    @abstractmethod
    def save_library_ficha(self, key: str, type_: str, text: str) -> None:
        """Guarda la ficha con su tipo (`names.check_ficha_type`). Si estaba con otro tipo,
        la de antes se va a la papelera: una clave, una ficha."""

    @abstractmethod
    def trash_library_ficha(self, key: str) -> None:
        """La ficha a la papelera (D66); `NotFound` si no está. Su stock se queda."""

    @abstractmethod
    def load_stock(self) -> dict:
        """{clave: {cantidad, ubicacion, fecha, nota}}; {} si no hay stock."""

    @abstractmethod
    def save_stock(self, stock: dict) -> None:
        """Lo guarda entero, con el formato de `load_stock` (lo que falte de una entrada,
        vacío)."""

    # ------------------------- copias del perfil al importar otro (PLAN_LIBRERIA L9, D27)
    @abstractmethod
    def profile_copy_dir(self):
        """Carpeta local donde `profile_zip` deja la copia del perfil antes de sustituirlo por
        uno importado, o None si el almacenamiento no la tiene (entonces no se importa: nunca
        se pisa un perfil sin copia). Puede no existir aún. Lo que haya dentro nunca sale como
        carpeta del workspace ni como ficha de la librería."""

    # ---------------------------------------------------------------- versiones (D76)
    # Una versión es una copia de la escena, el estado de los bloques y la miniatura. Se nombra
    # por su `id` (su carpeta, `board/versions/<fecha>-<nombre>/` en local); su `name` pasa por
    # la misma validación que el de un proyecto. Dos versiones nunca se pisan. Cada una se
    # describe como {id, name, created, auto}.
    @abstractmethod
    def list_versions(self, project_id: str) -> list:
        """Las versiones del proyecto, la más nueva primero."""

    @abstractmethod
    def save_version(self, project_id: str, name: str, elements: list, block_state: dict,
                     thumbnail: bytes | None, auto: bool = False) -> dict:
        """Se lleva también los archivos de salida de todos los bloques (D93)."""

    @abstractmethod
    def restore_block_files(self, project_id: str, version_id: str) -> None:
        """Los archivos de los bloques vuelven a ser los de la versión; los que no estaban en
        ella se van. Una versión de antes de FF 4.4 no tiene archivos: los bloques quedan sin."""

    @abstractmethod
    def load_version(self, project_id: str, version_id: str) -> dict:
        """{elements, blocks, info}; `NotFound` si no existe."""

    @abstractmethod
    def load_version_thumbnail(self, project_id: str, version_id: str) -> bytes | None: ...

    @abstractmethod
    def rename_version(self, project_id: str, version_id: str, name: str) -> dict: ...

    @abstractmethod
    def trash_version(self, project_id: str, version_id: str) -> None:
        """A la Papelera del sistema, nunca se borra en el sitio (D66)."""

    @abstractmethod
    def load_thumbnail(self, project_id: str) -> bytes | None: ...

    @abstractmethod
    def save_thumbnail(self, project_id: str, png: bytes) -> None: ...

    @abstractmethod
    def workdir(self, project_id: str):
        """Carpeta local donde trabaja el agente de ese proyecto (su `cwd`, plan §4)."""
