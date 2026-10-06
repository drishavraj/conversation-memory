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
  "design-system.css",
  "memory-map.css",
  "chat-ui.css",
  "manifest.webmanifest",
  "icon.svg",
  "icon-180.png",
  "icon-192.png",
  "icon-512.png",
])
  await copyFile(`src/${file}`, `../app/static/${file}`);

await mkdir("../app/static/fonts", { recursive: true });
for (const weight of [400, 500, 600]) await copyFile(`node_modules/@fontsource/inter/files/inter-latin-${weight}-normal.woff2`, `../app/static/fonts/inter-latin-${weight}-normal.woff2`);
await copyFile("node_modules/@fontsource/inter/LICENSE", "../app/static/fonts/INTER-LICENSE.txt");
