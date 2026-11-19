// Tarjeta del bloque (D77, D60): el alto nunca deja contenido escondido y la rueda no se
// queda atascada encima de un bloque.
import { describe, expect, it } from "vitest";
import { BLOCK_MIN_HEIGHT, blockHeight, wheelToCanvas } from "./block";

describe("alto del bloque", () => {
  it("crece hasta su contenido", () => {
    expect(blockHeight(220, 310.4)).toBe(311);
  });
  it("una tarjeta vuelve a encoger cuando sus salidas se acortan", () => {
    expect(blockHeight(400, 200, 400)).toBe(200);     // el alto lo había puesto ella
    expect(blockHeight(400, 200)).toBe(200);          // recién montada: manda el contenido
  });
  it("respeta un alto mayor que puso el usuario, pero nunca deja contenido escondido", () => {
    expect(blockHeight(400, 200, 311)).toBe(400);     // la estiró de 311 a 400
    expect(blockHeight(400, 450.2, 311)).toBe(451);   // y luego el contenido pasa de ahí
  });
  it("nunca baja del mínimo", () => {
    expect(blockHeight(50, 30)).toBe(BLOCK_MIN_HEIGHT);
  });
});

describe("rueda encima de un bloque", () => {
  const still = { scrollTop: 0, scrollHeight: 200, clientHeight: 200 };   // no se desplaza
  const mid = { scrollTop: 50, scrollHeight: 400, clientHeight: 200 };
  const plain = { ctrlKey: false, metaKey: false };

  it("va al lienzo si la tarjeta no se puede desplazar", () => {
    expect(wheelToCanvas({ ...plain, deltaY: 100 }, still)).toBe(true);
    expect(wheelToCanvas({ ...plain, deltaY: -100 }, still)).toBe(true);
  });
  it("se queda en la tarjeta si aún puede desplazarse en esa dirección", () => {
    expect(wheelToCanvas({ ...plain, deltaY: 100 }, mid)).toBe(false);
    expect(wheelToCanvas({ ...plain, deltaY: -100 }, mid)).toBe(false);
  });
  it("vuelve al lienzo al llegar al final", () => {
    expect(wheelToCanvas({ ...plain, deltaY: 100 }, { scrollTop: 200, scrollHeight: 400, clientHeight: 200 })).toBe(true);
  });
  it("con Ctrl o Cmd (zoom) va siempre al lienzo", () => {
    expect(wheelToCanvas({ deltaY: 100, ctrlKey: true, metaKey: false }, mid)).toBe(true);
    expect(wheelToCanvas({ deltaY: 100, ctrlKey: false, metaKey: true }, mid)).toBe(true);
  });
});
