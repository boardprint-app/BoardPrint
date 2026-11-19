// Comprueba los tipos de la interfaz propia de los paquetes del repo (`packs/*/ui-src`,
// tsconfig.packs.json, P40). Sin ninguna (el repo público no lleva paquetes) no hay nada que
// comprobar: `tsc` con un `include` vacío falla (TS18003), así que se sale bien sin llamarlo.
import { spawnSync } from "node:child_process";
import { existsSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { FRONTEND, PACKS } from "./pack-ui.mjs";

const conUi = existsSync(PACKS)
  ? readdirSync(PACKS, { withFileTypes: true })
      .filter((d) => d.isDirectory() && existsSync(join(PACKS, d.name, "ui-src")))
  : [];
if (conUi.length === 0) {
  console.log("sin interfaz de paquetes (packs/*/ui-src): nada que comprobar");
  process.exit(0);
}
const tsc = join(FRONTEND, "node_modules", "typescript", "bin", "tsc");
const r = spawnSync(process.execPath, [tsc, "-p", join(FRONTEND, "tsconfig.packs.json"), ...process.argv.slice(2)],
                    { stdio: "inherit" });
process.exit(r.status ?? 1);
