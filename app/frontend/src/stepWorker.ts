// Worker del visor STEP (plan D62): lee el STEP con OpenCASCADE en WebAssembly
// (occt-import-js, LGPL-2.1) fuera del hilo de la interfaz y devuelve la malla empaquetada
// (mesh.ts). La biblioteca no va en el bundle: está en /vendor/occt/ como archivos aparte y
// sustituibles, con su licencia (scripts/copy-occt.mjs). Es un script de Emscripten sin
// `export`, así que se carga como texto y se evalúa aquí (un worker de módulo no tiene
// importScripts); su `.wasm` lo pide él mismo a esa carpeta.
import { packMesh, type Part } from "./mesh";

const VENDOR = "/vendor/occt/";

type OcctMesh = {
  name?: string;
  color?: [number, number, number];
  attributes: { position: { array: number[] }; normal?: { array: number[] } };
  index: { array: number[] };
};
type Occt = { ReadStepFile: (data: Uint8Array, params: unknown) => { success: boolean; meshes: OcctMesh[] } };

let occt: Promise<Occt> | null = null;

function loadOcct(): Promise<Occt> {
  occt ??= (async () => {
    const r = await fetch(`${VENDOR}occt-import-js.js`);
    if (!r.ok) throw new StepError("no_instalado");
    const factory = new Function(`${await r.text()}\nreturn occtimportjs;`)() as
      (o: { locateFile: (f: string) => string }) => Promise<Occt>;
    return factory({ locateFile: (f) => `${VENDOR}${f}` });
  })();
  return occt;
}

// Lo fino de la malla: proporcional a la caja del modelo, como en Online3DViewer (el mismo
// lector), para que una pieza pequeña y un robot entero se vean igual de suaves.
const PARAMS = { linearUnit: "millimeter", linearDeflectionType: "bounding_box_ratio",
                 linearDeflection: 0.001, angularDeflection: 0.5 };

export type WorkerIn = { id: number; data: ArrayBuffer };
/** Los fallos conocidos van por código (`n`, cuántos cuerpos): el worker no sabe el idioma de
 *  la app, el texto lo pone el visor (StepViewer). */
export type StepErrorCode = "no_instalado" | "no_lee" | "sin_malla";
export type WorkerOut =
  | { id: number; stage: "biblioteca" | "leyendo" }
  | { id: number; ok: true; mesh: ArrayBuffer }
  | { id: number; ok: false; error: string; code?: StepErrorCode; n?: number };

class StepError extends Error {
  constructor(readonly code: StepErrorCode, readonly n?: number) { super(code); }
}

const post = (msg: WorkerOut, transfer: Transferable[] = []) =>
  (self as unknown as Worker).postMessage(msg, transfer);

self.onmessage = async (ev: MessageEvent<WorkerIn>) => {
  const { id, data } = ev.data;
  try {
    post({ id, stage: "biblioteca" });
    const lib = await loadOcct();
    post({ id, stage: "leyendo" });
    const res = lib.ReadStepFile(new Uint8Array(data), PARAMS);
    if (!res.success) throw new StepError("no_lee");
    // OpenCASCADE da los cuerpos pero sin triángulos cuando no le llega la memoria del visor
    // (2 GB de WebAssembly): con un STEP enorme, sin un solo triángulo, se dice, nunca una
    // ventana vacía. Si solo faltan algunos, se enseña lo demás y la barra dice cuántos.
    if (res.meshes.length && res.meshes.every((m) => !m.index.array.length)) {
      throw new StepError("sin_malla", res.meshes.length);
    }
    const parts: Part[] = res.meshes.map((m, i) => ({
      name: m.name || `Cuerpo ${i + 1}`,
      color: m.color ?? null,
      positions: new Float32Array(m.attributes.position.array),
      normals: m.attributes.normal ? new Float32Array(m.attributes.normal.array) : null,
      indices: new Uint32Array(m.index.array),
    }));
    const mesh = packMesh(parts);
    post({ id, ok: true, mesh }, [mesh]);
  } catch (e) {
    post({ id, ok: false, error: e instanceof Error ? e.message : String(e),
           ...(e instanceof StepError ? { code: e.code, n: e.n } : {}) });
  }
};
