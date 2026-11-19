// Controles genéricos *Gráfica* y *Vista 2D* (docs/PLAN_PAQUETES.md §5, P8, P52): pintan los
// campos de salida que el paquete arma con `chart()` y `view2d()` del SDK, en la tarjeta o en
// el panel. La cuenta (ejes, escala, nombres) está en controls.ts.
import { useLayoutEffect, useRef, useState, type MouseEvent } from "react";
import { outputView } from "./outputs";
import { getLanguage, t } from "./i18n";
import { tp } from "./packI18n";
import { charW, chartData, chartFrame, nearestPoint, placeLabels, planeData, planeFrame,
         type ChartData, type PlaneData } from "./controls";
import type { Value } from "./store";
import "./controls.css";

type Outputs = Record<string, Record<string, Value>>;
type Size = "card" | "panel";
const CHART_H: Record<Size, number> = { card: 150, panel: 260 };
const PLANE_H: Record<Size, number> = { card: 140, panel: 320 };

/** Ancho del hueco en px de maquetación (sin el zoom de la pizarra), y al cambiar. */
function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setW(el.offsetWidth);
    const ro = new ResizeObserver(() => setW(el.offsetWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

const num = (v: number, step?: number) => v.toLocaleString(getLanguage() === "en" ? "en-US" : "es-ES", {
  maximumFractionDigits: step ? Math.max(0, -Math.floor(Math.log10(step) + 1e-9)) : 4,
});
const withUnit = (label: string, unit: string) => (unit ? `${label} (${unit})` : label);

/** `pack`: el del bloque; sus textos (título, ejes, curvas, etiquetas) se traducen al pintar (O15). */
type Props = { control: "chart" | "view2d"; outputs: Outputs | null; stale: boolean; size: Size; pack?: string };

/** Los textos de una gráfica o una vista 2D en el idioma de la app; los números no cambian. */
function localized<D extends ChartData | PlaneData>(d: D, tr: (s: string) => string): D {
  const axis = (a: { label: string; unit: string }) => ({ ...a, label: tr(a.label) });
  if ("curves" in d) return { ...d, x: axis(d.x), y: axis(d.y), curves: d.curves.map((c) => ({ ...c, label: tr(c.label) })) };
  return { ...d, x: axis(d.x), y: axis(d.y), items: d.items.map((it) => ({ ...it, label: tr(it.label) })) };
}

/** Todos los campos de un control en las salidas de un bloque, en su orden. */
export function ControlFields({ control, outputs, stale, size, pack }: Props) {
  const tr = (s: string) => tp(pack, s);
  const fields = outputView(outputs).controls[control] ?? [];
  if (!fields.length) {
    // En la tarjeta, sin salidas no se pinta nada (como Resultados); en el panel se dice.
    return size === "panel" ? <p className="gc-empty">{t(`bloques.controles.vacio_${control}`)}</p> : null;
  }
  return (
    <>
      {fields.map((f) => {
        const raw = control === "chart" ? chartData(f.value) : planeData(f.value);
        const d = raw && localized(raw, tr);
        return (
          <figure key={`${f.port}.${f.key}`} className={`gc gc-${size}${stale ? " stale" : ""}`}>
            {f.label && <figcaption>{tr(f.label)}</figcaption>}
            {!d ? <p className="gc-bad">{t(`bloques.controles.mal_${control}`)}</p>
              : control === "chart" ? <ChartView d={d as ChartData} height={CHART_H[size]} />
              : <PlaneView d={d as PlaneData} maxH={PLANE_H[size]} />}
          </figure>
        );
      })}
    </>
  );
}

export function ChartView({ d, height }: { d: ChartData; height: number }) {
  const [ref, w] = useWidth();
  const [hx, setHx] = useState<number | null>(null);
  // El margen izquierdo, el del número más largo del eje y.
  const probe = chartFrame(d, Math.max(w, 120), height, { l: 0, r: 0, t: 0, b: 0 });
  const yLen = Math.max(...probe.ys.ticks.map((t) => num(t, probe.ys.step).length));
  const pad = { l: 10 + yLen * charW, r: 12, t: 18, b: 30 };
  const f = chartFrame(d, Math.max(w, 120), height, pad);
  const multi = d.curves.length > 1;
  const onMove = (e: MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const mx = (e.clientX - r.left) * (w / (r.width || w));      // con el zoom de la pizarra
    const x = f.xs.lo + ((mx - pad.l) / f.iw) * (f.xs.hi - f.xs.lo);
    setHx(mx < pad.l || mx > pad.l + f.iw ? null : x);
  };
  const read = hx === null ? null : d.curves.map((c) => nearestPoint(c.points, hx));
  return (
    <div className="gc-box-wrap" ref={ref}>
      {w > 0 && (
        <svg className="gc-chart" width={w} height={height} onMouseMove={onMove} onMouseLeave={() => setHx(null)}
             role="img" aria-label={t("bloques.controles.frente_a", { y: withUnit(d.y.label, d.y.unit), x: withUnit(d.x.label, d.x.unit) })}>
          {f.ys.ticks.map((t) => (
            <g key={`y${t}`}>
              <line className="gc-grid" x1={pad.l} x2={pad.l + f.iw} y1={f.py(t)} y2={f.py(t)} />
              <text className="gc-tick" x={pad.l - 4} y={f.py(t)} textAnchor="end" dominantBaseline="middle">{num(t, f.ys.step)}</text>
            </g>
          ))}
          {f.xs.ticks.map((t) => (
            <g key={`x${t}`}>
              <line className="gc-grid" x1={f.px(t)} x2={f.px(t)} y1={pad.t} y2={pad.t + f.ih} />
              <text className="gc-tick" x={f.px(t)} y={pad.t + f.ih + 12} textAnchor="middle">{num(t, f.xs.step)}</text>
            </g>
          ))}
          <rect className="gc-frame" x={pad.l} y={pad.t} width={f.iw} height={f.ih} />
          <text className="gc-axis" x={pad.l} y={11}>{withUnit(d.y.label, d.y.unit)}</text>
          <text className="gc-axis" x={pad.l + f.iw} y={height - 3} textAnchor="end">{withUnit(d.x.label, d.x.unit)}</text>
          {d.curves.map((c, i) => (
            <polyline key={i} className={`gc-curve gc-c${i % 4}`}
                      points={c.points.map(([x, y]) => `${f.px(x)},${f.py(y)}`).join(" ")}>
              <title>{c.label}</title>
            </polyline>
          ))}
          {read && (
            <g className="gc-hover">
              <line x1={f.px(read[0][0])} x2={f.px(read[0][0])} y1={pad.t} y2={pad.t + f.ih} />
              {read.map(([x, y], i) => <circle key={i} className={`gc-c${i % 4}`} cx={f.px(x)} cy={f.py(y)} r={3} />)}
            </g>
          )}
        </svg>
      )}
      {read && (
        // Al lado contrario del ratón: nunca tapa el trozo de curva que se está leyendo.
        <div className="gc-read" style={f.px(read[0][0]) > pad.l + f.iw / 2 ? { left: pad.l + 4 } : { right: 0 }}>
          <span>{d.x.label} {num(read[0][0])} {d.x.unit}</span>
          {read.map(([, y], i) => (
            <span key={i}><i className={`gc-c${i % 4}`} />{multi ? `${d.curves[i].label}: ` : `${d.y.label} `}{num(y)} {d.y.unit}</span>
          ))}
        </div>
      )}
      {multi && (
        <div className="gc-legend">
          {d.curves.map((c, i) => <span key={i}><i className={`gc-c${i % 4}`} />{c.label}</span>)}
        </div>
      )}
    </div>
  );
}

export function PlaneView({ d, maxH }: { d: PlaneData; maxH: number }) {
  const [ref, w] = useWidth();
  const f = w > 0 ? planeFrame(d, w, maxH) : null;
  const labels = f ? placeLabels(d, f) : [];
  const unit = d.x.unit === d.y.unit ? d.x.unit : `${d.x.unit} · ${d.y.unit}`;
  return (
    <div className="gc-box-wrap" ref={ref}>
      {f && (
        <svg className="gc-plane" width={f.w} height={f.h} role="img"
             aria-label={unit ? t("bloques.controles.vista2d_unidad", { x: d.x.label, y: d.y.label, unit })
                              : t("bloques.controles.vista2d", { x: d.x.label, y: d.y.label })}>
          {d.items.map((it, i) => {
            const cls = `gc-it${it.tone ? ` t-${it.tone}` : ""}`;
            const tip = it.label && <title>{it.label}</title>;
            if (it.kind === "box") {
              const x = f.px(it.box[0]), y = Math.min(f.py(it.box[1]), f.py(it.box[3]));
              return <rect key={i} className={cls} x={x} y={y} width={Math.max(f.px(it.box[2]) - x, 0.5)}
                           height={Math.max(Math.abs(f.py(it.box[3]) - f.py(it.box[1])), 0.5)}>{tip}</rect>;
            }
            if (it.kind === "line") {
              return <polyline key={i} className={`${cls} gc-line`}
                               points={it.points.map(([x, y]) => `${f.px(x)},${f.py(y)}`).join(" ")}>{tip}</polyline>;
            }
            return <circle key={i} className={`${cls} gc-pt`} cx={f.px(it.point[0])} cy={f.py(it.point[1])} r={3}>{tip}</circle>;
          })}
          {labels.map((l) => (
            <text key={l.item} className="gc-label" x={l.x} y={l.y} textAnchor={l.anchor} dominantBaseline="hanging">{l.text}</text>
          ))}
        </svg>
      )}
      {unit && <div className="gc-unit">{t("bloques.controles.a_escala", { unit })}</div>}
    </div>
  );
}
