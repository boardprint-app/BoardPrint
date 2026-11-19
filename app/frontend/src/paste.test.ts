// Lo pegado (D84, D137, D140): qué texto es un enlace, su título y su dominio, dónde entra una
// imagen y que la foto suelta nunca se deforma.
import { describe, expect, it } from "vitest";
import { cardSkeleton, IMAGE_CAPTION, IMAGE_LINK, IMAGE_MAX_WIDTH, imageBox, keepRatio, LINK_LINK,
         letterColor, linkDomain, linkInitial, linkTitle, pasteOnto, pastedUrl } from "./paste";
import { userEdit, type PostitData } from "./postit";

describe("pastedUrl: solo una URL http o https sola es un enlace", () => {
  it("una URL, sí", () => {
    expect(pastedUrl("https://docs.google.com/document/d/1/edit")).toBe("https://docs.google.com/document/d/1/edit");
    expect(pastedUrl("  http://localhost:5173/x \n")).toBe("http://localhost:5173/x");
  });
  it("texto, la copia de Excalidraw, una ruta u otro esquema, nunca", () => {
    for (const t of ["hola", "mira https://a.com", "https://a.com y más", '{"type":"excalidraw/clipboard"}',
                     "C:\\datos\\ficha.pdf", "file:///C:/x.pdf", "javascript:alert(1)", "ftp://a.com/x",
                     "https://", "", null, undefined]) {
      expect(pastedUrl(t), String(t)).toBeNull();
    }
  });
});

describe("título, dominio e inicial del enlace (D137, 5B)", () => {
  it("el título por defecto es el final de la URL, legible", () => {
    expect(linkTitle("https://harmonicdrive.de/es/productos/configurador-de-reductoras")).toBe("configurador de reductoras");
    expect(linkTitle("https://ejemplo.com/Ficha%20t%C3%A9cnica.pdf")).toBe("Ficha técnica.pdf");
  });
  it("salta lo que no dice nada («edit», «view») y, sin camino, es el dominio", () => {
    expect(linkTitle("https://docs.google.com/document/d/1AbC/edit")).toBe("1AbC");
    expect(linkTitle("https://www.schunk.com/")).toBe("schunk.com");
  });
  it("el dominio, sin www; la inicial, la del nombre y no la del subdominio", () => {
    expect(linkDomain("https://www.schunk.com/x")).toBe("schunk.com");
    expect(linkInitial("docs.google.com")).toBe("G");
    expect(linkInitial("harmonicdrive.de")).toBe("H");
    expect(linkInitial("localhost")).toBe("L");
  });
  it("el mismo dominio, siempre el mismo color", () =>
    expect(letterColor("docs.google.com")).toBe(letterColor("docs.google.com")));
});

describe("dónde entra una imagen pegada (D140)", () => {
  const box = { x: 0, y: 0, width: 260, height: 120 };
  const els = [
    { id: "p1", ...box, customData: { kind: "postit" } },
    { id: "b", ...box, customData: { kind: "block" } },
    { id: "p2", ...box, x: 500, customData: { kind: "postit" } },
  ];
  it("sobre un post-it, en ese post-it (el de más arriba)", () => {
    expect(pasteOnto(els, { x: 10, y: 10 })).toBe("p1");
    expect(pasteOnto(els, { x: 510, y: 10 })).toBe("p2");
  });
  it("fuera de un post-it, suelta", () => expect(pasteOnto(els, { x: 400, y: 10 })).toBeNull());
  it("un post-it oculto por el filtro o borrado no la recibe", () => {
    expect(pasteOnto(els, { x: 510, y: 10 }, (e) => e.id === "p2")).toBeNull();
    expect(pasteOnto([{ ...els[0], isDeleted: true }], { x: 10, y: 10 })).toBeNull();
  });
  it("pegada sobre un post-it nunca cambia su texto, y en uno del agente lo pasa al usuario", () => {
    const cd = { kind: "postit", postitKind: "nota", state: "abierto", text: "La pinza", author: "agent:design",
                 sources: [], estimate: false, anchor: null } as PostitData;
    const out = userEdit(cd, { image: { file: "a.png", width: 800, height: 600 } });
    expect(out.text).toBe("La pinza");
    expect(out.image?.file).toBe("a.png");
    expect([out.author, out.origin]).toEqual(["user", "agent:design"]);
  });
});

describe("la foto suelta nunca se deforma (D84)", () => {
  const img = { width: 800, height: 400 };
  it("nace con su proporción, nunca más ancha que el tope, con el pie debajo", () => {
    expect(imageBox(800, 400)).toEqual({ width: IMAGE_MAX_WIDTH, height: IMAGE_MAX_WIDTH / 2 + IMAGE_CAPTION });
    expect(imageBox(200, 100)).toEqual({ width: 200, height: 100 + IMAGE_CAPTION });
  });
  it("al estirarla, el alto lo da el ancho", () => {
    const cur = { x: 0, y: 0, width: 300, height: 400 };
    expect(keepRatio(cur, cur, img)).toEqual({ ...cur, height: 150 + IMAGE_CAPTION });
  });
  it("estirada por arriba, se queda quieto el borde de abajo", () => {
    const prev = { x: 0, y: 100, width: 200, height: 100 + IMAGE_CAPTION };
    const cur = { x: -100, y: 0, width: 300, height: 200 + IMAGE_CAPTION };
    const out = keepRatio(prev, cur, img)!;
    expect(out.height).toBe(150 + IMAGE_CAPTION);
    expect(out.y + out.height).toBe(cur.y + cur.height);
  });
  it("si ya está bien, nada", () =>
    expect(keepRatio(undefined, { x: 0, y: 0, width: 200, height: 100 + IMAGE_CAPTION }, img)).toBeNull());
});

describe("el elemento nuevo de una foto o un enlace", () => {
  it("lleva su propio enlace interno, centrado donde se pegó, con autor y fecha", () => {
    const f = cardSkeleton("image", "f1", { x: 100, y: 100 }, { width: 200, height: 120 }, { image: { file: "a.png" } });
    expect([f.link, f.x, f.y, f.customData.kind, f.customData.author]).toEqual([IMAGE_LINK + "f1", 0, 40, "image", "user"]);
    expect(cardSkeleton("link", "l1", { x: 0, y: 0 }, { width: 10, height: 10 }, {}).link).toBe(LINK_LINK + "l1");
  });
});
