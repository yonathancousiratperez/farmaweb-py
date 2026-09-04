// @ts-check
import { defineConfig } from "astro/config";
import react from "@astrojs/react";
import tailwindcss from "@tailwindcss/vite";

// Salida estatica: el sitio se sirve desde GitHub Pages, sin servidor. Todo lo
// dinamico (busqueda, promos vigentes) lo resuelve el navegador contra
// PostgREST con la key publishable, que es publica por diseno — la seguridad la
// da RLS, no el secreto de la key.
//
// SITE y BASE salen del entorno porque dependen de donde se publique:
//   · repo de proyecto  -> https://USUARIO.github.io  + base "/farmaweb-py/"
//   · repo USUARIO.github.io o dominio propio -> base "/"
// Hardcodear una de las dos formas rompe todos los enlaces internos en la otra.
const SITE = process.env.PUBLIC_SITE_URL || "http://localhost:4321";
const BASE = process.env.PUBLIC_BASE_PATH || "/";

export default defineConfig({
  site: SITE,
  base: BASE,
  output: "static",
  trailingSlash: "ignore",
  integrations: [react()],
  vite: { plugins: [tailwindcss()] },
});
