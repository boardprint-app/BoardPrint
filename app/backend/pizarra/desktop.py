"""Acciones del escritorio del usuario: abrir una carpeta en el explorador del sistema o un
archivo con su programa.

La ruta siempre la da el almacenamiento (nunca la interfaz), así que solo se abren carpetas
del workspace y archivos de salida de sus bloques.
"""
import os
import subprocess
import sys
import webbrowser

from pizarra import i18n


def clean_path(path):
    """Quita el prefijo de ruta extendida de Windows (\\\\?\\) que pone Tauri."""
    p = str(path)
    if p.startswith("\\\\?\\UNC\\"):            # \\?\UNC\srv\share -> \\srv\share
        return "\\\\" + p[8:]
    return p[4:] if p.startswith("\\\\?\\") else p


def reveal(path):
    """Abre la carpeta en el Explorador de Windows, el Finder o el gestor de archivos."""
    path = str(path)
    if sys.platform == "win32":
        os.startfile(path)                                   # noqa: S606 (ruta del workspace)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def open_file(path):
    """Abre un archivo con el programa que tenga asignado el sistema (un informe HTML, en el
    navegador). La ruta la da el almacenamiento o una tarjeta de la pizarra."""
    reveal(path)


# «Abrir con» solo existe como diálogo del sistema en Windows (D141); en Mac la flecha de
# *Abrir* no sale hasta que se decida (plan, «sin resolver»).
OPEN_WITH = sys.platform == "win32"


def open_with(path):
    """El «Abrir con» del sistema para elegir el programa (D141)."""
    if not OPEN_WITH:
        raise OSError(i18n.t("escritorio.abrir_con_solo_windows"))
    subprocess.Popen(["rundll32.exe", "shell32.dll,OpenAs_RunDLL", str(path)])


def open_url(url):
    """Abre un enlace de la pizarra en el navegador del sistema (D137). La URL la da la escena
    y ya viene comprobada (`pasted.safe_url`): solo http o https."""
    webbrowser.open(url)


def reveal_file(path):
    """Abre la carpeta del archivo en el explorador con el archivo seleccionado (una carpeta
    se abre a sí misma)."""
    path = str(path)
    if os.path.isdir(path):
        reveal(path)
    elif sys.platform == "win32":
        subprocess.Popen(["explorer", f"/select,{path}"])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])


# Diálogos de Windows: el moderno por COM (`windialog`, R38), delante de la ventana de la app.
# Por PowerShell (STA, que lo exige) solo si el de COM falla: es el de WinForms, que en la
# carpeta es el antiguo y sale detrás de la app. Imprime la ruta en UTF-8, o nada.
_WIN_DIALOG = r'''
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Windows.Forms
$owner = New-Object System.Windows.Forms.Form -Property @{TopMost = $true; ShowInTaskbar = $false}
$d = New-Object System.Windows.Forms.OpenFileDialog
$d.Title = $env:PIZARRA_TITLE
$d.Filter = $env:PIZARRA_FILTER
$d.Multiselect = ($env:PIZARRA_MULTI -eq "1")
if ($d.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) { $d.FileNames }
$owner.Dispose()
'''

# Carpeta: el diálogo moderno de Windows es el de archivos con «elegir carpeta», que en
# WinForms (.NET Framework de PowerShell 5.1) no existe; el FolderBrowserDialog sí.
_WIN_FOLDER = r'''
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Windows.Forms
$owner = New-Object System.Windows.Forms.Form -Property @{TopMost = $true; ShowInTaskbar = $false}
$d = New-Object System.Windows.Forms.FolderBrowserDialog
$d.Description = $env:PIZARRA_TITLE
$d.ShowNewFolderButton = $true
if ($d.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) { $d.SelectedPath }
$owner.Dispose()
'''


def _powershell(script, **env):
    r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", script],
                       capture_output=True, text=True, encoding="utf-8",
                       env=dict(os.environ, **env),
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        raise OSError(r.stderr.strip() or f"PowerShell salió con {r.returncode}")
    return [line.strip() for line in r.stdout.splitlines() if line.strip()]


def choose_file(title, patterns):
    """Diálogo del sistema para elegir un archivo; devuelve su ruta, o None si se cancela.
    `patterns`: [(nombre, "*.a;*.b")]. Bloquea hasta que el usuario elige: se llama desde un
    hilo del servidor, nunca desde el bucle de eventos."""
    if sys.platform == "win32":
        got = choose_files(title, patterns, multiple=False)
        return got[0] if got else None
    if sys.platform == "darwin":
        r = subprocess.run(["osascript", "-e",
                            f'POSIX path of (choose file with prompt "{title}")'],
                           capture_output=True, text=True)
        return r.stdout.strip() or None          # cancelar sale con error y sin ruta
    import tkinter
    from tkinter import filedialog
    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        types = [(name, p.replace(";", " ")) for name, p in patterns] + [(i18n.t("dialogo.todos"), "*")]
        return filedialog.askopenfilename(title=title, filetypes=types) or None
    finally:
        root.destroy()


def choose_files(title, patterns=(), multiple=True):
    """Como `choose_file`, pero con varios a la vez (*Archivo* de la pizarra, D59): devuelve
    la lista de rutas, vacía si se cancela."""
    if sys.platform == "win32":
        try:
            from pizarra import windialog
            return windialog.choose_files(title, patterns, multiple)
        except OSError:
            pass                                  # COM no disponible: el de WinForms
        filt = "|".join([f"{name} ({p})|{p}" for name, p in patterns]
                         + [f"{i18n.t('dialogo.todos')} (*.*)|*.*"])
        return _powershell(_WIN_DIALOG, PIZARRA_TITLE=title, PIZARRA_FILTER=filt,
                           PIZARRA_MULTI="1" if multiple else "0")
    if sys.platform == "darwin":
        multi = " with multiple selections allowed" if multiple else ""
        r = subprocess.run(["osascript", "-e",
                            f'set fs to (choose file with prompt "{title}"{multi})\n'
                            'set out to ""\nrepeat with f in (fs as list)\n'
                            'set out to out & POSIX path of f & linefeed\nend repeat\nout'],
                           capture_output=True, text=True)
        return [x for x in r.stdout.splitlines() if x.strip()]
    import tkinter
    from tkinter import filedialog
    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        return list(filedialog.askopenfilenames(title=title) or ())
    finally:
        root.destroy()


def choose_folder(title):
    """Diálogo del sistema para elegir una carpeta; su ruta, o None si se cancela."""
    if sys.platform == "win32":
        try:
            from pizarra import windialog
            return windialog.choose_folder(title)
        except OSError:
            pass                                  # COM no disponible: el de WinForms
        got = _powershell(_WIN_FOLDER, PIZARRA_TITLE=title)
        return got[0] if got else None
    if sys.platform == "darwin":
        r = subprocess.run(["osascript", "-e",
                            f'POSIX path of (choose folder with prompt "{title}")'],
                           capture_output=True, text=True)
        return r.stdout.strip() or None
    import tkinter
    from tkinter import filedialog
    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        return filedialog.askdirectory(title=title) or None
    finally:
        root.destroy()
