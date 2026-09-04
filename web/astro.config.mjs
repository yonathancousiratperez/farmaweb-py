// @ts-check
import { defineConfig } from "astro/config";
import react from "@astrojs/react";
import tailwindcss from "@tailwindcss/vite";

// Salida estatica: el sitio se sirve desde GitHub Pages, sin servidor. Todo lo
// dinamico (busqueda, filtros) lo resuelve el navegador contra PostgREST con la
// key publishable, que es publica por diseno — la seguridad la da RLS.
export default defineConfig({
  site: "https://farmaweb.py",
  output: "static",
  integrations: [react()],
  vite: { plugins: [tailwindcss()] },
});
