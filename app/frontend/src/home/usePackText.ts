// Lo que da un paquete a la *Librería* (la descripción y la unidad de cada campo de su
// `library/schema.toml`, PLAN_LIBRERIA L5) en el idioma de la app, con su catálogo (O15). En el
// inicio aún no hay catálogo de bloques cargado (`tp` no tiene los paquetes): los catálogos
// llegan con `GET /api/packs`, como en *Ajustes → Paquetes*. Mientras llegan, el texto de origen.
import { useCallback, useEffect, useState } from "react";
import type { InstalledPack } from "../packs";
import { fetchPacks } from "../packsApi";
import { tp, tpOwn } from "../packI18n";

export type PackText = (pack: string | null | undefined, text: string) => string;

export function usePackText(): PackText {
  const [packs, setPacks] = useState<InstalledPack[]>([]);
  useEffect(() => {
    let live = true;
    fetchPacks().then((r) => { if (live) setPacks(r.packs); }, () => {});
    return () => { live = false; };
  }, []);
  return useCallback((pack: string | null | undefined, text: string) => {
    if (!text) return text;
    const p = pack ? packs.find((x) => x.id === pack) : undefined;
    return p ? tpOwn(p, text) : tp(pack, text);
  }, [packs]);
}
