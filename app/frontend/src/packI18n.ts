// Traducción de lo que da un paquete (PLAN_PUBLICACION O15). Cada paquete trae sus catálogos
// (`packs/<id>/locales/<idioma>.toml`, que el backend manda en `catalog.packs[i].i18n`): una
// tabla `{texto de origen: traducción}`. Una clave con `{nombre}` es un patrón que casa la
// frase entera con cualquier valor en cada marcador («Falla por {x} mm» casa con «Falla por
// 1,2 mm»). Se traduce **solo lo que se pinta**: títulos, etiquetas, textos de las salidas.
// Los datos (ids, claves, valores que se mandan al backend o se comparan) nunca pasan por aquí.
// Sin traducción, el texto de origen. Los paquetes se escriben en español: en «es» no se toca.
import { getLanguage, t } from "./i18n";
import { getStore, type BlockType, type ConnectorInfo, type PackInfo, type ParamSpec } from "./store";
import type { Template } from "./palette";
import type { PortTypes } from "./ports";

export type Catalog = Record<string, string>;
/** El idioma en que se escriben los paquetes: en él no hay nada que traducir. */
export const SOURCE_LANG = "es";
/** Hasta dónde se traduce lo que casa con un marcador (`{motivos}` lleva otra frase dentro). */
const DEPTH = 3;
const LIST_SEP = "; ";

type Pattern = { re: RegExp; names: string[]; target: string; prefix: number; literal: number; order: number };
// Solo `{palabra}` (letras ASCII, cifras y _) es un marcador: «{parámetro: valor}» es texto.
const PLACEHOLDER = /\{(\w+)\}/g;
const compiled = new WeakMap<Catalog, Pattern[]>();
// Un marcador nunca pasa por encima de «; »: una lista «a (estado x); b (estado y)» no la casa
// entera un patrón de una línea, y se traduce parte por parte.
const GROUP = "((?:(?!; ).)+?)";

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Los patrones de un catálogo, una vez por catálogo: anclados, cada marcador un grupo no
 *  voraz que no cruza «; ». El orden es fijo: primero el de más texto fijo delante del primer
 *  marcador, luego el de más texto fijo en total, y luego el del catálogo. */
function patternsOf(cat: Catalog): Pattern[] {
  const got = compiled.get(cat);
  if (got) return got;
  const out: Pattern[] = [];
  Object.entries(cat).forEach(([key, target], order) => {
    const names: string[] = [];
    let src = "", last = 0, prefix = 0;
    for (const m of key.matchAll(PLACEHOLDER)) {
      if (!names.length) prefix = m.index!;
      src += `${escape(key.slice(last, m.index))}${GROUP}`;
      names.push(m[1]);
      last = m.index! + m[0].length;
    }
    if (!names.length) return;
    src += escape(key.slice(last));
    out.push({ re: new RegExp(`^${src}$`, "s"), names, target, prefix,
               literal: key.replace(PLACEHOLDER, "").length, order });
  });
  out.sort((a, b) => b.prefix - a.prefix || b.literal - a.literal || a.order - b.order);
  compiled.set(cat, out);
  return out;
}

const own = (cat: Catalog, text: string) => Object.prototype.hasOwnProperty.call(cat, text);

function lookup(cats: Catalog[], text: string, depth: number): string | null {
  for (const cat of cats) if (own(cat, text)) return cat[text];
  for (const cat of cats) {
    for (const p of patternsOf(cat)) {
      const m = p.re.exec(text);
      if (!m) continue;
      const vals: Record<string, string> = {};
      let ok = true;
      p.names.forEach((n, i) => {
        if (n in vals && vals[n] !== m[i + 1]) ok = false;
        vals[n] = m[i + 1];
      });
      if (!ok) continue;
      // lo que casa con un marcador puede ser otra frase del paquete: también se traduce
      return p.target.replace(PLACEHOLDER, (all, n: string) => (n in vals ? run(cats, vals[n], depth - 1) : all));
    }
  }
  return null;
}

function run(cats: Catalog[], text: string, depth: number): string {
  if (depth <= 0 || !text) return text;
  const hit = lookup(cats, text, depth);
  if (hit !== null) return hit;
  // una lista «a; b; c» (lo que falla, notas, motivos): cada parte por su lado
  if (text.includes(LIST_SEP)) return text.split(LIST_SEP).map((part) => run(cats, part, depth - 1)).join(LIST_SEP);
  return text;
}

/** `text` traducido con `cats` (uno o varios catálogos, el primero manda): la entrada exacta
 *  del primero que la tenga; si no, el primer patrón que casa con la frase entera (los del
 *  primer catálogo antes), con lo que casa en cada marcador traducido a su vez; si no, una
 *  lista «a; b» parte por parte; y si no, el propio texto. Un marcador repetido en la clave
 *  tiene que valer lo mismo. */
export function translate(cats: Catalog | Catalog[] | null | undefined, text: string): string {
  if (typeof text !== "string" || !text || !cats) return text;
  const list = (Array.isArray(cats) ? cats : [cats]).filter(Boolean);
  return list.length ? run(list, text, DEPTH) : text;
}

/** El catálogo del paquete `packId` en `lang` (por defecto, el de la app), solo el suyo, o
 *  undefined. */
export function packCatalog(packId: string | null | undefined, lang: string = getLanguage(),
                            packs: PackInfo[] = getStore().packs): Catalog | undefined {
  if (!packId || lang === SOURCE_LANG) return undefined;
  return packs.find((p) => p.id === packId)?.i18n?.[lang];
}

const scopes = new WeakMap<PackInfo[], Map<string, Catalog[]>>();

/** Los catálogos con que se traduce lo de `packId`: el suyo primero y luego los de los demás
 *  paquetes cargados (un bloque enseña textos que da un paquete que pide, o su conector). */
export function packScope(packId: string | null | undefined, lang: string = getLanguage(),
                          packs: PackInfo[] = getStore().packs): Catalog[] {
  if (lang === SOURCE_LANG) return [];
  let byKey = scopes.get(packs);
  if (!byKey) scopes.set(packs, byKey = new Map());
  const key = `${lang}:${packId ?? ""}`;
  let got = byKey.get(key);
  if (!got) {
    const first = packCatalog(packId, lang, packs);
    const rest = packs.filter((p) => p.id !== packId && !p.error).map((p) => p.i18n?.[lang])
      .filter((c): c is Catalog => !!c);
    got = first ? [first, ...rest] : rest;
    byKey.set(key, got);
  }
  return got;
}

const merged = new WeakMap<Catalog[], Catalog>();

/** Lo mismo como una sola tabla (el suyo manda), para la interfaz propia de un paquete. El
 *  mismo objeto mientras no cambien los paquetes: el estado del marco no se rehace por él. */
export function mergedCatalog(packId: string | null | undefined, lang: string = getLanguage(),
                              packs: PackInfo[] = getStore().packs): Catalog {
  const scope = packScope(packId, lang, packs);
  let got = merged.get(scope);
  if (!got) merged.set(scope, got = Object.assign({}, ...[...scope].reverse()) as Catalog);
  return got;
}

/** Un texto del paquete `packId` en el idioma de la app, para pintarlo. */
export function tp(packId: string | null | undefined, text: string): string {
  return translate(packScope(packId), text);
}

/** Lo mismo con el catálogo que trae `pack` (`GET /api/packs`) delante: *Ajustes → Paquetes*
 *  se abre también desde el inicio, donde aún no hay catálogo de bloques cargado. */
export function tpOwn(pack: { id: string; i18n?: Record<string, Catalog> }, text: string,
                      lang: string = getLanguage(), packs: PackInfo[] = getStore().packs): string {
  if (lang === SOURCE_LANG) return text;
  const own = pack.i18n?.[lang];
  const scope = packScope(pack.id, lang, packs);
  return translate(own ? [own, ...scope] : scope, text);
}

/** El paquete de un tipo de bloque, de puerto o de plantilla: lo de antes del primer punto. */
export const packOf = (kind: string) => kind.split(".", 1)[0];

// ------------------------------------------------- el catálogo de bloques, ya para pintar
type Lookup = (pack: string, text: string) => string;

function localizeParam(spec: ParamSpec, tr: (s: string) => string): ParamSpec {
  // las opciones (`choices`) son valores que se guardan: solo cambia cómo se enseñan
  const labels: Record<string, string> = {};
  for (const c of spec.choices) {
    const shown = tr(spec.choice_labels?.[c] ?? c);
    if (spec.choice_labels?.[c] !== undefined || shown !== c) labels[c] = shown;
  }
  return { ...spec, label: spec.label ? tr(spec.label) : spec.label,
           ...(spec.choice_labels || Object.keys(labels).length ? { choice_labels: labels } : {}) };
}

function localizeType(ty: BlockType, tr: (s: string) => string): BlockType {
  return {
    ...ty, title: tr(ty.title), description: tr(ty.description),
    params: Object.fromEntries(Object.entries(ty.params).map(([n, p]) => [n, localizeParam(p, tr)])),
    fix: ty.fix ? { ...ty.fix, label: tr(ty.fix.label) } : ty.fix,
  };
}

export type CatalogParts = {
  types: Record<string, BlockType>; ports: PortTypes; templates: Record<string, Template>;
  connectorInfo: Record<string, ConnectorInfo>; packs: PackInfo[];
};

/** El catálogo que llega con `init`, con los textos que se pintan en `lang`: títulos,
 *  descripciones, etiquetas de parámetros y de sus opciones, nombres de tipos de puerto, de
 *  plantillas, de conectores y de paquetes. Los ids, las claves y los valores no cambian. El
 *  idioma no cambia sin recargar la ventana (R1): basta hacerlo una vez, al recibirlo. */
/** Los tipos de puerto del núcleo (`packs.CORE_PORT_TYPES`: modelo CAD, archivo, carpeta) no
 *  son de ningún paquete: su nombre sale del catálogo de la app. */
function corePort(type: string): string | null {
  const key = `puerto.${type}`;
  const got = t(key);
  return got === key ? null : got;
}

export function localizeCatalog(cat: CatalogParts, lang: string = getLanguage()): CatalogParts {
  if (lang === SOURCE_LANG) return cat;
  const look: Lookup = (pack, text) => translate(packScope(pack, lang, cat.packs), text);
  const by = (pack: string) => (s: string) => look(pack, s);
  return {
    types: Object.fromEntries(Object.entries(cat.types).map(([k, ty]) => [k, localizeType(ty, by(ty.pack || packOf(k)))])),
    ports: Object.fromEntries(Object.entries(cat.ports).map(([k, p]) => [k, { ...p, label: corePort(k) ?? look(packOf(k), p.label) }])),
    templates: Object.fromEntries(Object.entries(cat.templates).map(([k, tpl]) => {
      const pack = tpl.pack || packOf(k);
      return [k, { ...tpl, title: look(pack, tpl.title), description: look(pack, tpl.description) }];
    })),
    // un conector se llama como su paquete (P41)
    connectorInfo: Object.fromEntries(Object.entries(cat.connectorInfo).map(([k, c]) => [k, { ...c, title: look(k, c.title) }])),
    packs: cat.packs.map((p) => ({ ...p, name: look(p.id, p.name) })),
  };
}
