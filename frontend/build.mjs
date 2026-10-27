// Bundles src/ into dist/ with esbuild. No framework build step, no CDN:
// everything is served from the app's own origin to satisfy the strict CSP.
import { build, context } from "esbuild";
import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";

const watch = process.argv.includes("--watch");

rmSync("dist", { recursive: true, force: true });
mkdirSync("dist/assets", { recursive: true });
mkdirSync("dist/app", { recursive: true });
cpSync("public/index.html", "dist/index.html");
cpSync("public/app.html", "dist/app/index.html");
// Installable public app: manifest, home-screen icons and the offline service worker.
cpSync("public/manifest.webmanifest", "dist/manifest.webmanifest");
cpSync("public/sw.js", "dist/sw.js");
cpSync("public/icons", "dist/icons", { recursive: true });
// One stylesheet: core styles plus each module's src/modules/<name>/<name>.css.
const moduleCss = readdirSync("src/modules", { withFileTypes: true })
  .filter((d) => d.isDirectory() && existsSync(`src/modules/${d.name}/${d.name}.css`))
  .map((d) => `/* module: ${d.name} */\n` + readFileSync(`src/modules/${d.name}/${d.name}.css`, "utf8"));
writeFileSync("dist/assets/styles.css", [readFileSync("src/styles.css", "utf8"), ...moduleCss].join("\n"));

const options = {
  // Two bundles: the public site and the signed-in app (ADR-06).
  entryPoints: { site: "src/main.tsx", app: "src/app/main.tsx" },
  bundle: true,
  outdir: "dist/assets",
  splitting: true,
  chunkNames: "chunks/[name]-[hash]",
  format: "esm",
  target: "es2022",
  jsx: "automatic",
  minify: !watch,
  sourcemap: true,
  define: { "process.env.NODE_ENV": JSON.stringify(watch ? "development" : "production") },
  // Allows building against globally installed packages in restricted sandboxes.
  nodePaths: process.env.NODE_PATH ? process.env.NODE_PATH.split(":") : [],
  logLevel: "info",
};

if (watch) {
  const ctx = await context(options);
  await ctx.watch();
} else {
  await build(options);
}
