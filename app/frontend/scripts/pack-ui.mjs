// Lo común de compilar y probar la interfaz propia de los paquetes del repo
// (`packs/<id>/ui-src/` → `packs/<id>/ui/`, docs/PLAN_PAQUETES.md §5, P24, P40). Los paquetes no
// tienen `node_modules`: React y vitest salen de los de este frontend. Un paquete de fuera
// compila su `ui/` con lo que quiera; esto es solo para los oficiales.
import { existsSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const FRONTEND = resolve(dirname(fileURLToPath(import.meta.url)), "..");
export const PACKS = resolve(FRONTEND, "../../packs");
const MODULES = join(FRONTEND, "node_modules").replace(/\\/g, "/");

/** Los alias que dejan importar React (y vitest, en los tests) desde `packs/`. */
export const packAlias = [
  { find: /^(react|react-dom|scheduler|vitest)(\/.*)?$/, replacement: `${MODULES}/$1$2` },
];

/** Los paquetes con interfaz que compilar: los que tienen `ui-src/index.html`. */
export function packsWithUi() {
  if (!existsSync(PACKS)) return [];
  return readdirSync(PACKS, { withFileTypes: true })
    .filter((d) => d.isDirectory() && existsSync(join(PACKS, d.name, "ui-src", "index.html")))
    .map((d) => ({ id: d.name, src: join(PACKS, d.name, "ui-src"), out: join(PACKS, d.name, "ui") }));
}
