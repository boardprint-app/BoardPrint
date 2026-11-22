"""Correo de Outlook en la pizarra (docs/PLAN_M365.md §6: M5, M10, M11).

Un correo entra como `.eml` (su MIME, `/messages/{id}/$value`) y sus adjuntos como tarjetas
sueltas si se piden: `fileAttachment` como archivo, `itemAttachment` (un correo adjunto) como
`.eml`; un `referenceAttachment` (un enlace) no se descarga, y se dice. Todo cae en
`<proyecto>/microsoft365/`, como los archivos de la nube (M6).

El agente redacta **borradores** (`draft`): quedan en *Borradores* y se envían desde Outlook
(M5). Aquí no hay nada que llame a `/send` ni a `sendMail`, y la app no pide `Mail.Send`.
"""
import base64
import html
import re
from pathlib import Path
from urllib.parse import quote

from pizarra.m365_files import place, safe_name, sha256, write_new
from pizarra.validation import ValidationError

MESSAGE_SELECT = "id,subject,from,receivedDateTime,hasAttachments,bodyPreview,webLink,isRead"
INLINE_MAX = 3 * 1024 * 1024        # un adjunto de más va por sesión de subida
ATTACH_MAX = 150 * 1024 * 1024      # lo que admite Outlook por adjunto
CHUNK = 320 * 1024 * 12             # ~3,75 MiB por trozo, múltiplo de 320 KiB
MAX_RECIPIENTS = 50
_EMAIL = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$")
FILE_ATT = "#microsoft.graph.fileAttachment"
ITEM_ATT = "#microsoft.graph.itemAttachment"


def _sender(msg):
    addr = ((msg.get("from") or {}).get("emailAddress")) or {}
    return {"name": addr.get("name") or "", "address": addr.get("address") or ""}


def message_view(msg):
    """Lo que el panel y el agente ven de un correo."""
    return {"id": msg.get("id"), "subject": msg.get("subject") or "",
            "from": _sender(msg), "received": msg.get("receivedDateTime") or "",
            "has_attachments": bool(msg.get("hasAttachments")),
            "preview": (msg.get("bodyPreview") or "")[:300],
            "web_link": msg.get("webLink") or "", "read": bool(msg.get("isRead", True))}


def folders(graph):
    """Las carpetas del buzón. La bandeja de entrada va con el id `inbox`, el mismo que usa el
    panel al abrirse: si no, el selector la enseña dos veces."""
    inbox = graph.get("/me/mailFolders/inbox?$select=id").get("id")
    return [{"id": "inbox" if f.get("id") == inbox else f.get("id"),
             "name": f.get("displayName") or "",
             "total": f.get("totalItemCount") or 0, "unread": f.get("unreadItemCount") or 0}
            for f in graph.get_all("/me/mailFolders?$top=100")]


def messages(graph, folder="inbox", search=None, top=50):
    """Los últimos correos de una carpeta, o los que coinciden con `search` en todo el buzón
    (`$search` de Graph no admite `$orderby`: vuelven por relevancia)."""
    top = max(1, min(int(top or 50), 100))
    text = str(search or "").strip().replace('"', "")
    if text:
        path = f'/me/messages?$search="{quote(text, safe="")}"&$top={top}&$select={MESSAGE_SELECT}'
    else:
        path = (f"/me/mailFolders/{quote(folder or 'inbox', safe='')}/messages?$top={top}"
                f"&$orderby=receivedDateTime desc&$select={MESSAGE_SELECT}")
    return [message_view(m) for m in graph.get(path).get("value") or []]


def card_for_message(board, message_id):
    for el in board.elements:
        if el.get("isDeleted") or el.get("type") != "embeddable":
            continue
        m = (el.get("customData") or {}).get("m365") or {}
        if m.get("service") == "correo" and m.get("message_id") == message_id and \
                not m.get("attachment_id"):
            return el
    return None


def _add_card(board, path, x, y, author, m365):
    el = board.add_cards([path], x, y, author=author)[0]
    el["customData"]["m365"] = m365
    return el


def bring_message(board, graph, message_id, with_attachments=False, x=None, y=None,
                  author="user"):
    """El correo como `.eml` y, con `with_attachments`, sus adjuntos debajo (M10). Devuelve
    (tarjetas nuevas, avisos, la del correo). Un correo ya en la pizarra no se repite, pero
    sus adjuntos sí se pueden pedir después."""
    mid = quote(str(message_id or ""), safe="")
    if not mid:
        raise ValidationError("falta el id del correo")
    meta = graph.get(f"/me/messages/{mid}?$select={MESSAGE_SELECT}")
    view = message_view(meta)
    x, y = place(board, x, y)
    new, notes = [], []
    mail = card_for_message(board, view["id"])
    if mail is None:
        data = graph.download(f"/me/messages/{mid}/$value")
        path = write_new(board, safe_name(view["subject"], "correo") + ".eml", data)
        mail = _add_card(board, path, x, y, author, {
            "service": "correo", "message_id": view["id"], "name": view["subject"],
            "web_url": view["web_link"], "sha256": sha256(data)})
        new.append(mail)
    if with_attachments and view["has_attachments"]:
        top = mail["y"] + mail["height"] + 16
        for att in graph.get_all(f"/me/messages/{mid}/attachments?$select=id,name,size,isInline"):
            kind, name = att.get("@odata.type"), att.get("name") or "adjunto"
            if att.get("isInline"):
                continue                     # las imágenes del cuerpo del correo
            if _attachment_card(board, view["id"], att.get("id")) is not None:
                continue
            aid = quote(att.get("id") or "", safe="")
            if kind == FILE_ATT:
                full = graph.get(f"/me/messages/{mid}/attachments/{aid}")
                data = base64.b64decode(full.get("contentBytes") or "")
                filename = name
            elif kind == ITEM_ATT:
                data = graph.download(f"/me/messages/{mid}/attachments/{aid}/$value")
                filename = safe_name(name, "correo") + ".eml"
            else:
                notes.append(f"{name}: es un enlace, no un archivo; ábrelo desde Outlook")
                continue
            path = write_new(board, filename, data)
            el = _add_card(board, path, mail["x"] + 24, top, author, {
                "service": "correo", "message_id": view["id"], "attachment_id": att.get("id"),
                "name": name, "web_url": view["web_link"], "sha256": sha256(data)})
            top += el["height"] + 16
            new.append(el)
    if new:
        board.save()
    return new, notes, mail


def _attachment_card(board, message_id, attachment_id):
    for el in board.elements:
        m = (el.get("customData") or {}).get("m365") or {}
        if not el.get("isDeleted") and m.get("message_id") == message_id and \
                m.get("attachment_id") == attachment_id:
            return el
    return None


def recipients(value, field):
    """Una lista de direcciones (`["a@b.com", …]` o `"a@b.com; c@d.com"`), o ValidationError."""
    if value is None or value == "":
        return []
    items = value if isinstance(value, list) else re.split(r"[;,]", str(value))
    out = []
    for item in items:
        addr = str(item or "").strip()
        if not addr:
            continue
        if not _EMAIL.match(addr):
            raise ValidationError(f"`{field}`: {addr!r} no es una dirección de correo")
        out.append(addr)
    if len(out) > MAX_RECIPIENTS:
        raise ValidationError(f"`{field}`: como mucho {MAX_RECIPIENTS} direcciones")
    return out


def body_html(text):
    """El texto del agente como HTML: escapado (nada de etiquetas suyas) y con sus saltos."""
    paragraphs = re.split(r"\n\s*\n", str(text or "").strip())
    return "".join("<p>" + html.escape(p).replace("\n", "<br>") + "</p>" for p in paragraphs if p)


def draft_payload(to, cc, subject, body, attachments=()):
    """El JSON de `POST /me/messages` (un borrador, M5). `attachments`: (nombre, bytes) de hasta
    `INLINE_MAX`; los mayores se suben después con su sesión (`draft`)."""
    msg = {"subject": str(subject or "").strip(),
           "body": {"contentType": "HTML", "content": body_html(body)},
           "toRecipients": [{"emailAddress": {"address": a}} for a in to],
           "ccRecipients": [{"emailAddress": {"address": a}} for a in cc]}
    small = [{"@odata.type": FILE_ATT, "name": name,
              "contentBytes": base64.b64encode(data).decode("ascii")}
             for name, data in attachments if len(data) <= INLINE_MAX]
    if small:
        msg["attachments"] = small
    return msg


def draft(graph, to, cc, subject, body, paths=()):
    """Crea el borrador en *Borradores* con los archivos de `paths` adjuntos. Devuelve
    `{id, web_link}`. Nunca lo envía (M5)."""
    to, cc = recipients(to, "para"), recipients(cc, "cc")
    if not str(subject or "").strip():
        raise ValidationError("el borrador necesita `asunto`")
    files = []
    for p in paths:
        p = Path(p)
        data = p.read_bytes()
        if len(data) > ATTACH_MAX:
            raise ValidationError(f"{p.name}: pasa de {ATTACH_MAX // (1024 * 1024)} MB, el "
                                  "máximo de Outlook por adjunto")
        files.append((p.name, data))
    created = graph.post("/me/messages", draft_payload(to, cc, subject, body, files))
    mid = quote(created.get("id") or "", safe="")
    for name, data in files:
        if len(data) <= INLINE_MAX:
            continue
        session = graph.post(f"/me/messages/{mid}/attachments/createUploadSession",
                             {"AttachmentItem": {"attachmentType": "file", "name": name,
                                                 "size": len(data)}})
        url, total = session["uploadUrl"], len(data)
        for start in range(0, total, CHUNK):
            part = data[start:start + CHUNK]
            graph.request("PUT", url, body=part, auth=False, headers={
                "Content-Type": "application/octet-stream",
                "Content-Length": str(len(part)),
                "Content-Range": f"bytes {start}-{start + len(part) - 1}/{total}"})
    return {"id": created.get("id"), "web_link": created.get("webLink") or ""}
