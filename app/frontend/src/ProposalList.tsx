// Propuesta sobre un parámetro que es una lista de objetos con `id` (D177: el `arbol` del
// *Diseño del terminal*, o cualquier otro): dentro de la pestaña de la propuesta, por elemento.
// Lo añadido con sus campos, lo quitado tachado, y en lo modificado solo lo que cambia (dentro
// de `params`, qué parámetro). El diff es de proposal.ts (`listDiff`).
import { Fragment } from "react";
import { brief, listDiff, type FieldDiff, type Proposal } from "./proposal";
import { t } from "./i18n";

function Field({ f }: { f: FieldDiff }) {
  if (f.kind === "keys") {
    return (
      <>
        {f.keys.map((k) => (
          <li key={k.key}>
            <span className="al-f">{f.field} · {k.key}</span>{" "}
            {k.before !== undefined && <span className="old">{brief(k.before)}</span>}
            {k.before !== undefined && k.after !== undefined && " "}
            {k.after !== undefined ? <span className="new">{brief(k.after)}</span> : <em> {t("agente.lista.se_quita_parentesis")}</em>}
          </li>
        ))}
      </>
    );
  }
  if (f.kind === "items") {
    return (
      <li>
        <span className="al-f">{f.field}</span>{" "}
        {f.added.map((v, i) => <Fragment key={`a${i}`}><span className="new">+ {brief(v)}</span>{" "}</Fragment>)}
        {f.removed.map((v, i) => <Fragment key={`r${i}`}><span className="old">{brief(v)}</span>{" "}</Fragment>)}
      </li>
    );
  }
  return (
    <li>
      <span className="al-f">{f.field}</span>{" "}
      {f.before !== undefined && <><span className="old">{brief(f.before)}</span>{" "}</>}
      {f.after !== undefined ? <span className="new">{brief(f.after)}</span> : <em>{t("agente.lista.se_quita_parentesis")}</em>}
    </li>
  );
}

/** «1 añadido», «3 añadidos»: la clave `<base>_uno` o `<base>_varios`. */
const plural = (n: number, base: string) => t(`${base}_${n === 1 ? "uno" : "varios"}`, { n });

export function ProposalList({ p, label }: { p: Proposal; label: (param: string) => string }) {
  const lists = Object.entries(p.change.params ?? {})
    .map(([name, after]) => ({ name, diff: listDiff(p.current.params?.[name], after) }))
    .filter((x) => x.diff !== null);
  if (!lists.length) return null;
  return (
    <>
      {lists.map(({ name, diff }) => {
        const n = (k: string) => diff!.items.filter((i) => i.kind === k).length;
        const counts = [n("added") && plural(n("added"), "agente.lista.anadido"),
                        n("removed") && plural(n("removed"), "agente.lista.quitado"),
                        n("changed") && plural(n("changed"), "agente.lista.cambiado"),
                        diff!.unchanged && plural(diff!.unchanged, "agente.lista.igual")].filter(Boolean);
        return (
          <div key={name} className="ask-list" aria-label={t("agente.lista.aria", { nombre: label(name) })}>
            <div className="al-head"><b>{label(name)}</b> · {counts.join(" · ") || t("agente.lista.sin_cambios")}</div>
            <ul>
              {diff!.items.map((it) => (
                <li key={`${it.kind}:${it.id}`} className={`al-${it.kind}`}>
                  <span className="al-id">
                    <i aria-hidden="true">{it.kind === "added" ? "+" : it.kind === "removed" ? "−" : "~"}</i>
                    {it.kind === "removed" ? <span className="old">{it.id}</span> : it.id}
                    <span className="al-tag">{it.kind === "added" ? t("agente.lista.tag_nuevo") : it.kind === "removed" ? t("agente.lista.tag_quita") : t("agente.lista.tag_cambia")}</span>
                  </span>
                  {/* Lo quitado, en una línea (lo que era); lo nuevo y lo cambiado, campo a campo. */}
                  {it.kind === "removed" ? (
                    <div className="al-was">{brief(Object.fromEntries(Object.entries(it.item).filter(([k]) => k !== "id")))}</div>
                  ) : (
                    <ul>
                      {it.kind === "changed"
                        ? it.fields.map((f) => <Field key={f.field} f={f} />)
                        : Object.entries(it.item).filter(([k]) => k !== "id").map(([k, v]) => (
                            <li key={k}><span className="al-f">{k}</span>{" "}<span className="new">{brief(v)}</span></li>
                          ))}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </>
  );
}
