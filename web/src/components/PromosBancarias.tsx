import { useEffect, useState } from "react";
import {
  diasEnTexto,
  ERROR_CATALOGO,
  fechaLarga,
  guaranies,
  promosVigentes,
  type Promo,
} from "../lib/datos";

/**
 * Listado de promociones bancarias vigentes.
 *
 * Se resuelve en el navegador, no en el build: el sitio es estatico y se
 * despliega cada tanto, pero una promo que vence esta noche tiene que
 * desaparecer manana sola. El filtro por fecha lo hace Postgres en cada
 * consulta.
 */
export default function PromosBancarias() {
  const [promos, setPromos] = useState<Promo[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    promosVigentes()
      .then(setPromos)
      .catch((e) => setError(e instanceof Error ? e.message : ERROR_CATALOGO));
  }, []);

  if (error) {
    return (
      <p className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-xl p-4">
        {error}
      </p>
    );
  }

  if (promos === null) {
    return (
      <div className="space-y-3">
        {[0, 1].map((i) => (
          <div key={i} className="h-36 rounded-2xl border border-neutral-200 bg-white animate-pulse" />
        ))}
      </div>
    );
  }

  if (promos.length === 0) {
    return (
      <div className="bg-white border border-neutral-300 rounded-2xl p-5 sm:p-6">
        <p className="font-semibold">Ahora mismo no hay promociones vigentes</p>
        <p className="text-sm text-neutral-600 mt-2 leading-relaxed">
          Ninguna promocion se publica sin revision humana previa. Un tope mal leido
          cambia por completo la decision de compra, asi que preferimos no mostrar
          nada antes que mostrar algo sin verificar.
        </p>
        <p className="text-sm text-neutral-600 mt-3 leading-relaxed">
          Las que vencen <strong>desaparecen solas</strong> de esta pagina: la vigencia
          se evalua contra la fecha del dia en cada visita, no a mano.
        </p>
      </div>
    );
  }

  return (
    <ul className="space-y-3">
      {promos.map((p) => (
        <li
          key={p.id}
          className="bg-white border border-neutral-300 rounded-2xl p-5 flex flex-col sm:flex-row gap-4"
        >
          <div className="sm:w-28 shrink-0">
            <p className="font-semibold text-marca-700">{p.banco_nombre}</p>
            {p.porcentaje ? (
              <p className="text-3xl font-bold tracking-tight mt-1">{p.porcentaje}%</p>
            ) : null}
            <p className="text-xs uppercase tracking-wide text-neutral-500">{p.tipo}</p>
          </div>

          <div className="flex-1 min-w-0">
            <h2 className="font-semibold leading-snug">{p.titulo}</h2>
            <dl className="mt-2 text-sm text-neutral-700 space-y-1">
              <div>
                <dt className="inline font-medium">Cuando: </dt>
                <dd className="inline">{diasEnTexto(p.dias_semana)}</dd>
              </div>
              {p.tope_gs ? (
                <div>
                  <dt className="inline font-medium">Tope del beneficio: </dt>
                  <dd className="inline">{guaranies(p.tope_gs)}</dd>
                </div>
              ) : null}
              {p.tarjetas.length > 0 ? (
                <div>
                  <dt className="inline font-medium">Tarjetas: </dt>
                  <dd className="inline">{p.tarjetas.join(", ")}</dd>
                </div>
              ) : null}
              {p.farmacias.length > 0 ? (
                <div>
                  <dt className="inline font-medium">Farmacias: </dt>
                  <dd className="inline">{p.farmacias.join(", ")}</dd>
                </div>
              ) : null}
              <div>
                <dt className="inline font-medium">Vigencia: </dt>
                <dd className="inline">
                  hasta el {fechaLarga(p.vigente_hasta)}
                </dd>
              </div>
            </dl>

            {/* El enlace a las bases va SIEMPRE, en cada promo: lo que publicamos
                es un resumen y son ellas las que prevalecen. */}
            <a
              href={p.url_bases}
              target="_blank"
              rel="noopener nofollow"
              className="inline-block mt-3 text-sm font-medium text-marca-700 underline underline-offset-2"
            >
              Ver bases y condiciones de {p.banco_nombre}
            </a>
          </div>
        </li>
      ))}
    </ul>
  );
}
