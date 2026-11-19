import { readFile } from "node:fs/promises";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { packAlias } from "./scripts/pack-ui.mjs";

// Excalidraw añade esm.sh como respaldo de cada fuente (ASSETS_FALLBACK_URL). La app no hace
// llamadas externas (plan D44): se sustituye por el propio origen, que ya sirve las fuentes
// (scripts/copy-fonts.mjs). Sin esto, la CSP las bloquea pero Chrome llena la consola de
// errores. `npm run build` comprueba después que no queda ninguna referencia a esm.sh.
const CDN_FALLBACK = /`https:\/\/esm\.sh\/\$\{[\s\S]*?\}\/dist\/prod\/`/g;
const LOCAL_ORIGIN = '(location.origin + "/")';
const isExcalidraw = (id: string) => /@excalidraw[\\/]excalidraw[\\/].*\.js$/.test(id);

// Bloques y post-its son `embeddable` con un enlace interno (pizarra.local): Excalidraw pinta
// a su lado el icono de enlace, que no lleva a ningún sitio (D77). Se quita solo en los
// `embeddable`. Si otra versión de Excalidraw cambia ese código, se para el build.
// Dos formas: la de desarrollo (dist/dev, legible) y la de producción (dist/prod, minificada:
// `sp=(e,t,n,r)=>{if(e.link&&!n.selectedElementIds[e.id])`, justo detrás de la caché de iconos).
const LINK_ICON_DEV = /if \(element\.link && !appState\.selectedElementIds\[element\.id\]\)/;
const LINK_ICON_DEV_FIX = 'if (element.link && element.type !== "embeddable" && !appState.selectedElementIds[element.id])';
const LINK_ICON_PROD = /(regularLink:null,elementLink:null\},[\w$]+=\(([\w$]+),[\w$]+,([\w$]+),[\w$]+\)=>\{if\()\2\.link&&!\3\.selectedElementIds\[\2\.id\]\)/;

function patchExcalidraw(code: string, id: string) {
  let out = code.includes("esm.sh") ? code.replace(CDN_FALLBACK, LOCAL_ORIGIN) : code;
  const dev = out.includes("renderLinkIcon = ");
  const prod = out.includes("regularLink:null,elementLink:null}");
  if (dev || prod) {
    const re = dev ? LINK_ICON_DEV : LINK_ICON_PROD;
    if (!re.test(out)) throw new Error(`vite.config: el parche del icono de enlace ya no aplica en ${id}`);
    out = dev
      ? out.replace(LINK_ICON_DEV, LINK_ICON_DEV_FIX)
      : out.replace(LINK_ICON_PROD, (_m, head, el, st) =>
          `${head}${el}.link&&${el}.type!=="embeddable"&&!${st}.selectedElementIds[${el}.id])`);
  }
  return out === code ? undefined : out;
}

function noCdnFonts(): Plugin {
  return {
    name: "no-cdn-fonts",
    enforce: "pre",
    transform(code, id) {
      if (!isExcalidraw(id)) return;
      const out = patchExcalidraw(code, id);
      if (out) return { code: out, map: null };
    },
  };
}

export default defineConfig({
  plugins: [react(), noCdnFonts()],
  // En desarrollo Vite preempaqueta las dependencias con esbuild: mismo parche ahí.
  optimizeDeps: {
    esbuildOptions: {
      plugins: [
        {
          name: "no-cdn-fonts",
          setup(build) {
            build.onLoad({ filter: /@excalidraw[\\/]excalidraw[\\/].*\.js$/ }, async (args) => {
              const code = await readFile(args.path, "utf8");
              const out = patchExcalidraw(code, args.path);
              return out ? { contents: out, loader: "js" } : undefined;
            });
          },
        },
      ],
    },
  },
  // PIZARRA_BACKEND y PIZARRA_WEB_PORT dejan probar contra otro backend (p. ej. uno con un
  // workspace de pruebas) sin tocar el de siempre en 8765.
  server: {
    port: Number(process.env.PIZARRA_WEB_PORT ?? 5173),
    strictPort: true,
    proxy: {
      "/api": `http://${process.env.PIZARRA_BACKEND ?? "127.0.0.1:8765"}`,
      // La interfaz propia de los paquetes (PLAN_PAQUETES P47). Con el `Host` de Vite: el
      // backend escribe con él la CSP («scripts solo de <origen>/packs/<id>/ui/»), y con el
      // del backend los scripts que el marco pide a Vite quedarían fuera.
      "/packs": { target: `http://${process.env.PIZARRA_BACKEND ?? "127.0.0.1:8765"}`, changeOrigin: false },
      // La animación de un post-it (D175): sin token, fuera de /api.
      "/animations": `http://${process.env.PIZARRA_BACKEND ?? "127.0.0.1:8765"}`,
      "/ws": { target: `ws://${process.env.PIZARRA_BACKEND ?? "127.0.0.1:8765"}`, ws: true },
    },
  },
  define: { "process.env.IS_PREACT": JSON.stringify("false") },
  // `npm test` (vitest): los de la app y los de la interfaz de los paquetes del repo
  // (packs/*/ui-src, PLAN_PAQUETES P40), que sacan vitest y React de aquí (scripts/pack-ui.mjs).
  test: {
    dir: "../..",
    include: ["app/frontend/src/**/*.test.ts", "packs/*/ui-src/**/*.test.ts"],
    alias: packAlias,
  },
} as Parameters<typeof defineConfig>[0]);
