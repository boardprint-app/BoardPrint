"""Carpetas sincronizadas con la nube (docs/PLAN_PIZARRA.md R3, D186).

Ejecutar desde app/backend:  python -m unittest tests.test_cloud -v
"""
import unittest

from pizarra.cloud import service

WIN_ENV = {"OneDrive": r"C:\Users\ana\OneDrive",
           "OneDriveCommercial": r"C:\Users\ana\OneDrive - Taller SL"}


class Windows(unittest.TestCase):
    def s(self, path, env=WIN_ENV):
        return service(path, env=env, platform="win32")

    def test_dentro_de_onedrive_siempre_avisa_tambien_con_otras_mayusculas(self):
        self.assertEqual(self.s(r"C:\Users\ana\OneDrive\Documentos\BoardPrint\Personal"), "OneDrive")
        self.assertEqual(self.s(r"c:\users\ANA\onedrive\Documentos"), "OneDrive")
        self.assertEqual(self.s(r"C:\Users\ana\OneDrive - Taller SL\Proyectos"), "OneDrive")

    def test_onedrive_por_su_nombre_aunque_no_haya_variable(self):
        self.assertEqual(self.s(r"D:\OneDrive - Otra\x", env={}), "OneDrive")

    def test_dropbox_google_drive_e_icloud(self):
        self.assertEqual(self.s(r"C:\Users\ana\Dropbox\BoardPrint", env={}), "Dropbox")
        self.assertEqual(self.s(r"G:\Mi unidad\BoardPrint", env={}), "Google Drive")
        self.assertEqual(self.s(r"C:\Users\ana\iCloudDrive\BoardPrint", env={}), "iCloud")

    def test_fuera_de_la_nube_nunca_avisa(self):
        self.assertIsNone(self.s(r"C:\Users\ana\Documents\BoardPrint\Personal"))
        self.assertIsNone(self.s(r"D:\Proyectos"))
        # la raíz de la variable no basta para que todo el disco sea OneDrive
        self.assertIsNone(self.s(r"C:\Users\ana\Documents", env={"OneDrive": "C:\\"}))


class Mac(unittest.TestCase):
    def s(self, path):
        return service(path, env={}, platform="darwin")

    def test_icloud_y_cloudstorage(self):
        self.assertEqual(self.s("/Users/ana/Library/Mobile Documents/com~apple~CloudDocs/BP"), "iCloud")
        self.assertEqual(self.s("/Users/ana/Library/CloudStorage/OneDrive-Personal/BP"), "OneDrive")
        self.assertEqual(self.s("/Users/ana/Library/CloudStorage/GoogleDrive-ana@x.com/BP"), "Google Drive")
        self.assertEqual(self.s("/Users/ana/Library/CloudStorage/Dropbox/BP"), "Dropbox")

    def test_fuera_de_la_nube_nunca_avisa(self):
        self.assertIsNone(self.s("/Users/ana/Documents/BoardPrint/Personal"))


if __name__ == "__main__":
    unittest.main()
