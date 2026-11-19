// La bienvenida (plan D186, §10) y el aviso de la primera animación (D187): cuándo sale, los
// pasos, qué guardan *Saltar* y *Terminar*, y adónde lleva *Ir a Ajustes*.
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AppSettings } from "./appSettings";
import { goToAnimationSettings, animationNoticeShown, NOTICE_ROW, NOTICE_TAB, showAnimationNotice } from "./animationNotice";
import { BLINK_MS, closeSettings, getSettings } from "./settings";
import {
  closeWelcome, connectorList, finishWelcome, planLabel, getWelcome, goToStep, LAST_STEP, nextStep, openWelcome,
  prevStep, readyToShow, sameFolder, waitForRestart, welcomeOnLoad, WELCOME_STEPS,
} from "./welcome";

const settings = (vista: boolean) => ({ bienvenida_vista: vista }) as AppSettings;

describe("cuándo sale la bienvenida", () => {
  beforeEach(() => closeWelcome());

  it("solo si los ajustes han llegado y dicen que no se ha visto", () => {
    expect(welcomeOnLoad(settings(false))).toBe(true);
    expect(welcomeOnLoad(settings(true))).toBe(false);
  });

  it("nunca con los ajustes sin cargar (el backend no responde)", () => {
    expect(welcomeOnLoad(null)).toBe(false);
  });

  it("al pedirla sale por el primer paso, aunque ya estuviera en otro", () => {
    openWelcome();
    goToStep(2);
    openWelcome();
    expect(getWelcome()).toEqual({ open: true, step: 0 });
  });
});

describe("cuándo se pinta el inicio o la pizarra", () => {
  const project = { view: "project", project: "p" };

  it("no antes de haber pedido los ajustes: Excalidraw tomaría el idioma de antes", () => {
    expect(readyToShow(project, false)).toBe(false);
    expect(readyToShow(null, true)).toBe(false);
    expect(readyToShow(project, true)).toBe(true);
  });
});

describe("los pasos", () => {
  it("son cuatro, en el orden del plan", () => {
    expect(WELCOME_STEPS).toEqual(["idioma", "sesion", "programas", "carpeta"]);
    expect(LAST_STEP).toBe(3);
  });

  it("siguiente y anterior no se salen de los cuatro", () => {
    expect(nextStep(0)).toBe(1);
    expect(nextStep(LAST_STEP)).toBe(LAST_STEP);
    expect(prevStep(2)).toBe(1);
    expect(prevStep(0)).toBe(0);
    goToStep(9);
    expect(getWelcome().step).toBe(LAST_STEP);
  });
});

describe("Saltar y Terminar", () => {
  it("guardan bienvenida_vista: true y cierran", async () => {
    openWelcome();
    const save = vi.fn(async () => null);
    expect(await finishWelcome(save)).toBeNull();
    expect(save).toHaveBeenCalledWith({ bienvenida_vista: true });
    expect(getWelcome().open).toBe(false);
  });

  it("cierran aunque no se pueda guardar (nunca bloquea) y dan el motivo", async () => {
    openWelcome();
    expect(await finishWelcome(async () => "sin backend")).toBe("sin backend");
    expect(getWelcome().open).toBe(false);
  });
});

describe("el paso de los programas (el núcleo no nombra ningún paquete, P67)", () => {
  it("cada conector con el nombre de su paquete: abierto, abriéndose o sin abrir", () => {
    expect(connectorList({
      b: { name: "Zeta", available: false, launching: false },
      a: { name: "Alfa", available: true, launching: false },
      c: { available: false, launching: true },
    })).toEqual([
      { id: "a", name: "Alfa", state: "disponible" },
      { id: "c", name: "c", state: "abriendose" },
      { id: "b", name: "Zeta", state: "cerrado" },
    ]);
  });

  it("sin ningún paquete con programa, la lista sale vacía", () => {
    expect(connectorList({})).toEqual([]);
    expect(connectorList(null)).toEqual([]);
  });
});

describe("cambiar de carpeta: esperar al servidor rearrancado", () => {
  const clock = () => {
    let t = 0;
    return { now: () => t, sleep: async (n: number) => { t += n; } };
  };

  it("la misma carpeta con otras mayúsculas o barras", () => {
    expect(sameFolder("C:\\Users\\Ana\\Proyectos\\", "c:/users/ana/proyectos")).toBe(true);
    expect(sameFolder("C:\\A", "C:\\B")).toBe(false);
    expect(sameFolder(null, "C:\\A")).toBe(false);
  });

  it("vale cuando el health ya da la carpeta nueva", async () => {
    const answers = [{ workspace: "C:\\viejo" }, { workspace: "C:\\Nuevo" }];
    const ok = await waitForRestart("C:\\nuevo", async () => answers.shift() ?? null, clock());
    expect(ok).toBe(true);
  });

  it("vale cuando vuelve a responder tras dejar de hacerlo", async () => {
    const answers = [null, null, { workspace: "D:\\resuelta" }];
    expect(await waitForRestart("C:\\nuevo", async () => answers.shift() ?? null, clock())).toBe(true);
  });

  it("se rinde a los 15 s si el de antes sigue igual", async () => {
    expect(await waitForRestart("C:\\nuevo", async () => ({ workspace: "C:\\viejo" }), clock())).toBe(false);
  });
});

describe("el aviso de la primera animación", () => {
  beforeEach(() => closeSettings());

  it("Ir a Ajustes abre Agentes con la fila de las animaciones marcada y quita el aviso", () => {
    showAnimationNotice();
    goToAnimationSettings();
    const s = getSettings();
    expect(s.open).toBe(true);
    expect(s.tab).toBe("agentes");
    expect(s.highlight).toBe("animaciones_automaticas");
    expect([NOTICE_TAB, NOTICE_ROW]).toEqual(["agentes", "animaciones_automaticas"]);
    expect(animationNoticeShown()).toBe(false);
  });

  it("la fila parpadea una vez durante medio segundo", () => {
    expect(BLINK_MS).toBe(500);
  });
});

describe("el plan de la cuenta de Claude", () => {
  it("se escribe como nombre propio, nunca en minúscula («Plan: Max»)", () => {
    expect(planLabel("max")).toBe("Max");
    expect(planLabel("pro")).toBe("Pro");
    expect(planLabel("claude_max")).toBe("Claude Max");
    expect(planLabel("ENTERPRISE")).toBe("Enterprise");
  });
});
