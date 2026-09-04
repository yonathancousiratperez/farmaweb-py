import { useEffect, useRef, useState } from "react";
import { buscarProductos, listarFarmacias, type Farmacia, type Producto } from "../lib/datos";
import { TarjetaProducto } from "./TarjetaProducto";

const POR_PAGINA = 24;

export default function Buscador() {
  const [q, setQ] = useState("");
  const [farmacia, setFarmacia] = useState<string | null>(null);
  const [soloOfertas, setSoloOfertas] = useState(false);

  const [productos, setProductos] = useState<Producto[]>([]);
  const [farmacias, setFarmacias] = useState<Farmacia[]>([]);
  const [pagina, setPagina] = useState(0);
  const [cargando, setCargando] = useState(true);
  const [hayMas, setHayMas] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Cada tecla dispararia una consulta; se espera a que el usuario frene.
  const [qDebounced, setQDebounced] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setQDebounced(q), 300);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    listarFarmacias().then(setFarmacias);
  }, []);

  // Cualquier cambio de criterio vuelve a la primera pagina: paginar sobre un
  // filtro viejo mezcla resultados de dos busquedas distintas.
  useEffect(() => {
    setPagina(0);
  }, [qDebounced, farmacia, soloOfertas]);

  // Descarta respuestas de busquedas que quedaron atras: sin esto, una consulta
  // lenta puede pisar el resultado de otra mas nueva.
  const pedidoActual = useRef(0);

  useEffect(() => {
    const id = ++pedidoActual.current;
    setCargando(true);
    setError(null);
    buscarProductos({
      q: qDebounced,
      farmacia,
      soloOfertas,
      limite: POR_PAGINA,
      offset: pagina * POR_PAGINA,
    })
      .then((filas) => {
        if (id !== pedidoActual.current) return;
        setProductos((previos) => (pagina === 0 ? filas : [...previos, ...filas]));
        setHayMas(filas.length === POR_PAGINA);
      })
      .catch((e) => {
        if (id !== pedidoActual.current) return;
        setError(e instanceof Error ? e.message : "No se pudo cargar el catalogo");
      })
      .finally(() => {
        if (id === pedidoActual.current) setCargando(false);
      });
  }, [qDebounced, farmacia, soloOfertas, pagina]);

  return (
    <div>
      <div className="sticky top-16 z-10 bg-[#fbfbfa]/95 backdrop-blur border-b border-neutral-200 -mx-4 px-4 py-3">
        <div className="max-w-6xl mx-auto flex flex-col gap-3">
          <label className="relative block">
            <span className="sr-only">Buscar productos</span>
            <input
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Buscar: ibuprofeno, shampoo, panales..."
              className="w-full rounded-xl border border-neutral-300 bg-white px-4 py-3 pr-11 text-base outline-none focus:border-marca-500 focus:ring-2 focus:ring-marca-500/20"
            />
            <span className="absolute right-4 top-1/2 -translate-y-1/2 text-neutral-400" aria-hidden>
              ⌕
            </span>
          </label>

          <div className="flex gap-2 overflow-x-auto pb-1 -mx-1 px-1">
            <Chip activo={farmacia === null} onClick={() => setFarmacia(null)}>
              Todas
            </Chip>
            {farmacias.map((f) => (
              <Chip
                key={f.slug}
                activo={farmacia === f.slug}
                onClick={() => setFarmacia(farmacia === f.slug ? null : f.slug)}
              >
                {f.nombre}
              </Chip>
            ))}
            <Chip activo={soloOfertas} onClick={() => setSoloOfertas(!soloOfertas)}>
              Solo ofertas
            </Chip>
          </div>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-0 py-6">
        {error ? (
          <p className="text-center text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg py-3">
            {error}
          </p>
        ) : null}

        {!cargando && productos.length === 0 && !error ? (
          <p className="text-center text-neutral-500 py-16">
            No encontramos nada para <strong>{qDebounced}</strong>. Proba con menos
            palabras o con el nombre de la marca.
          </p>
        ) : null}

        <div className="grid gap-3 grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {productos.map((p) => (
            <TarjetaProducto key={p.id} p={p} />
          ))}
          {cargando
            ? Array.from({ length: pagina === 0 ? 10 : 5 }).map((_, i) => (
                <div
                  key={`esqueleto-${i}`}
                  className="bg-white rounded-xl border border-neutral-200 h-72 animate-pulse"
                />
              ))
            : null}
        </div>

        {hayMas && !cargando ? (
          <div className="text-center mt-8">
            <button
              onClick={() => setPagina((n) => n + 1)}
              className="px-6 py-2.5 rounded-xl bg-marca-600 text-white font-medium hover:bg-marca-700 transition"
            >
              Ver mas productos
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function Chip({
  activo,
  onClick,
  children,
}: {
  activo: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={activo}
      className={
        "shrink-0 px-3 py-1.5 rounded-full text-sm border transition whitespace-nowrap " +
        (activo
          ? "bg-marca-600 border-marca-600 text-white"
          : "bg-white border-neutral-300 text-neutral-700 hover:border-marca-500")
      }
    >
      {children}
    </button>
  );
}
