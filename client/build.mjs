// Bundles src/main.jsx into ../smms/static/dist/app.js (the Flask server serves this file).
import { build, context } from "esbuild";
const opts = {
  entryPoints: ["src/main.jsx"],
  outfile: "../smms/static/dist/app.js",
  bundle: true, minify: true, sourcemap: false, format: "iife", target: ["es2020"],
  jsx: "automatic", loader: { ".js": "jsx" },
  define: { "process.env.NODE_ENV": '"production"' },
  logLevel: "info",
};
if (process.argv.includes("--watch")) { const c = await context(opts); await c.watch(); console.log("watching..."); }
else await build(opts);
