// Copia las fuentes de Excalidraw a public/ para servirlas en local.
// Sin esto Excalidraw las descarga de esm.sh: la app no funcionaría sin conexión y haría
// llamadas externas que el plan descarta (D44). Se ejecuta antes de `dev` y `build`.
import { cpSync, existsSync } from "node:fs";

const src = "node_modules/@excalidraw/excalidraw/dist/prod/fonts";
const dst = "public/fonts";
if (!existsSync(dst)) cpSync(src, dst, { recursive: true });
