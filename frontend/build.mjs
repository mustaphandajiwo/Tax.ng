// Bundles src/ into dist/ with esbuild. No framework build step, no CDN:
// everything is served from the app's own origin to satisfy the strict CSP.
import { build, context } from "esbuild";
import { cpSync, mkdirSync, rmSync } from "node:fs";

const watch = process.argv.includes("--watch");

rmSync("dist", { recursive: true, force: true });
mkdirSync("dist/assets", { recursive: true });
cpSync("public/index.html", "dist/index.html");
cpSync("src/styles.css", "dist/assets/styles.css");

const options = {
  entryPoints: ["src/main.tsx"],
  bundle: true,
  outfile: "dist/assets/app.js",
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
