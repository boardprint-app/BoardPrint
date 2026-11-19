// Conexión con el proyecto abierto (una por proyecto, plan D69). Reintenta si el backend se
// reinicia, salvo si el proyecto ya no existe o se ha borrado: entonces avisa y para.
import { wsUrl } from "./auth";

type Handler = (msg: any) => void;

const GONE = new Set([4404, 4410]); // proyecto que no existe / borrado

let ws: WebSocket | null = null;
let generation = 0;
const queue: string[] = [];

export function connect(project: string, onMessage: Handler, onGone: () => void) {
  disconnect();
  const gen = ++generation;
  const open = () => {
    const sock = new WebSocket(wsUrl(project));
    ws = sock;
    sock.onopen = () => {
      while (queue.length) sock.send(queue.shift()!);
    };
    sock.onmessage = (ev) => onMessage(JSON.parse(ev.data));
    sock.onclose = (ev) => {
      if (gen !== generation) return; // ya se ha abierto otro proyecto
      if (GONE.has(ev.code)) onGone();
      else setTimeout(() => gen === generation && open(), 1000);
    };
  };
  open();
}

export function disconnect() {
  generation++;
  queue.length = 0;
  const old = ws;
  ws = null;
  old?.close();
}

export function send(msg: object) {
  const data = JSON.stringify(msg);
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(data);
  else queue.push(data);
}
