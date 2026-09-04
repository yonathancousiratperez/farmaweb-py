/**
 * Arma un enlace interno respetando el `base` del sitio.
 *
 * En GitHub Pages un repo de proyecto se sirve bajo /nombre-del-repo/, asi que
 * un href="/terminos" escrito a mano apunta fuera del sitio y da 404. Astro
 * expone el prefijo en import.meta.env.BASE_URL; esto solo lo aplica sin
 * duplicar barras.
 */
export function ruta(camino: string): string {
  const base = import.meta.env.BASE_URL || "/";
  const limpio = camino.startsWith("/") ? camino.slice(1) : camino;
  const prefijo = base.endsWith("/") ? base : base + "/";
  return prefijo + limpio;
}
