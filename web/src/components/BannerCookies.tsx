import { useEffect, useState } from "react";

const CLAVE = "farmaweb:consentimiento";

export type Consentimiento = "aceptado" | "rechazado" | null;

export function leerConsentimiento(): Consentimiento {
  try {
    const v = localStorage.getItem(CLAVE);
    return v === "aceptado" || v === "rechazado" ? v : null;
  } catch {
    // Modo privado o cookies bloqueadas: sin consentimiento registrado, que es
    // el estado seguro (no se carga analitica).
    return null;
  }
}

/**
 * Banner de consentimiento previo (Ley 7593/2025, Art. 6).
 *
 * Tres cosas que la ley obliga y que son faciles de hacer mal:
 *  1. El consentimiento es PREVIO: la analitica no se carga hasta que haya un
 *     "aceptado" explicito. Por eso el banner no dispara nada al montarse.
 *  2. Rechazar tiene que ser tan facil como aceptar: los dos botones tienen el
 *     mismo peso visual, no hay un "aceptar" verde grande y un "rechazar"
 *     escondido en gris chiquito.
 *  3. Revocar tiene que ser igual de simple: /cookies reusa este mismo estado.
 */
export default function BannerCookies() {
  const [decision, setDecision] = useState<Consentimiento>(null);
  const [montado, setMontado] = useState(false);

  useEffect(() => {
    setDecision(leerConsentimiento());
    setMontado(true);
  }, []);

  function decidir(valor: Exclude<Consentimiento, null>) {
    try {
      localStorage.setItem(CLAVE, valor);
    } catch {
      /* si no se puede guardar, se vuelve a preguntar en la proxima visita */
    }
    setDecision(valor);
    // Aca iria el arranque de la analitica cuando valor === "aceptado".
    // Hoy no hay ninguna cargada, y esa es justamente la postura por defecto.
  }

  if (!montado || decision !== null) return null;

  return (
    <div
      role="dialog"
      aria-live="polite"
      aria-label="Consentimiento de cookies"
      className="fixed inset-x-0 bottom-0 z-50 p-3 sm:p-4"
    >
      <div className="max-w-3xl mx-auto bg-white border border-neutral-300 rounded-2xl shadow-lg p-4 sm:p-5 flex flex-col sm:flex-row sm:items-center gap-4">
        <p className="text-sm text-neutral-700 leading-relaxed flex-1">
          Usamos cookies propias necesarias para que el sitio funcione. Para medir el
          uso de forma agregada necesitamos tu permiso. Podes cambiar de idea cuando
          quieras desde{" "}
          <a href="/cookies" className="text-marca-700 underline underline-offset-2">
            Politica de cookies
          </a>
          .
        </p>
        <div className="flex gap-2 shrink-0">
          <button
            onClick={() => decidir("rechazado")}
            className="flex-1 sm:flex-none px-4 py-2 rounded-xl border border-neutral-300 text-sm font-medium hover:bg-neutral-50 transition"
          >
            Rechazar
          </button>
          <button
            onClick={() => decidir("aceptado")}
            className="flex-1 sm:flex-none px-4 py-2 rounded-xl border border-marca-600 bg-marca-600 text-white text-sm font-medium hover:bg-marca-700 transition"
          >
            Aceptar
          </button>
        </div>
      </div>
    </div>
  );
}
