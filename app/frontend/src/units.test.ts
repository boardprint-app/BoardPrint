// Unidades en pantalla (plan D182, §10): enseñar y editar en otra unidad nunca mueve lo
// guardado; una unidad que la tabla no conoce nunca se convierte.
import { describe, expect, it } from "vitest";
import { cleanPrefs, commitText, editText, fromShown, IMPERIAL, shownUnit, SI, toShown } from "./units";

describe("unidades en pantalla", () => {
  it("convierte al pintar a la unidad elegida", () => {
    expect(toShown(25.4, "mm", IMPERIAL)).toBeCloseTo(1, 12);
    expect(shownUnit("mm", IMPERIAL)).toBe("in");
    expect(toShown(1, "kg", IMPERIAL)).toBeCloseTo(2.20462262, 6);
    expect(shownUnit("deg", SI)).toBe("°");
    expect(toShown(0.5, "m", SI)).toBe(500);              // un alcance en m se enseña en mm
  });

  it("lo editado en pulgadas se guarda en mm", () => {
    expect(fromShown(2, "mm", IMPERIAL)).toBeCloseTo(50.8, 12);
    expect(commitText(300, editText(300, "mm", IMPERIAL), "12", "mm", IMPERIAL)).toBeCloseTo(304.8, 12);
  });

  it("sin deriva tras diez ediciones sin tocar el texto", () => {
    let v = 300;
    for (let i = 0; i < 10; i++) {
      const shown = editText(v, "mm", IMPERIAL);
      v = commitText(v, shown, shown, "mm", IMPERIAL)!;
    }
    expect(v).toBe(300);
  });

  it("enseñar y volver a escribir lo enseñado da el mismo valor que en mm", () => {
    for (const mm of [300, 123.456, 0.1, 2500]) {
      const typed = editText(mm, "mm", IMPERIAL);
      // 6 cifras significativas en pulgadas: menos de una micra de diferencia
      expect(commitText(mm, "", typed, "mm", IMPERIAL)).toBeCloseTo(mm, 2);
    }
  });

  it("una unidad que la tabla no conoce nunca se convierte", () => {
    for (const u of ["MPa", "deg/s", "m/s²", "kg/m3", "-", ""]) {
      expect(toShown(7.5, u, IMPERIAL)).toBe(7.5);
      expect(fromShown(7.5, u, IMPERIAL)).toBe(7.5);
      expect(shownUnit(u, IMPERIAL)).toBe(u);
    }
  });

  it("lo que no es un número no se guarda", () => {
    expect(commitText(300, "11.81", "abc", "mm", IMPERIAL)).toBeNull();
  });

  it("unas unidades ilegibles dan SI", () => {
    expect(cleanPrefs({ longitud: "pies", masa: 3 })).toEqual(SI);
    expect(cleanPrefs(null)).toEqual(SI);
    expect(cleanPrefs({ longitud: "in" }).longitud).toBe("in");
  });
});
