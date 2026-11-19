# App de la pizarra (en construcción)

Diseño y decisiones: `docs/PLAN_PIZARRA.md` (del repo de desarrollo). Hoy hay el spike
FF 3.1: pizarra Excalidraw con bloques ejecutables (Tubo → Voladizo, con el motor real) y
post-its de agente validados.

## Arrancar en desarrollo

Dos terminales desde la raíz del repo:

```bash
# 1. Backend (127.0.0.1:8765). En desarrollo todo vive en out/dev/: settings.toml y el
#    workspace «Personal» en out/dev/Documentos/BoardPrint/. La primera vez copia ahí la
#    pizarra de out/spike_pizarra/ como proyecto «Spike» (plan D67, D70).
.venv/Scripts/python.exe -m pip install -r app/backend/requirements.txt   # una vez
cd app/backend && ../../.venv/Scripts/python.exe -m pizarra.server

# 2. Frontend (http://localhost:5173)
cd app/frontend && npm install && npm run dev
```

Para usar un bloque: selecciónalo y vuelve a hacer clic dentro para activarlo. Las flechas
se dibujan con la herramienta de flecha (tecla `A`) de un bloque a otro.

Se abre el último proyecto; la primera vez, la pantalla de inicio (de momento una lista
provisional). Abrir el mismo proyecto en dos pestañas sirve para ver los cambios de una en la
otra.

Post-it de agente de prueba en un proyecto (rechazado con 422 si lleva cifras sin fuente; el
id sale de `GET /api/workspace`):

```bash
curl -X POST http://127.0.0.1:8765/api/projects/<id>/agent/postit -H "Content-Type: application/json" \
  -d '{"text": "Revisa la unión del extremo", "kind": "riesgo"}'
```

## Tests

```bash
cd app/backend && ../../.venv/Scripts/python.exe -m unittest discover -s tests -t .
cd app/frontend && npx tsc -p . && npm test
```
