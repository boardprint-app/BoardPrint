// Falla si la interfaz compilada conserva alguna referencia al CDN de fuentes (plan D44).
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const dir = "dist/assets";
const hits = readdirSync(dir)
  .filter((f) => f.endsWith(".js"))
  .filter((f) => readFileSync(join(dir, f), "utf8").includes("esm.sh"));
if (hits.length) {
  console.error(`la interfaz compilada aún referencia esm.sh: ${hits.join(", ")}`);
  process.exit(1);
}
console.log("sin referencias a CDN externos");
