import { fechaCorta, guaranies, type Producto } from "../lib/datos";

/**
 * Tarjeta de un producto.
 *
 * 🔴 Cuando `requiere_receta` es true NO se pinta precio, ni porcentaje, ni
 * badge de oferta. Pero esto es la segunda linea de defensa, no la primera: la
 * API ya devuelve esos campos en null (gate en `v_productos_publicos`,
 * Ley 1119/97 Art. 25). Si algun dia este `if` desapareciera por accidente, no
 * habria nada que filtrar.
 */
export function TarjetaProducto({ p }: { p: Producto }) {
  return (
    <article className="bg-white rounded-xl border border-neutral-200 hover:border-marca-500 hover:shadow-sm transition flex flex-col overflow-hidden">
      <div className="relative aspect-square bg-neutral-50 grid place-items-center p-3">
        {p.imagen_url ? (
          <img
            src={p.imagen_url}
            alt={p.nombre}
            loading="lazy"
            className="max-h-full max-w-full object-contain mix-blend-multiply"
          />
        ) : (
          <span className="text-neutral-300 text-xs">sin imagen</span>
        )}
        {!p.requiere_receta && p.descuento_pct ? (
          <span className="absolute top-2 left-2 bg-[var(--color-oferta)] text-white text-xs font-bold px-2 py-0.5 rounded-full">
            -{Math.round(p.descuento_pct)}%
          </span>
        ) : null}
      </div>

      <div className="p-3 flex flex-col gap-2 flex-1">
        <p className="text-[11px] uppercase tracking-wide text-marca-600 font-medium">
          {p.farmacia_nombre}
        </p>
        <h3 className="text-sm leading-snug font-medium recorte-2" title={p.nombre}>
          {p.nombre}
        </h3>

        <div className="mt-auto">
          {p.requiere_receta ? (
            <div className="text-xs text-neutral-600 bg-neutral-100 rounded-lg px-2 py-1.5 leading-snug">
              <strong className="block text-neutral-800">Venta bajo receta</strong>
              Consulta el precio en la farmacia.
            </div>
          ) : (
            <>
              {p.precio_lista ? (
                <p className="text-xs text-neutral-400 line-through">
                  {guaranies(p.precio_lista)}
                </p>
              ) : null}
              <p className="text-lg font-bold tracking-tight">{guaranies(p.precio_oferta)}</p>
              {p.precio_capturado_en ? (
                <p className="text-[10px] text-neutral-400">
                  capturado {fechaCorta(p.precio_capturado_en)}
                </p>
              ) : null}
            </>
          )}
        </div>

        {/* Deep-link a la ficha original: el sitio manda trafico a la farmacia,
            no lo retiene. */}
        <a
          href={p.url_producto}
          target="_blank"
          rel="noopener nofollow"
          className="text-center text-sm font-medium border border-marca-600 text-marca-700 rounded-lg py-1.5 hover:bg-marca-50 transition"
        >
          Ver en {p.farmacia_nombre}
        </a>
      </div>
    </article>
  );
}
