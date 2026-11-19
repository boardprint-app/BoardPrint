"""Informe HTML autocontenido a partir de los parámetros, medidas y resultados.

No depende de Fusion: recibe diccionarios y escribe un archivo.
"""
import html
from datetime import datetime

CSS = """
:root{--bg:#f5f7f8;--card:#fff;--fg:#1b2329;--mut:#5b6872;--line:#d3dbe0;--ok:#2f7d4f;--bad:#b3261e;--warn:#a86512;--acc:#0b6e8a}
@media (prefers-color-scheme:dark){:root{--bg:#12181c;--card:#1a2227;--fg:#e3e9ec;--mut:#93a1aa;--line:#2e3a41;--ok:#6cc08f;--bad:#f2867c;--warn:#e0a55a;--acc:#4fb3cf}}
body{background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,Segoe UI,sans-serif;margin:0;padding:24px 16px}
main{max-width:900px;margin:0 auto;display:flex;flex-direction:column;gap:22px}
h1{margin:0;font-size:1.6rem}h2{margin:0 0 8px;font-size:1.1rem}
.meta{color:var(--mut)}
.banner{padding:12px 16px;border-left:5px solid;background:var(--card);font-weight:600}
.banner.ok{border-color:var(--ok);color:var(--ok)}.banner.bad{border-color:var(--bad);color:var(--bad)}
.tw{overflow-x:auto;background:var(--card);border:1px solid var(--line)}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;color:var(--mut)}
td.n{text-align:right;font-family:Consolas,monospace}
.pill{display:inline-block;padding:1px 8px;border-radius:10px;font-size:.78rem;font-weight:600}
.pill.ok{background:color-mix(in srgb,var(--ok) 18%,transparent);color:var(--ok)}
.pill.bad{background:color-mix(in srgb,var(--bad) 18%,transparent);color:var(--bad)}
.pill.mod{background:color-mix(in srgb,var(--warn) 18%,transparent);color:var(--warn)}
code{font-family:Consolas,monospace;font-size:.9em}
"""


def _f(v, nd=3):
    if isinstance(v, (int, float)):
        if abs(v) < 1e-9:
            return "0"
        return f"{v:.{nd}g}" if abs(v) >= 1e4 or (v != 0 and abs(v) < 1e-2) else f"{v:,.{nd}f}".rstrip("0").rstrip(".")
    return html.escape(str(v))


def write(path, spec, values, measured, results, checks, notes=()):
    e = html.escape
    all_ok = all(c["ok"] for c in checks)
    n_bad = sum(1 for c in checks if not c["ok"])
    rows_p = []
    for name, p in spec.params.items():
        v = values.get(name)
        modified = v is not None and abs(v - p.value) > 1e-9
        in_range = v is not None and p.min <= v <= p.max
        tag = '<span class="pill mod">modificado</span>' if modified else '<span class="pill">por defecto</span>'
        if not in_range:
            tag += ' <span class="pill bad">fuera de rango</span>'
        rows_p.append(f"<tr><td><code>{e(name)}</code></td><td>{e(p.desc)}</td><td class='n'>{_f(v)}</td>"
                      f"<td>{e(p.label)}</td><td class='n'>{_f(p.value)}</td><td class='n'>{_f(p.min)} – {_f(p.max)}</td><td>{tag}</td></tr>")
    rows_m = "".join(f"<tr><td>{e(k)}</td><td class='n'>{_f(v) if not isinstance(v, list) else e(', '.join(_f(x) for x in v))}</td></tr>"
                     for k, v in measured.items())
    rows_r = "".join(f"<tr><td>{e(r['name'])}</td><td><code>{e(r['formula'])}</code></td><td class='n'>{_f(r['value'])}</td><td>{e(r['unit'])}</td></tr>"
                     for r in results)
    rows_c = "".join(f"<tr><td>{e(c['name'])}</td><td class='n'>{_f(c['value'])}</td><td>{e(c['limit'])}</td>"
                     f"<td><span class='pill {'ok' if c['ok'] else 'bad'}'>{'OK' if c['ok'] else 'FALLA'}</span></td></tr>"
                     for c in checks)
    notes_html = "".join(f"<li>{e(n)}</li>" for n in notes)
    banner = ('<div class="banner ok">Todas las comprobaciones OK</div>' if all_ok
              else f'<div class="banner bad">{n_bad} comprobación(es) FALLAN</div>')
    doc = f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Informe {e(spec.part)}</title><style>{CSS}</style></head><body><main>
<header><h1>Informe de cálculo: {e(spec.part)}</h1>
<div class="meta">Documento Fusion <code>{e(spec.document)}</code> · componente <code>{e(spec.component)}</code> · generado {datetime.now():%Y-%m-%d %H:%M:%S}</div></header>
{banner}
<section><h2>Comprobaciones</h2><div class="tw"><table><thead><tr><th>Comprobación</th><th>Valor</th><th>Límite</th><th>Estado</th></tr></thead><tbody>{rows_c}</tbody></table></div></section>
<section><h2>Resultados</h2><div class="tw"><table><thead><tr><th>Magnitud</th><th>Fórmula</th><th>Valor</th><th>Unidad</th></tr></thead><tbody>{rows_r}</tbody></table></div></section>
<section><h2>Parámetros (valores vivos de Fusion)</h2><div class="tw"><table><thead><tr><th>Nombre</th><th>Descripción</th><th>Valor</th><th>Unidad</th><th>Defecto</th><th>Rango</th><th>Origen</th></tr></thead><tbody>{''.join(rows_p)}</tbody></table></div></section>
<section><h2>Medido en Fusion</h2><div class="tw"><table><tbody>{rows_m}</tbody></table></div></section>
{f'<section><h2>Hipótesis y notas</h2><ul>{notes_html}</ul></section>' if notes else ''}
</main></body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    return all_ok, n_bad
