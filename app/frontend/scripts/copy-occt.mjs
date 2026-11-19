// Copia el lector STEP del visor (occt-import-js: OpenCASCADE en WebAssembly, LGPL-2.1) a
// public/vendor/occt/ tal cual, con sus dos licencias al lado (plan D62). Va como archivos
// aparte y sustituibles, no metido en el bundle: es lo que pide la LGPL, y el worker del visor
// (src/stepWorker.ts) los carga con importScripts. Se ejecuta antes de `dev` y `build`.
import { cpSync, existsSync, mkdirSync } from "node:fs";

const src = "node_modules/occt-import-js/dist";
const dst = "public/vendor/occt";
const files = ["occt-import-js.js", "occt-import-js.wasm", "license.occt-import-js.txt", "license.occt.txt"];
mkdirSync(dst, { recursive: true });
for (const f of files) {
  if (!existsSync(`${dst}/${f}`)) cpSync(`${src}/${f}`, `${dst}/${f}`);
}
