// Acceso a los datos publicos de Farmaweb.py.
//
// Se habla PostgREST directo con fetch en vez de @supabase/supabase-js: lo unico
// que se usa son tres lecturas anonimas, y la libreria entera pesa mas que todo
// el JS de la isla del buscador. En movil paraguayo eso importa.
//
// 🔴 Todas las lecturas van contra vistas publicas o contra buscar_productos().
// Ninguna toca las tablas base: el gate de medicamentos bajo receta (Ley 1119/97
// Art. 25) vive en `v_productos_publicos`, y saltearlo devolveria precios de Rx.

const URL_BASE = import.meta.env.PUBLIC_SUPABASE_URL;
const CLAVE = import.meta.env.PUBLIC_SUPABASE_ANON_KEY;

export type Producto = {
  id: number;
  farmacia_nombre: string;
  farmacia_slug: string;
  ean: string | null;
  nombre: string;
  marca: string | null;
  presentacion: string | null;
  url_producto: string;
  imagen_url: string | null;
  condicion_venta: string;
  /** true = medicamento bajo receta o controlado: se muestra SIN precio. */
  requiere_receta: boolean;
  precio_lista: number | null;
  precio_oferta: number | null;
  descuento_pct: number | null;
  precio_capturado_en: string | null;
};

export type Farmacia = { id: number; nombre: string; slug: string; url_base: string };

function cabeceras(): HeadersInit {
  return {
    apikey: CLAVE,
    Authorization: `Bearer ${CLAVE}`,
    "Content-Type": "application/json",
  };
}

export type OpcionesBusqueda = {
  q?: string;
  limite?: number;
  offset?: number;
  farmacia?: string | null;
  soloOfertas?: boolean;
};

export async function buscarProductos(o: OpcionesBusqueda = {}): Promise<Producto[]> {
  const r = await fetch(`${URL_BASE}/rest/v1/rpc/buscar_productos`, {
    method: "POST",
    headers: cabeceras(),
    body: JSON.stringify({
      q: o.q ?? "",
      p_limite: o.limite ?? 24,
      p_offset: o.offset ?? 0,
      p_farmacia: o.farmacia ?? null,
      p_solo_ofertas: o.soloOfertas ?? false,
    }),
  });
  if (!r.ok) throw new Error(`Busqueda fallida (${r.status})`);
  return r.json();
}

export async function listarFarmacias(): Promise<Farmacia[]> {
  const r = await fetch(
    `${URL_BASE}/rest/v1/v_farmacias_publicas?select=id,nombre,slug,url_base&order=nombre`,
    { headers: cabeceras() },
  );
  if (!r.ok) return [];
  return r.json();
}

/** Guaranies sin decimales: en Paraguay no se usan centimos. */
export function guaranies(valor: number | null | undefined): string {
  if (valor === null || valor === undefined) return "—";
  return "₲ " + Math.round(valor).toLocaleString("es-PY");
}

export function fechaCorta(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString("es-PY", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export type Promo = {
  id: number;
  banco_nombre: string;
  banco_slug: string;
  banco_logo: string | null;
  titulo: string;
  tipo: "descuento" | "reintegro" | "cuotas";
  porcentaje: number | null;
  tope_gs: number | null;
  tarjetas: string[];
  dias_semana: number[];
  vigente_desde: string;
  vigente_hasta: string;
  url_bases: string;
  farmacias: string[];
};

/**
 * Promociones bancarias vigentes HOY.
 *
 * Se pide desde el navegador y no en tiempo de build a proposito: el sitio es
 * estatico y se despliega cada tanto, pero una promo que vence esta noche tiene
 * que desaparecer manana sin esperar un redeploy. El filtro por fecha lo evalua
 * Postgres en cada consulta (`v_promos_vigentes`), no el build.
 */
export async function promosVigentes(): Promise<Promo[]> {
  const r = await fetch(
    `${URL_BASE}/rest/v1/v_promos_publicas?select=*&order=porcentaje.desc`,
    { headers: cabeceras() },
  );
  if (!r.ok) throw new Error(`No se pudieron cargar las promociones (${r.status})`);
  return r.json();
}

const DIAS = ["", "lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"];

/** [1,2] -> "lunes y martes". Array vacio = todos los dias. */
export function diasEnTexto(dias: number[]): string {
  if (!dias || dias.length === 0) return "todos los dias";
  const nombres = dias.map((d) => DIAS[d]).filter(Boolean);
  if (nombres.length === 1) return `los ${nombres[0]}`;
  return "los " + nombres.slice(0, -1).join(", ") + " y " + nombres[nombres.length - 1];
}

export function fechaLarga(iso: string): string {
  const [a, m, d] = iso.split("-").map(Number);
  return new Date(a, m - 1, d).toLocaleDateString("es-PY", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}
