// El post-it como tarjeta (plan §3, D71): qué guarda en `customData` y cómo se lee.
import type { BlockState, BlockType } from "./store";
import type { ImageRef } from "./paste";
import type { AnimationRef } from "./animation";
import { t } from "./i18n";

export const POSTIT_KINDS = ["nota", "sugerencia", "riesgo", "pregunta"] as const;
export const POSTIT_STATES = ["abierto", "aceptado", "descartado"] as const;
export type PostitKind = (typeof POSTIT_KINDS)[number];
export type PostitState = (typeof POSTIT_STATES)[number];

export const POSTIT_LINK = /^https:\/\/pizarra\.local\/postit\//;
export const POSTIT_MIN_WIDTH = 200;   // D60: caben la etiqueta, el texto y los controles

// Getters: el texto se traduce al leerlo, no al cargar el módulo (el idioma llega después).
export const KIND_LABEL: Record<PostitKind, string> = {
  get nota() { return t("lienzo.postit.tipo.nota"); },
  get sugerencia() { return t("lienzo.postit.tipo.sugerencia"); },
  get riesgo() { return t("lienzo.postit.tipo.riesgo"); },
  get pregunta() { return t("lienzo.postit.tipo.pregunta"); },
};

export type Source = { kind: string; ref?: string; formula?: string; inputs?: string[]; url?: string; date?: string };

export type PostitData = {
  kind: "postit";
  postitKind: PostitKind;
  state: PostitState;
  text: string;
  author: string;
  origin?: string;
  created?: string;
  sources: Source[];
  estimate: boolean;
  anchor: string | null;
  image?: ImageRef | null;     // imagen pegada encima del texto (D140)
  animation?: AnimationRef | null;   // animación del agente encima del texto (D143, D175)
};

export const AUTHOR_LABEL: Record<string, string> = {
  get "agent:design"() { return t("lienzo.autor.diseno"); },
  get "agent:review"() { return t("lienzo.autor.revisor"); },
  get "agent:onboarding"() { return t("lienzo.autor.onboarding"); },
};

export type PostitView = {
  kind: PostitKind;
  state: PostitState;
  text: string;
  author: string | null;      // marca del autor; null si es del usuario sin más
  unverified: boolean;        // estimación o cuenta del agente: borde discontinuo (D19, D52)
  sources: string[];          // cómo se lee cada fuente
};

function blockName(ref: string, blocks: Record<string, BlockState>, types: Record<string, BlockType>) {
  const b = blocks[ref.split(":").slice(1).join(":") || ref];
  const title = b && types[b.type]?.title;
  return title ? t("lienzo.postit.fuente_bloque", { titulo: title }) : ref;
}

export function postitView(
  cd: PostitData,
  blocks: Record<string, BlockState>,
  types: Record<string, BlockType>,
): PostitView {
  const sources = (cd.sources ?? []).map((s) => {
    if (s.kind === "bloque" && s.ref) return blockName(s.ref, blocks, types);
    if (s.kind === "calculo") {
      const formula = (s.formula ?? "").trim();
      return s.inputs?.length
        ? t("lienzo.postit.fuente_calculo_con",
            { formula, entradas: s.inputs.map((r) => blockName(r, blocks, types)).join(", ") })
        : t("lienzo.postit.fuente_calculo", { formula });
    }
    return s.ref ?? s.kind;
  });
  const author = cd.author && cd.author !== "user"
    ? AUTHOR_LABEL[cd.author] ?? cd.author
    : cd.origin ? t("lienzo.postit.autor_editado") : null;
  return {
    kind: (POSTIT_KINDS as readonly string[]).includes(cd.postitKind) ? cd.postitKind : "nota",
    state: (POSTIT_STATES as readonly string[]).includes(cd.state) ? cd.state : "abierto",
    text: cd.text ?? "",
    author,
    unverified: !!cd.estimate || (cd.sources ?? []).some((s) => s.kind === "calculo"),
    sources,
  };
}

// ------------------------------------------------------------- cambios del usuario (D72, D73)

// La etiqueta del tipo se pulsa para pasar al siguiente (D80, 1B).
export function nextKind(k: PostitKind): PostitKind {
  return POSTIT_KINDS[(POSTIT_KINDS.indexOf(k) + 1) % POSTIT_KINDS.length];
}

const isAgent = (a?: string) => !!a && a.startsWith("agent:");

// Lo que el usuario cambia en un post-it. Cambiar el contenido (texto, tipo o imagen, D140) de
// uno del agente lo pasa al usuario con `origin` (D72); el estado, nunca (D73). El backend
// aplica la misma regla (validation._content).
export type PostitPatch = Partial<Pick<PostitData, "text" | "postitKind" | "state" | "image">>;
export function userEdit(cd: PostitData, patch: PostitPatch): PostitData {
  const out = { ...cd, ...patch };
  const content = ("text" in patch && patch.text !== cd.text)
    || ("postitKind" in patch && patch.postitKind !== cd.postitKind)
    || ("image" in patch && (patch.image?.file ?? null) !== (cd.image?.file ?? null));
  if (content && isAgent(cd.author)) {
    out.origin = cd.author;
    out.author = "user";
  }
  return out;
}

// ------------------------------------------------------------------------- filtro (D80, 4C)

// Qué se ve: es de la vista, nunca toca la escena. Por defecto, todo.
export type PostitFilter = { kinds: Record<PostitKind, boolean>; discarded: boolean; agent: boolean };

export const FILTER_ALL: PostitFilter = {
  kinds: { nota: true, sugerencia: true, riesgo: true, pregunta: true }, discarded: true, agent: true,
};

export function filteredOut(f: PostitFilter, cd: PostitData): boolean {
  const kind = (POSTIT_KINDS as readonly string[]).includes(cd.postitKind) ? cd.postitKind : "nota";
  return !f.kinds[kind] || (!f.discarded && cd.state === "descartado") || (!f.agent && isAgent(cd.author));
}
