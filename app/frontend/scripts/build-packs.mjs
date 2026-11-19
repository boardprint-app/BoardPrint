// Compila la interfaz propia de cada paquete del repo (`packs/<id>/ui-src/` → `ui/`, que no se
// versiona). Lo llaman `predev` y `prebuild`, como las fuentes: sin esto, la tarjeta de un
// bloque con conector enseña «no tiene interfaz propia cargada».
//
// `base: "./"`: la página se sirve en /packs/<id>/ui/ (P47) y sus scripts y hojas tienen que
// salir de esa misma carpeta, que es lo único que deja su CSP. Sin el polyfill de
// `modulepreload`, que sería un script en línea de más.
import { build } from "vite";
import react from "@vitejs/plugin-react";
import { packAlias, packsWithUi } from "./pack-ui.mjs";

for (const p of packsWithUi()) {
  await build({
    configFile: false,
    root: p.src,
    base: "./",
    logLevel: "warn",
    plugins: [react()],
    resolve: { alias: packAlias },
    build: { outDir: p.out, emptyOutDir: true, modulePreload: { polyfill: false }, reportCompressedSize: false },
  });
  console.log(`interfaz del paquete ${p.id}: ${p.out}`);
}
