"""Diálogo moderno de Windows para elegir archivos o una carpeta (`IFileOpenDialog`), el mismo
que el «Abrir» de cualquier programa, llamado por COM con ctypes (sin dependencias).

Lo abre el backend, que es otro proceso que la ventana de la app: si no se hace nada, Windows
lo deja detrás (un proceso en segundo plano no puede ponerse delante). Por eso su dueño es la
ventana que está delante al pedirlo (la de la app, donde el usuario acaba de pulsar) y, mientras
dura, la entrada de este hilo se une a la de esa ventana, que es lo que deja que el diálogo
salga delante y con el foco (R38).

Solo Windows. Se llama desde un hilo del servidor (bloquea hasta que el usuario elige).
"""
import ctypes
from ctypes import POINTER, WINFUNCTYPE, byref, c_uint, c_void_p, c_wchar_p, wintypes

from pizarra import i18n

_ole32 = ctypes.windll.ole32
_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

_ole32.CoCreateInstance.argtypes = [c_void_p, c_void_p, wintypes.DWORD, c_void_p, POINTER(c_void_p)]
_ole32.CoTaskMemFree.argtypes = [c_void_p]
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, text):
        super().__init__()
        _ole32.CLSIDFromString(c_wchar_p("{" + text + "}"), byref(self))


class _FilterSpec(ctypes.Structure):
    _fields_ = [("name", c_wchar_p), ("spec", c_wchar_p)]


CLSID_FileOpenDialog = "DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7"
IID_IFileOpenDialog = "d57c7288-d4ad-4768-be02-9d969532d960"
CLSCTX_INPROC_SERVER = 1
COINIT_APARTMENTTHREADED = 2
FOS_PICKFOLDERS = 0x20
FOS_FORCEFILESYSTEM = 0x40
FOS_ALLOWMULTISELECT = 0x200
FOS_PATHMUSTEXIST = 0x800
FOS_FILEMUSTEXIST = 0x1000
SIGDN_FILESYSPATH = 0x80058000
ERROR_CANCELLED = ctypes.c_long(0x800704C7).value      # HRESULT de «Cancelar»

# Posiciones en la tabla de métodos (IUnknown, IModalWindow, IFileDialog, IFileOpenDialog).
_RELEASE, _SHOW = 2, 3
_SET_FILE_TYPES, _SET_OPTIONS, _GET_OPTIONS, _SET_TITLE = 4, 9, 10, 17
_GET_RESULTS = 27
_ITEM_GET_DISPLAY_NAME = 5            # IShellItem
_ARRAY_GET_COUNT, _ARRAY_GET_ITEM = 7, 8   # IShellItemArray


def _method(obj, index, *argtypes):
    vtable = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
    return WINFUNCTYPE(ctypes.HRESULT, c_void_p, *argtypes)(vtable[index])


def _call(obj, index, argtypes=(), *args):
    return _method(obj, index, *argtypes)(obj, *args)


def _release(obj):
    if obj:
        _method(obj, _RELEASE)(obj)


def _path_of(item):
    out = c_wchar_p()
    _call(item, _ITEM_GET_DISPLAY_NAME, (c_uint, POINTER(c_wchar_p)), SIGDN_FILESYSPATH, byref(out))
    try:
        return out.value
    finally:
        _ole32.CoTaskMemFree(ctypes.cast(out, c_void_p))


def _ask(title, folders, multiple, patterns):
    """Rutas elegidas, o [] si se cancela."""
    _ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    dialog = c_void_p()
    try:
        _ole32.CoCreateInstance(byref(_GUID(CLSID_FileOpenDialog)), None, CLSCTX_INPROC_SERVER,
                                byref(_GUID(IID_IFileOpenDialog)), byref(dialog))
        opts = c_uint()
        _call(dialog, _GET_OPTIONS, (POINTER(c_uint),), byref(opts))
        flags = opts.value | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST
        flags |= FOS_PICKFOLDERS if folders else FOS_FILEMUSTEXIST
        if multiple:
            flags |= FOS_ALLOWMULTISELECT
        _call(dialog, _SET_OPTIONS, (c_uint,), flags)
        _call(dialog, _SET_TITLE, (c_wchar_p,), title)
        if patterns and not folders:
            specs = (_FilterSpec * (len(patterns) + 1))(
                *[_FilterSpec(name, spec) for name, spec in patterns], _FilterSpec(i18n.t("dialogo.todos"), "*.*"))
            _call(dialog, _SET_FILE_TYPES, (c_uint, c_void_p), len(specs), specs)
        owner = _user32.GetForegroundWindow()
        mine = _kernel32.GetCurrentThreadId()
        theirs = _user32.GetWindowThreadProcessId(owner, None) if owner else 0
        joined = bool(theirs and theirs != mine and _user32.AttachThreadInput(mine, theirs, True))
        try:
            _call(dialog, _SHOW, (wintypes.HWND,), owner)
        except OSError as exc:
            if exc.winerror == ERROR_CANCELLED:
                return []
            raise
        finally:
            if joined:
                _user32.AttachThreadInput(mine, theirs, False)
        items = c_void_p()
        _call(dialog, _GET_RESULTS, (POINTER(c_void_p),), byref(items))
        try:
            count = wintypes.DWORD()
            _call(items, _ARRAY_GET_COUNT, (POINTER(wintypes.DWORD),), byref(count))
            paths = []
            for i in range(count.value):
                item = c_void_p()
                _call(items, _ARRAY_GET_ITEM, (wintypes.DWORD, POINTER(c_void_p)), i, byref(item))
                try:
                    paths.append(_path_of(item))
                finally:
                    _release(item)
            return paths
        finally:
            _release(items)
    finally:
        _release(dialog)
        _ole32.CoUninitialize()


def choose_files(title, patterns=(), multiple=True):
    """`patterns`: [(nombre, "*.a;*.b")]. Devuelve las rutas elegidas, [] si se cancela."""
    return _ask(title, False, multiple, list(patterns))


def choose_folder(title):
    """La carpeta elegida, o None si se cancela."""
    got = _ask(title, True, False, ())
    return got[0] if got else None
