import { build } from "esbuild";
import { mkdir, copyFile } from "node:fs/promises";
await mkdir("../app/static", { recursive: true });
await build({
  entryPoints: ["src/app.js"],
  bundle: true,
  minify: true,
  format: "esm",
  outfile: "../app/static/app.js",
});
for (const file of [
  "index.html",
  "style.css",
  "manifest.webmanifest",
  "icon.svg",
  "icon-180.png",
  "icon-192.png",
  "icon-512.png",
])
  await copyFile(`src/${file}`, `../app/static/${file}`);
