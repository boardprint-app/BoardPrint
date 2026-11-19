// Visor STEP propio (plan D62, D135): three.js con la malla que saca el worker (stepWorker.ts)
// o la de la caché del backend por hash del archivo. Se gira con el ratón (botón izquierdo),
// se desplaza con el derecho y se acerca con la rueda; «Encuadrar» vuelve a la vista inicial
// (isométrica, Z arriba como en Fusion). Se carga solo al previsualizar un STEP (lazy en
// Preview.tsx): three.js no pesa en la pizarra.
import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { apiFetch } from "./auth";
import { getLanguage, t } from "./i18n";
import { triangles, unpackMesh, type Part } from "./mesh";
import type { WorkerIn, WorkerOut } from "./stepWorker";

const STAGES = new Set(["cache", "bajando", "biblioteca", "leyendo"]);
const stageText = (stage: string) => (STAGES.has(stage) ? t(`bloques.step.etapa_${stage}`) : stage);

type Loaded = { parts: Part[]; seconds: number; cached: boolean };

/** La malla de un STEP: de la caché si está (por el hash de su contenido), si no, leída en el
 *  worker y guardada en la caché para la próxima vez. */
function useStepMesh(rawUrl: string, hash: string | null) {
  const [stage, setStage] = useState("cache");
  const [elapsed, setElapsed] = useState(0);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let worker: Worker | null = null;
    const t0 = performance.now();
    const tick = window.setInterval(() => setElapsed((performance.now() - t0) / 1000), 250);
    const done = (parts: Part[], cached: boolean) => {
      if (cancelled) return;
      window.clearInterval(tick);
      setLoaded({ parts, seconds: (performance.now() - t0) / 1000, cached });
    };
    const fail = (msg: string) => {
      if (cancelled) return;
      window.clearInterval(tick);
      setError(msg);
    };
    (async () => {
      if (hash) {
        const r = await apiFetch(`/api/mesh/${hash}`);
        if (r.status === 200) {                  // 204: no está en la caché
          try {
            const parts = unpackMesh(await r.arrayBuffer());
            if (triangles(parts) > 0) return done(parts, true);
          } catch { /* malla de la caché estropeada: se vuelve a leer el STEP */ }
          // Sin triángulos o estropeada: se vuelve a leer el STEP (y su error se dice).
        }
      }
      if (cancelled) return;
      setStage("bajando");
      const r = await apiFetch(rawUrl);
      if (!r.ok) return fail((await r.json().catch(() => null))?.detail ?? `error ${r.status}`);
      const data = await r.arrayBuffer();
      if (cancelled) return;
      worker = new Worker(new URL("./stepWorker.ts", import.meta.url), { type: "module" });
      worker.onerror = (e) => fail(t("bloques.step.visor_fallo", { error: e.message || t("bloques.step.sin_memoria") }));
      worker.onmessage = async (ev: MessageEvent<WorkerOut>) => {
        const msg = ev.data;
        if ("stage" in msg) return setStage(msg.stage);
        worker?.terminate();
        if (!msg.ok) return fail(msg.code ? t(`bloques.step.error_${msg.code}`, { n: msg.n ?? 0 }) : msg.error);
        let parts: Part[];
        try {
          parts = unpackMesh(msg.mesh);
        } catch (e) {
          return fail(String(e));
        }
        done(parts, false);
        if (hash) {
          void apiFetch(`/api/mesh/${hash}`, { method: "PUT", body: msg.mesh,
                                              headers: { "Content-Type": "application/octet-stream" } });
        }
      };
      worker.postMessage({ id: 1, data } satisfies WorkerIn, [data]);
    })().catch((e) => fail(String(e)));
    return () => {
      cancelled = true;
      window.clearInterval(tick);
      worker?.terminate();          // cerrar el visor para la lectura
    };
  }, [rawUrl, hash]);
  return { stage: stageText(stage), elapsed, loaded, error };
}

const GREY = new THREE.Color(0.72, 0.75, 0.78);

export default function StepViewer({ rawUrl, hash }: { rawUrl: string; hash: string | null }) {
  const { stage, elapsed, loaded, error } = useStepMesh(rawUrl, hash);
  const box = useRef<HTMLDivElement>(null);
  const fitRef = useRef<() => void>(() => {});

  useEffect(() => {
    const host = box.current;
    if (!host || !loaded) return;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    host.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 1e7);
    camera.up.set(0, 0, 1);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x445066, 1.3));
    const key = new THREE.DirectionalLight(0xffffff, 1.8);
    key.position.set(1, 1.5, 2);
    camera.add(key);                         // la luz va con la cámara: nunca una cara a oscuras
    scene.add(camera);

    const group = new THREE.Group();
    for (const p of loaded.parts) {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.BufferAttribute(p.positions, 3));
      if (p.normals) geo.setAttribute("normal", new THREE.BufferAttribute(p.normals, 3));
      geo.setIndex(new THREE.BufferAttribute(p.indices, 1));
      if (!p.normals) geo.computeVertexNormals();
      const mat = new THREE.MeshStandardMaterial({
        color: p.color ? new THREE.Color(...p.color) : GREY, metalness: 0.15, roughness: 0.55,
        side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1,
      });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.name = p.name;
      group.add(mesh);
    }
    scene.add(group);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.12;

    const fit = () => {
      const bb = new THREE.Box3().setFromObject(group);
      if (bb.isEmpty()) return;
      const sphere = bb.getBoundingSphere(new THREE.Sphere());
      const fov = THREE.MathUtils.degToRad(camera.fov);
      const dist = (sphere.radius / Math.sin(fov / 2)) * 1.08;
      const dir = new THREE.Vector3(1, -1.25, 0.9).normalize();
      camera.position.copy(sphere.center).addScaledVector(dir, dist);
      camera.near = Math.max(dist / 1000, 1e-3);
      camera.far = dist * 100;
      camera.updateProjectionMatrix();
      controls.target.copy(sphere.center);
      controls.update();
    };
    fitRef.current = fit;

    const resize = () => {
      const w = host.clientWidth, h = host.clientHeight;
      renderer.setSize(w, h, false);
      camera.aspect = w / Math.max(h, 1);
      camera.updateProjectionMatrix();
    };
    resize();
    fit();
    const ro = new ResizeObserver(resize);
    ro.observe(host);
    let frame = 0;
    const loop = () => {
      controls.update();
      renderer.render(scene, camera);
      frame = requestAnimationFrame(loop);
    };
    loop();
    return () => {
      cancelAnimationFrame(frame);
      ro.disconnect();
      controls.dispose();
      group.traverse((o) => {
        if (o instanceof THREE.Mesh) { o.geometry.dispose(); (o.material as THREE.Material).dispose(); }
      });
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [loaded]);

  const tris = loaded ? triangles(loaded.parts) : 0;
  const empty = loaded ? loaded.parts.filter((p) => !p.indices.length).length : 0;
  const locale = getLanguage() === "en" ? "en-US" : "es-ES";
  return (
    <div className="pv-step">
      <div className="pv-step-canvas" ref={box} />
      {!loaded && !error && (
        <div className="pv-wait">
          <span className="pv-spin" aria-hidden="true" />
          {stage} <span className="pv-secs">{elapsed.toFixed(0)} s</span>
        </div>
      )}
      {error && <div className="pv-wait pv-err">{t("bloques.vista.no_se_puede", { error })}</div>}
      {loaded && (
        <div className="pv-step-bar">
          <span>
            {t(loaded.parts.length === 1 ? "bloques.step.cuerpos_uno" : "bloques.step.cuerpos_varios", { n: loaded.parts.length })}
            {empty > 0 && <span className="pv-err"> ({t("bloques.step.sin_malla", { n: empty })})</span>} ·{" "}
            {t("bloques.step.triangulos", { n: tris.toLocaleString(locale) })} ·{" "}
            {loaded.cached ? t("bloques.step.de_cache")
              : t("bloques.step.leido_en", { s: loaded.seconds.toLocaleString(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 }) })}
          </span>
          <span className="pv-hint">{t("bloques.step.ayuda")}</span>
          <button type="button" className="ubtn" onClick={() => fitRef.current()}>{t("bloques.step.encuadrar")}</button>
        </div>
      )}
    </div>
  );
}
