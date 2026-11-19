// Malla del visor STEP en binario (plan D62): lo que el worker saca de OpenCASCADE y lo que se
// guarda en la caché del backend por hash del archivo (`/api/mesh/<hash>`), para no volver a
// leer el STEP. Formato:
//   "PZM1" · u32 largo de la cabecera · cabecera JSON (UTF-8) · relleno hasta múltiplo de 4 ·
//   por cada malla: posiciones (f32 × 3n), normales (f32 × 3n, si las hay), índices (u32 × m).
// Un binario que no cuadra da error entero: nunca se enseña una malla a medias. Si cambia el
// formato, cambia la marca y `MESH_FORMAT` del backend (files_api.py).

export type Part = {
  name: string;
  color: [number, number, number] | null;    // 0-1, el del STEP si lo trae
  positions: Float32Array;
  normals: Float32Array | null;
  indices: Uint32Array;
};

const MAGIC = "PZM1";
type Head = { meshes: { name: string; color: [number, number, number] | null; vertices: number; indices: number; normals: boolean }[] };

const pad4 = (n: number) => (n + 3) & ~3;

export function packMesh(parts: Part[]): ArrayBuffer {
  const head: Head = {
    meshes: parts.map((p) => ({ name: p.name, color: p.color, vertices: p.positions.length / 3,
                                indices: p.indices.length, normals: !!p.normals })),
  };
  const json = new TextEncoder().encode(JSON.stringify(head));
  let size = pad4(8 + json.length);
  for (const p of parts) size += (p.positions.length + (p.normals?.length ?? 0) + p.indices.length) * 4;
  const buf = new ArrayBuffer(size);
  const bytes = new Uint8Array(buf);
  bytes.set(new TextEncoder().encode(MAGIC), 0);
  new DataView(buf).setUint32(4, json.length, true);
  bytes.set(json, 8);
  let at = pad4(8 + json.length);
  for (const p of parts) {
    new Float32Array(buf, at, p.positions.length).set(p.positions);
    at += p.positions.length * 4;
    if (p.normals) {
      new Float32Array(buf, at, p.normals.length).set(p.normals);
      at += p.normals.length * 4;
    }
    new Uint32Array(buf, at, p.indices.length).set(p.indices);
    at += p.indices.length * 4;
  }
  return buf;
}

export function unpackMesh(buf: ArrayBuffer): Part[] {
  const fail = (why: string): never => { throw new Error(`malla no válida: ${why}`); };  // i18n-ok diagnóstico interno
  if (buf.byteLength < 8) fail("demasiado corta");
  const bytes = new Uint8Array(buf);
  if (new TextDecoder().decode(bytes.subarray(0, 4)) !== MAGIC) fail("no es una malla del visor");
  const len = new DataView(buf).getUint32(4, true);
  if (8 + len > buf.byteLength) fail("cabecera cortada");
  let head: Head;
  try {
    head = JSON.parse(new TextDecoder().decode(bytes.subarray(8, 8 + len)));
  } catch {
    return fail("cabecera ilegible");
  }
  if (!Array.isArray(head?.meshes)) fail("cabecera sin mallas");
  let at = pad4(8 + len);
  const parts: Part[] = [];
  for (const m of head.meshes) {
    const v = m.vertices * 3, need = (v * (m.normals ? 2 : 1) + m.indices) * 4;
    if (!Number.isInteger(v) || !Number.isInteger(m.indices) || at + need > buf.byteLength) fail("datos cortados");
    const positions = new Float32Array(buf.slice(at, at + v * 4));
    at += v * 4;
    let normals: Float32Array | null = null;
    if (m.normals) {
      normals = new Float32Array(buf.slice(at, at + v * 4));
      at += v * 4;
    }
    const indices = new Uint32Array(buf.slice(at, at + m.indices * 4));
    at += m.indices * 4;
    if (indices.some((i) => i >= m.vertices)) fail(`«${m.name}» apunta a un vértice que no tiene`);  // i18n-ok diagnóstico interno
    parts.push({ name: String(m.name ?? ""), color: m.color ?? null, positions, normals, indices });
  }
  if (at !== buf.byteLength) fail("sobran datos");
  return parts;
}

/** Triángulos de toda la malla (lo que dice el visor al cargar). */
export const triangles = (parts: Part[]) => parts.reduce((n, p) => n + p.indices.length / 3, 0);
