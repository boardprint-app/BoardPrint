"""Correo de Outlook en la pizarra (docs/PLAN_M365.md §6, §9: M5, M10).

Reglas: el `.eml` y sus adjuntos nunca salen de `<proyecto>/microsoft365/`, y un asunto con
caracteres prohibidos de Windows se limpia; un `referenceAttachment` nunca se descarga (se
avisa); las imágenes del cuerpo no se traen; el mismo correo no se repite. Un borrador nunca
llama a `/send` ni a `sendMail`; su cuerpo va escapado; sus adjuntos son exactamente los
archivos dados; una dirección mal escrita se rechaza antes de llamar a Graph. `leer_archivo`
lee un `.eml`: cabecera con remitente, fecha, asunto y adjuntos, y el texto, también el de un
correo solo HTML, sin etiquetas.

Ejecutar desde app/backend:  python -m unittest tests.test_m365_mail -v
"""
import base64
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path

from pizarra import m365_files, m365_mail, read_files, scene
from pizarra.validation import ValidationError

from tests.helpers import new_board

MIME = b"From: Ana <ana@ejemplo.com>\r\nSubject: Oferta\r\n\r\nHola\r\n"


class FakeMailGraph:
    def __init__(self, attachments=(), subject='Oferta: "brazo" v2/3?', has=True):
        self.calls = []
        self.subject, self.has = subject, has
        self.attachments = list(attachments)

    def get(self, path, **kw):
        self.calls.append(("GET", path))
        if "/attachments/" in path:
            aid = path.rsplit("/", 1)[1]
            att = next(a for a in self.attachments if a["id"] == aid)
            return {**att, "contentBytes": base64.b64encode(att["_data"]).decode()}
        return {"id": "m1", "subject": self.subject, "hasAttachments": self.has,
                "webLink": "https://outlook.live.com/m1",
                "from": {"emailAddress": {"name": "Ana", "address": "ana@ejemplo.com"}}}

    def get_all(self, path, **kw):
        self.calls.append(("GET_ALL", path))
        return [{k: v for k, v in a.items() if k != "_data"} for a in self.attachments]

    def download(self, path, **kw):
        self.calls.append(("DOWNLOAD", path))
        return MIME

    def post(self, path, payload, **kw):
        self.calls.append(("POST", path, payload))
        if path.endswith("createUploadSession"):
            return {"uploadUrl": "https://subida.example/att"}
        return {"id": "borrador1", "webLink": "https://outlook.live.com/borrador1"}

    def request(self, method, url, body=None, auth=True, headers=None, **kw):
        self.calls.append(("CHUNK", url, auth, len(body)))


def att(aid, name, kind, data=b"", inline=False):
    return {"id": aid, "name": name, "@odata.type": kind, "isInline": inline, "_data": data}


class Traer(unittest.TestCase):
    def setUp(self):
        self.board = new_board()
        self.folder = (Path(self.board.dir) / m365_files.FOLDER).resolve()

    def test_eml_con_el_asunto_limpio_dentro_de_la_carpeta(self):
        new, notes, mail = m365_mail.bring_message(self.board, FakeMailGraph(), "m1", x=0, y=0)
        path = self.board.card_path(mail)
        self.assertEqual(path.parent.resolve(), self.folder)
        self.assertEqual(path.suffix, ".eml")
        for ch in '<>:"/\\|?*':
            self.assertNotIn(ch, path.name)
        self.assertEqual(path.read_bytes(), MIME)
        self.assertEqual(mail["customData"]["m365"]["service"], "correo")

    def test_adjuntos_si_se_piden_y_nunca_enlaces_ni_imagenes_del_cuerpo(self):
        g = FakeMailGraph([att("a1", "../plano.pdf", m365_mail.FILE_ATT, b"%PDF"),
                           att("a2", "logo.png", m365_mail.FILE_ATT, b"png", inline=True),
                           att("a3", "Carpeta compartida", "#microsoft.graph.referenceAttachment"),
                           att("a4", "Re: pedido", m365_mail.ITEM_ATT)])
        new, notes, mail = m365_mail.bring_message(self.board, g, "m1", True, 0, 0)
        names = sorted(self.board.card_path(e).name for e in new)
        self.assertEqual(len(new), 3)                        # correo + pdf + correo adjunto
        self.assertIn("_plano.pdf", names)
        self.assertTrue(any(n.startswith("Re_ pedido") and n.endswith(".eml") for n in names))
        self.assertEqual(len(notes), 1)
        self.assertIn("Carpeta compartida", notes[0])
        for e in new:
            self.assertEqual(self.board.card_path(e).parent.resolve(), self.folder)
        self.assertFalse(any(c[0] == "GET" and c[1].endswith("/a3") for c in g.calls))

    def test_un_correo_nunca_cae_encima_de_otra_tarjeta(self):
        # E2E de FF 7.5: el `.eml` caía encima del Excel traído antes al mismo centro de vista.
        local = Path(self.board.dir) / "notas.txt"
        local.write_text("x", encoding="utf-8")
        card = self.board.add_cards([local], 0, 0)[0]
        g = FakeMailGraph([att("a1", "plano.pdf", m365_mail.FILE_ATT, b"%PDF")])
        new, _, mail = m365_mail.bring_message(self.board, g, "m1", True, 0, 0)
        boxes = [scene.bbox(e) for e in [card, *new]]
        for i, (ax0, ay0, ax1, ay1) in enumerate(boxes):
            for bx0, by0, bx1, by1 in boxes[i + 1:]:
                self.assertTrue(bx0 >= ax1 or bx1 <= ax0 or by0 >= ay1 or by1 <= ay0)
        self.assertEqual(new[1]["x"], mail["x"] + 24)       # el adjunto, debajo de su correo

    def test_la_bandeja_de_entrada_va_con_el_id_inbox(self):
        # E2E de FF 7.5: el panel abre `inbox` y el selector la enseñaba dos veces (el alias y
        # la carpeta con su id de Graph).
        class G:
            def get(self, path, **kw):
                return {"id": "AQMk-inbox"}

            def get_all(self, path, **kw):
                return [{"id": "AQMk-inbox", "displayName": "Bandeja de entrada"},
                        {"id": "AQMk-borr", "displayName": "Borradores"}]
        self.assertEqual([f["id"] for f in m365_mail.folders(G())], ["inbox", "AQMk-borr"])

    def test_el_mismo_correo_no_se_repite(self):
        g = FakeMailGraph(has=False)
        m365_mail.bring_message(self.board, g, "m1", x=0, y=0)
        new, _, _ = m365_mail.bring_message(self.board, g, "m1", x=0, y=0)
        self.assertEqual(new, [])
        self.assertEqual(sum(1 for c in g.calls if c[0] == "DOWNLOAD"), 1)


class Borrador(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_nunca_envia_y_adjunta_solo_lo_dado(self):
        small = self.dir / "informe.pdf"
        small.write_bytes(b"x" * 10)
        big = self.dir / "modelo.step"
        big.write_bytes(b"y" * (m365_mail.INLINE_MAX + 1))
        (self.dir / "otro.txt").write_bytes(b"no")
        g = FakeMailGraph()
        got = m365_mail.draft(g, "ana@ejemplo.com; luis@ejemplo.com", None, "Informe",
                              "Hola <b>Ana</b>\n\nAdjunto.", [small, big])
        self.assertEqual(got, {"id": "borrador1", "web_link": "https://outlook.live.com/borrador1"})
        for c in g.calls:
            url = c[1].lower()
            self.assertNotIn("/send", url)
            self.assertNotIn("sendmail", url)
        create = next(c for c in g.calls if c[0] == "POST" and c[1] == "/me/messages")[2]
        self.assertEqual([a["name"] for a in create["attachments"]], ["informe.pdf"])
        session = next(c for c in g.calls if c[0] == "POST" and c[1].endswith("createUploadSession"))
        self.assertEqual(session[2]["AttachmentItem"]["name"], "modelo.step")
        self.assertEqual(sum(c[3] for c in g.calls if c[0] == "CHUNK"), m365_mail.INLINE_MAX + 1)
        self.assertTrue(all(c[2] is False for c in g.calls if c[0] == "CHUNK"))
        self.assertEqual([r["emailAddress"]["address"] for r in create["toRecipients"]],
                         ["ana@ejemplo.com", "luis@ejemplo.com"])

    def test_cuerpo_escapado(self):
        html = m365_mail.body_html('<script>x</script>\nlinea 2\n\notro')
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertEqual(html.count("<p>"), 2)
        self.assertIn("<br>", html)

    def test_direccion_mal_escrita_antes_de_graph(self):
        g = FakeMailGraph()
        with self.assertRaises(ValidationError):
            m365_mail.draft(g, "ana-sin-arroba", None, "Hola", "x")
        with self.assertRaises(ValidationError):
            m365_mail.draft(g, "ana@ejemplo.com", None, "  ", "x")
        self.assertEqual(g.calls, [])


class LeerEml(unittest.TestCase):
    def _write(self, msg):
        path = Path(tempfile.mkdtemp()) / "c.eml"
        path.write_bytes(bytes(msg))
        return path

    def test_texto_cabecera_y_adjuntos(self):
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = "Ana <ana@ejemplo.com>", "yo@ejemplo.com", "Oferta"
        msg["Date"] = "Fri, 20 Nov 2026 10:00:00 +0100"
        msg.set_content("Precio: 1200 EUR\nPlazo: 3 semanas")
        msg.add_attachment(b"%PDF", maintype="application", subtype="pdf", filename="oferta.pdf")
        chunks = read_files._eml(self._write(msg))
        head = chunks[0].text
        for want in ("Ana <ana@ejemplo.com>", "Oferta", "2026", "oferta.pdf"):
            self.assertIn(want, head)
        self.assertIn("1200 EUR", chunks[1].text)
        self.assertTrue(read_files.readable("x.EML"))

    def test_solo_html_sin_etiquetas(self):
        msg = EmailMessage()
        msg["From"], msg["Subject"] = "b@ejemplo.com", "HTML"
        msg.set_content("<html><head><style>p{color:red}</style></head><body><p>Hola</p>"
                        "<div>Precio <b>99</b> &euro;</div></body></html>", subtype="html")
        text = read_files._eml(self._write(msg))[1].text
        self.assertEqual(text, "Hola\nPrecio 99 €")


if __name__ == "__main__":
    unittest.main()
