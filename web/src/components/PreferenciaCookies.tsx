import { useEffect, useState } from "react";
import { leerConsentimiento, type Consentimiento } from "./BannerCookies";

const CLAVE = "farmaweb:consentimiento";

/**
 * Panel de revocacion en /cookies.
 *
 * La Ley 7593/2025 exige que retirar el consentimiento sea tan simple como
 * darlo. Por eso esto es un boton en la propia pagina de cookies y no un
 * formulario de contacto ni un correo a soporte.
 */
export default function PreferenciaCookies() {
  const [decision, setDecision] = useState<Consentimiento>(null);
  const [montado, setMontado] = useState(false);

  useEffect(() => {
    setDecision(leerConsentimiento());
    setMontado(true);
  }, []);

  function guardar(valor: Consentimiento) {
    try {
      if (valor === null) localStorage.removeItem(CLAVE);
      else localStorage.setItem(CLAVE, valor);
    } catch {
      /* nada que hacer si el navegador bloquea el almacenamiento */
    }
    setDecision(valor);
  }

  if (!montado) return null;

  const etiqueta =
    decision === "aceptado"
      ? "Aceptaste la analitica agregada."
      : decision === "rechazado"
        ? "Rechazaste la analitica agregada."
        : "Todavia no elegiste. Por defecto no se carga ninguna analitica.";

  return (
    <div className="not-prose bg-white border border-neutral-300 rounded-xl p-4 sm:p-5 my-6">
      <p className="text-sm font-medium">Tu eleccion actual</p>
      <p className="text-sm text-neutral-600 mt-1">{etiqueta}</p>
      <div className="flex flex-wrap gap-2 mt-4">
        <button
          onClick={() => guardar("rechazado")}
          className="px-4 py-2 rounded-xl border border-neutral-300 text-sm font-medium hover:bg-neutral-50 transition"
        >
          Rechazar analitica
        </button>
        <button
          onClick={() => guardar("aceptado")}
          className="px-4 py-2 rounded-xl border border-marca-600 bg-marca-600 text-white text-sm font-medium hover:bg-marca-700 transition"
        >
          Aceptar analitica
        </button>
        <button
          onClick={() => guardar(null)}
          className="px-4 py-2 rounded-xl border border-neutral-300 text-sm text-neutral-600 hover:bg-neutral-50 transition"
        >
          Borrar mi eleccion
        </button>
      </div>
    </div>
  );
}
