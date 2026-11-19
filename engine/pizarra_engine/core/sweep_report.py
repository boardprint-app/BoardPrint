"""Informe HTML de un barrido: gráfica de masa frente al parámetro con cada
punto marcado OK / FALLA, y matriz de comprobaciones por valor. Sin Fusion."""
import html

from pizarra_engine.core.report import CSS, _f

W, H = 640, 260
PAD_L, PAD_R, PAD_T, PAD_B = 56, 16, 30, 40


def _ticks(lo, hi, n=5):
    if hi == lo:
        return [lo]
    step = (hi - lo) / (n - 1)
    return [lo + i * step for i in range(n)]


def _chart(data):
    rows = data["rows"]
    if not rows:
        return "<p>No hay puntos dentro de rango.</p>"
    xs = [r["value"] for r in rows]
    ys = [r["mass_kg"] for r in rows]
    x0, x1 = min(xs), max(xs)
    y1 = max(ys) * 1.1
    sx = lambda x: PAD_L + (x - x0) / ((x1 - x0) or 1) * (W - PAD_L - PAD_R)
    sy = lambda y: H - PAD_B - y / y1 * (H - PAD_T - PAD_B)
    grid = "".join(
        f'<line x1="{PAD_L}" x2="{W - PAD_R}" y1="{sy(t):.1f}" y2="{sy(t):.1f}" class="g"/>'
        f'<text x="{PAD_L - 8}" y="{sy(t) + 4:.1f}" class="ax" text-anchor="end">{t:.2f}</text>'
        for t in _ticks(0, y1))
    xt = "".join(f'<text x="{sx(x):.1f}" y="{H - PAD_B + 18}" class="ax" text-anchor="middle">{x:g}</text>' for x in xs)
    path = " ".join(f"{'M' if i == 0 else 'L'}{sx(x):.1f},{sy(y):.1f}" for i, (x, y) in enumerate(zip(xs, ys)))
    pts = ""
    for r in rows:
        cls = "ok" if r["ok"] else "bad"
        fails = ", ".join(c["name"] for c in r["checks"] if not c["ok"]) or "ninguna"
        tip = f"{data['param']} = {r['value']:g} {data['label']} · masa {r['mass_kg']:.3f} kg · fallan: {fails}"
        best = r["value"] == data["best"]
        pts += (f'<g><title>{html.escape(tip)}</title>'
                f'<circle cx="{sx(r["value"]):.1f}" cy="{sy(r["mass_kg"]):.1f}" r="14" fill="transparent"/>'
                f'<circle cx="{sx(r["value"]):.1f}" cy="{sy(r["mass_kg"]):.1f}" r="{7 if best else 5}" class="pt {cls}"/></g>')
        if best:
            pts += (f'<text x="{sx(r["value"]):.1f}" y="{sy(r["mass_kg"]) - 14:.1f}" class="lbl" text-anchor="middle">'
                    f'óptimo {r["value"]:g} · {r["mass_kg"]:.3f} kg</text>')
    xlabel = f'{html.escape(data["param"])} ({html.escape(data["label"])})'
    return (f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Masa frente a {html.escape(data["param"])}">'
            f'{grid}<line x1="{PAD_L}" x2="{W - PAD_R}" y1="{H - PAD_B}" y2="{H - PAD_B}" class="axl"/>'
            f'{xt}<text x="{(W + PAD_L) / 2}" y="{H - 4}" class="ax" text-anchor="middle">{xlabel}</text>'
            f'<text x="{PAD_L - 8}" y="12" class="ax" text-anchor="end">kg</text>'
            f'<path d="{path}" class="ln"/>{pts}</svg>')


def write(path, data):
    e = html.escape
    rows = data["rows"]
    names = [c["name"] for c in rows[0]["checks"]] if rows else []
    head = "".join(f"<th class='n'>{e(data['param'])} = {r['value']:g}</th>" for r in rows)
    body = ""
    for i, n in enumerate(names):
        cells = ""
        for r in rows:
            c = r["checks"][i]
            cells += f"<td class='n'><span class='pill {'ok' if c['ok'] else 'bad'}'>{'✓' if c['ok'] else '✗'} {_f(c['value'])}</span></td>"
        limits = {r["checks"][i]["limit"] for r in rows}
        limit = limits.pop() if len(limits) == 1 else "límite variable con el parámetro"
        body += f"<tr><td>{e(n)}<br><small class='meta'>{e(limit)}</small></td>{cells}</tr>"
    mass_row = "".join(f"<td class='n'>{r['mass_kg']:.3f}</td>" for r in rows)
    best = data["best"]
    banner = (f'<div class="banner ok">Opción más ligera que cumple todo: {e(data["param"])} = {best:g} {e(data["label"])}</div>'
              if best is not None else '<div class="banner bad">Ningún valor del barrido cumple todas las comprobaciones</div>')
    skipped = (f"<p class='meta'>Valores omitidos por estar fuera de rango: {', '.join(f'{v:g}' for v in data['skipped_out_of_range'])}</p>"
               if data["skipped_out_of_range"] else "")
    css = CSS + """
svg{width:100%;height:auto;background:var(--card);border:1px solid var(--line)}
.g{stroke:var(--line);stroke-width:1}.axl{stroke:var(--mut);stroke-width:1}
.ax{fill:var(--mut);font-size:11px}.lbl{fill:var(--fg);font-size:12px;font-weight:600}
.ln{fill:none;stroke:var(--acc);stroke-width:2}
.pt{stroke:var(--card);stroke-width:2}.pt.ok{fill:var(--ok)}.pt.bad{fill:var(--bad)}
.key{display:flex;gap:16px;color:var(--mut);font-size:.85rem}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;vertical-align:-1px}
"""
    doc = f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Barrido {e(data['param'])} · {e(data['part'])}</title><style>{css}</style></head><body><main>
<header><h1>Barrido de {e(data['param'])}: {e(data['part'])}</h1>
<div class="meta">{e(data['desc'])} · valor original {e(data['original'])} (restaurado) · {e(data['time'])}</div></header>
{banner}
<section><h2>Masa frente a {e(data['param'])}</h2>
<div class="key"><span><span class="dot" style="background:var(--ok)"></span>cumple todo</span><span><span class="dot" style="background:var(--bad)"></span>falla alguna comprobación</span></div>
{_chart(data)}{skipped}</section>
<section><h2>Comprobaciones por valor</h2><div class="tw"><table><thead><tr><th>Comprobación</th>{head}</tr></thead>
<tbody><tr><td><b>Masa (kg)</b></td>{mass_row}</tr>{body}</tbody></table></div></section>
</main></body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
