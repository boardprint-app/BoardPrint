// La malla del visor STEP en la caché (plan D62, §10): vuelve idéntica, y un binario que no
// cuadra da error entero, nunca una malla a medias.
import { describe, expect, it } from "vitest";
import { packMesh, triangles, unpackMesh, type Part } from "./mesh";

const PARTS: Part[] = [
  { name: "Base", color: [0.5, 0.5, 0.55], positions: new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]),
    normals: new Float32Array([0, 0, 1, 0, 0, 1, 0, 0, 1]), indices: new Uint32Array([0, 1, 2]) },
  { name: "Brida ñ", color: null, positions: new Float32Array([0, 0, 1, 1, 0, 1, 0, 1, 1, 1, 1, 1]),
    normals: null, indices: new Uint32Array([0, 1, 2, 1, 3, 2]) },
];

describe("malla del visor STEP (D62)", () => {
  it("vuelve idéntica, con nombres, colores y normales", () => {
    const back = unpackMesh(packMesh(PARTS));
    expect(back.map((p) => [p.name, p.color, !!p.normals])).toEqual([
      ["Base", [0.5, 0.5, 0.55], true], ["Brida ñ", null, false]]);
    expect(Array.from(back[1].positions)).toEqual(Array.from(PARTS[1].positions));
    expect(Array.from(back[0].normals!)).toEqual(Array.from(PARTS[0].normals!));
    expect(Array.from(back[1].indices)).toEqual([0, 1, 2, 1, 3, 2]);
    expect(triangles(back)).toBe(3);
  });
  it("una malla vacía también vale", () => {
    expect(unpackMesh(packMesh([]))).toEqual([]);
  });
  it("un binario cortado, ajeno o que apunta fuera da error, nunca media malla", () => {
    const good = packMesh(PARTS);
    expect(() => unpackMesh(good.slice(0, good.byteLength - 4))).toThrow(/cortados/);
    expect(() => unpackMesh(new TextEncoder().encode("PNG!....").buffer)).toThrow(/no es una malla/);
    expect(() => unpackMesh(new ArrayBuffer(3))).toThrow(/corta/);
    const longer = new Uint8Array(good.byteLength + 4);
    longer.set(new Uint8Array(good));
    expect(() => unpackMesh(longer.buffer)).toThrow(/sobran/);
    const bad = packMesh([{ ...PARTS[0], indices: new Uint32Array([0, 1, 7]) }]);
    expect(() => unpackMesh(bad)).toThrow(/vértice/);
  });
});
