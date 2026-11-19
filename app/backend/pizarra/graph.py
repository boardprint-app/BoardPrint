"""Grafo de bloques derivado de la escena y estado "desactualizado" (D14).

Un bloque es un elemento `embeddable` con `customData.kind == "block"`. Una conexión es una
flecha enlazada por los dos extremos a dos bloques: los datos van del inicio al final, de un
puerto de salida a un puerto de entrada del mismo tipo (D88, D94). La flecha guarda sus
puertos en `customData = {kind: "connection", from, to}`; si le falta alguno, solo se
completa cuando hay una única pareja posible (`resolve_ports`).

Una tarjeta de archivo o de carpeta (`customData.kind` `file` o `folder`) es un **nodo fuente**
(D131): no se ejecuta ni tiene estado, tiene una sola salida (`archivo`, del tipo
`archivo.<ext>`, o `carpeta`) y su hash es el del contenido, que da el sondeo (`files.Prober`)
y entra aquí como `sources = {id: FileState}`. Los tipos casan iguales (D88), salvo los de
archivo por prefijo (`accepts`, D132). Una flecha de un bloque a una carpeta no es una entrada
sino un destino de sus salidas (D109): va en `copies`, y si la carpeta alimenta a ese bloque o a
uno de delante, se rechaza como ciclo.

`edges` es `{destino: {puerto_de_entrada: (origen, puerto_de_salida)}}`. Las salidas de un
bloque se guardan por puerto (`outputs[puerto] = {campo: {value, unit, source}}`) y su hash
también (`outputs_hash[puerto]`): lo de detrás solo depende del puerto que le llega.

Estado de un bloque:
- `no_disponible`: pide un conector (`requires`) que no está disponible. Sin error.
- `nunca`: no se ha ejecutado.
- `incompleto`: le falta alguna entrada obligatoria conectada (una opcional, D122, no cuenta),
  o le llega un archivo o una carpeta sin hash (no está, no se lee...; `explain` da el motivo).
- `error`: la última ejecución falló.
- `al_dia`: su hash de entradas coincide con el de la última ejecución y todo lo que tiene
  delante está al día.
- `desactualizado`: en cualquier otro caso. Nunca dispara una ejecución.
"""
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from pizarra import files, i18n

# Tipo de tarjeta -> su único puerto de salida
SOURCE_PORT = {"file": files.FILE, "folder": files.FOLDER}


def _h(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def blocks_in(elements, registry=None):
    """Bloques vivos de la escena. Con `registry`, solo los de un tipo conocido: un bloque de
    un paquete no instalado (o de otra versión) se queda en la pizarra pero no entra en el
    grafo, para que nunca la deje inutilizable (plan R6)."""
    return {e["id"]: e for e in elements
            if e.get("type") == "embeddable" and not e.get("isDeleted")
            and (e.get("customData") or {}).get("kind") == "block"
            and (registry is None or (e.get("customData") or {}).get("blockType") in registry)}


def accepts(input_type, output_type):
    """¿Admite una entrada de `input_type` una salida de `output_type`? Tienen que ser iguales
    (D88), con la única excepción de los archivos (D132): `archivo` admite cualquier
    `archivo.*`. `archivo.step` solo admite `archivo.step` (un `.stp` también lo es)."""
    return input_type == output_type or (input_type == files.FILE and files.is_file_port(output_type))


def sources_in(elements):
    """Tarjetas de archivo y de carpeta vivas de la escena (D131)."""
    return {e["id"]: e for e in elements if not e.get("isDeleted")
            and (e.get("customData") or {}).get("kind") in SOURCE_PORT}


@dataclass(frozen=True)
class SourceType:
    """Lo que el grafo ve de una tarjeta de archivo o de carpeta: una salida, ninguna entrada."""
    title: str
    outputs: dict
    inputs: dict = field(default_factory=dict)
    optional: tuple = ()
    requires: tuple = ()


def source_type(el):
    cd = el.get("customData") or {}
    path = str(cd.get("path") or "")
    name = PurePosixPath(path.replace("\\", "/")).name or SOURCE_PORT[cd["kind"]]
    out = files.port_type(path) if cd["kind"] == "file" else files.FOLDER
    return SourceType(name, {SOURCE_PORT[cd["kind"]]: out})


def arrow_ends(arrow, blocks):
    """`(origen, destino)` si la flecha une dos nodos de `blocks`; si no, `None` (dibujo libre)."""
    src = (arrow.get("startBinding") or {}).get("elementId")
    dst = (arrow.get("endBinding") or {}).get("elementId")
    return (src, dst) if src in blocks and dst in blocks else None


def arrow_ports(arrow):
    """Puertos que guarda la flecha (`customData.kind == "connection"`): `(salida, entrada)`,
    cada uno o `None` si no lo dice."""
    cd = arrow.get("customData") or {}
    if cd.get("kind") != "connection":
        return None, None
    return cd.get("from"), cd.get("to")


def resolve_ports(arrow, src_type, dst_type):
    """`((salida, entrada), None)` o `(None, motivo)`.

    Con los dos puertos en la flecha, tienen que existir y casar (`accepts`). Si falta alguno,
    solo se completa cuando hay una única pareja posible: con dos o más, nunca se elige sola
    (D88); la interfaz pregunta y escribe el puerto en la flecha.
    """
    frm, to = arrow_ports(arrow)
    if frm is not None and frm not in src_type.outputs:
        return None, i18n.t("conexion.sin_salida", bloque=src_type.title, puerto=repr(frm))
    if to is not None and to not in dst_type.inputs:
        return None, i18n.t("conexion.sin_entrada", bloque=dst_type.title, puerto=repr(to))
    outs = [frm] if frm is not None else sorted(src_type.outputs)
    ins = [to] if to is not None else sorted(dst_type.inputs)
    pairs = [(op, ip) for op in outs for ip in ins if accepts(dst_type.inputs[ip], src_type.outputs[op])]
    if not pairs:
        if frm is not None and to is not None:
            return None, i18n.t("conexion.tipos_no_casan", salida=repr(frm),
                                tipo_salida=src_type.outputs[frm], entrada=repr(to),
                                tipo_entrada=dst_type.inputs[to])
        return None, i18n.t("conexion.ninguna_entrada", destino=dst_type.title, origen=src_type.title)
    if len(pairs) > 1:
        return None, i18n.t("conexion.ambigua", origen=src_type.title, destino=dst_type.title)
    return pairs[0], None


def build(elements, registry):
    """Devuelve (edges, problems); ver `connections`."""
    edges, _, problems = connections(elements, registry)
    return edges, problems


def connections(elements, registry):
    """Devuelve (edges, copies, problems).

    edges: {destino: {puerto: (origen, puerto_salida)}}; el origen puede ser una tarjeta de
    archivo o de carpeta. copies: {carpeta: [(bloque, puerto_salida o None, flecha)]}, las
    salidas que van a una carpeta (None: todas las del bloque). problems: lista de dicts
    {arrow, reason}. Se rechazan las conexiones entre puertos que no casan o que no existen,
    las que dejan duda de qué puertos unen, las que ocupan una entrada ya ocupada, las que
    llevan algo a un archivo o de una tarjeta a otra, y las que cerrarían un ciclo (también a
    través de una carpeta).
    """
    blocks = blocks_in(elements, registry)
    srcs = sources_in(elements)
    nodes = {**blocks, **srcs}
    edges, copies, problems = {}, {}, []
    arrows = sorted((e for e in elements if e.get("type") == "arrow" and not e.get("isDeleted")),
                    key=lambda e: e["id"])
    for a in arrows:
        ends = arrow_ends(a, nodes)
        if ends is None:
            continue                      # flecha de dibujo libre, no es una conexión
        src, dst = ends
        if src == dst:
            problems.append({"arrow": a["id"], "reason": i18n.t("conexion.consigo_mismo")})
            continue
        if dst in srcs:
            reason = _copy_problem(a, src, srcs[dst], blocks, registry)
            if reason is None:
                reason = _repeated_copy(a, src, copies.get(dst, ()))
            if reason is None and _reaches(edges, copies, dst, src):
                reason = i18n.t("conexion.ciclo_carpeta")
            if reason:
                problems.append({"arrow": a["id"], "reason": reason})
            else:
                copies.setdefault(dst, []).append((src, arrow_ports(a)[0], a["id"]))
            continue
        src_type = (source_type(srcs[src]) if src in srcs
                    else registry[blocks[src]["customData"]["blockType"]])
        ports, reason = resolve_ports(a, src_type, registry[blocks[dst]["customData"]["blockType"]])
        if ports is None:
            problems.append({"arrow": a["id"], "reason": reason})
            continue
        op, ip = ports
        if ip in edges.get(dst, {}):
            problems.append({"arrow": a["id"], "reason": i18n.t("conexion.entrada_ocupada", entrada=repr(ip))})
            continue
        if _reaches(edges, copies, dst, src):
            problems.append({"arrow": a["id"], "reason": i18n.t("conexion.ciclo")})
            continue
        edges.setdefault(dst, {})[ip] = (src, op)
    return edges, copies, problems


def _copy_problem(arrow, src, card, blocks, registry):
    """Motivo por el que una flecha a una tarjeta no es un destino de salidas, o None."""
    if card["customData"]["kind"] != "folder":
        return i18n.t("conexion.archivo_no_recibe")
    if src not in blocks:
        return i18n.t("conexion.carpeta_solo_bloques")
    frm, _ = arrow_ports(arrow)
    btype = registry[blocks[src]["customData"]["blockType"]]
    if frm is not None and frm not in btype.outputs:
        return i18n.t("conexion.sin_salida", bloque=btype.title, puerto=repr(frm))
    return None


def _repeated_copy(arrow, src, links):
    """Motivo si la flecha repite una salida que ya llega a esa carpeta por otra flecha (todas
    las salidas, `None`, cubren cualquiera): cada ejecución la copiaría dos veces."""
    frm, _ = arrow_ports(arrow)
    for s, port, _ in links:
        if s == src and (port is None or frm is None or port == frm):
            return i18n.t("conexion.copia_repetida")
    return None


def _reaches(edges, copies, start, target):
    """¿Se llega de `start` a `target` siguiendo los datos hacia delante, también de un bloque a
    la carpeta que recibe sus salidas?"""
    downstream = {}
    for dst, ports in edges.items():
        for src, _ in ports.values():
            downstream.setdefault(src, set()).add(dst)
    for folder, links in copies.items():
        for src, _, _ in links:
            downstream.setdefault(src, set()).add(folder)
    stack, seen = [start], set()
    while stack:
        n = stack.pop()
        if n == target:
            return True
        if n in seen:
            continue
        seen.add(n)
        stack.extend(downstream.get(n, ()))
    return False


def required(edges, elements, registry):
    """Las conexiones a entradas obligatorias (D99, D122): las de `edges` sin las que llegan a
    una entrada opcional. Lo de delante de una opcional nunca deja un bloque incompleto, ni lo
    para al ejecutar, ni le impide estar al día."""
    blocks = blocks_in(elements, registry)
    out = {}
    for dst, ports in edges.items():
        opt = registry[blocks[dst]["customData"]["blockType"]].optional
        kept = {ip: v for ip, v in ports.items() if ip not in opt}
        if kept:
            out[dst] = kept
    return out


def topo_upstream(edges, *block_ids):
    """Bloques de delante de `block_ids` (incluidos) en orden de ejecución, cada uno una vez."""
    order, seen = [], set()

    def visit(n):
        if n in seen:
            return
        seen.add(n)
        for src in sorted({s for s, _ in edges.get(n, {}).values()}):
            visit(src)
        order.append(n)

    for b in block_ids:
        visit(b)
    return order


def input_hash(block_id, params, edges, state, sources=None, files=None):
    """Hash de lo que entra en el bloque: sus parámetros y, por cada entrada, el hash del
    puerto de salida que le llega (no el del bloque entero); de una tarjeta de archivo o de
    carpeta, el de su contenido (`sources[id].hash`), nunca el de su ruta (D133). `files`:
    `{parámetro: hash}` de los parámetros que son la ruta de un archivo (el *STEP de
    referencia*), que también desactualizan por contenido; sin ninguno, el hash es el de
    siempre."""
    sources = sources or {}

    def up(src, out_port):
        if src in sources:
            return sources[src].hash
        return ((state.get(src) or {}).get("outputs_hash") or {}).get(out_port)

    ups = {port: up(src, out_port) for port, (src, out_port) in sorted(edges.get(block_id, {}).items())}
    return _h({"params": params, "inputs": ups, **({"files": files} if files else {})})


def outputs_hash(outputs, file_digest=None):
    """Hash de cada puerto de salida: `{puerto: hash}`.

    Un campo que cita un archivo (`{"value", "file": "arm.toml"}`) entra con el hash del
    contenido del archivo (`file_digest(nombre)`), no solo con su nombre: un `arm.toml`
    distinto con los mismos campos tiene que desactualizar lo de detrás (D93).
    """
    def keyed(payload):
        return {name: ({**f, "file_digest": file_digest(f["file"]) if file_digest else None}
                       if isinstance(f, dict) and "file" in f else f)
                for name, f in payload.items()}
    return {port: _h(keyed(payload)) for port, payload in (outputs or {}).items()}


def is_port_outputs(outputs):
    """¿Están las salidas guardadas por puerto (FF 4.4)? Las del spike eran campos sueltos
    `{campo: {value, unit}}`; las de ahora, `{puerto: {campo: {value, unit}}}`."""
    return isinstance(outputs, dict) and all(
        isinstance(p, dict) and all(isinstance(f, dict) and "value" in f for f in p.values())
        for p in outputs.values())


def pack_changed(registry, kind, st):
    """Si el bloque se ejecutó con otra versión de su paquete que la cargada (P25), el motivo;
    si no, "". Un bloque de antes de FF 10.1 no la apuntaba y se da por la de ahora."""
    ran = (st or {}).get("pack_version")
    info = registry.pack_of(kind) if ran and hasattr(registry, "pack_of") else None
    if info is None or info.version == ran:
        return ""
    return i18n.t("bloque.otra_version_paquete", paquete=info.id, antes=ran, ahora=info.version)


def statuses(elements, registry, state, connectors=frozenset(), sources=None, param_files=None):
    """Estado de cada bloque de la escena; ver `explain`."""
    return explain(elements, registry, state, connectors, sources, param_files)[0]


def explain(elements, registry, state, connectors=frozenset(), sources=None, param_files=None):
    """(estados, motivos). Estado de cada bloque de la escena (las tarjetas de archivo no
    tienen, D131). `state[id]` guarda params, last_hash, outputs... Un bloque que pide un
    conector que no está en `connectors` sale `no_disponible`. `sources`: `{tarjeta: FileState}`
    del sondeo; una tarjeta conectada sin hash (o sin sondear) deja el bloque `incompleto`, con
    su motivo en `motivos[bloque]`, aunque llegue a una entrada opcional: nunca entra el hash
    viejo ni se ejecuta como si no estuviera conectada (D138). `param_files`:
    `{bloque: {parámetro: hash}}`, ver `input_hash`."""
    sources = sources or {}
    param_files = param_files or {}
    blocks = blocks_in(elements, registry)
    srcs = sources_in(elements)
    edges, _ = build(elements, registry)
    req = required(edges, elements, registry)
    result, reasons = {}, {}

    def status(bid):
        if bid in result:
            return result[bid]
        st = state.get(bid) or {}
        btype = registry[blocks[bid]["customData"]["blockType"]]
        missing = [p for p in btype.inputs if p not in edges.get(bid, {}) and p not in btype.optional]
        # Una opcional cuenta por lo que entra (el hash), no por el estado de su bloque: cerrar
        # Fusion no desactualiza lo que ya usó su resultado (D122).
        ups = [status(src) for src, _ in req.get(bid, {}).values() if src not in srcs]
        lost = [f"{source_type(srcs[src]).title}: "
                f"{files.reason_text(getattr(sources.get(src), 'reason', None)) or i18n.t('tarjeta.sin_comprobar')}"
                for src, _ in sorted(set(edges.get(bid, {}).values()))
                if src in srcs and getattr(sources.get(src), "hash", None) is None]
        changed = ""
        if not set(btype.requires) <= set(connectors):
            s = "no_disponible"
        elif missing:
            s = "incompleto"
        elif lost:
            s = "incompleto"
            reasons[bid] = "; ".join(lost)
        elif st.get("error"):
            s = "error"
        elif st.get("last_hash") is None:
            s = "nunca"
        elif (st["last_hash"] == input_hash(bid, st.get("params"), edges, state, sources,
                                            param_files.get(bid))
              and all(u == "al_dia" for u in ups)
              and not (changed := pack_changed(registry, blocks[bid]["customData"]["blockType"], st))):
            s = "al_dia"
        else:
            s = "desactualizado"
            if changed:
                reasons[bid] = changed
        result[bid] = s
        return s

    for bid in sorted(blocks):
        status(bid)
    return result, reasons
