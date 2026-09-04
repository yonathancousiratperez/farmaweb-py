"""Extractor del listado de medicamentos registrados de DINAVISA.

Fuente: https://dinavisa.gov.py/wp-content/uploads/2023/12/listado_medicamentos_diciembre_2023.pdf
Es el unico listado consolidado que DINAVISA publica en abierto. Data de
diciembre de 2023 y no hay version mas nueva accesible sin tramite.

Que esa antiguedad no invalide el uso: lo que no figura en el listado no se
libera. Un medicamento registrado despues de 2023 simplemente no aparece y
sigue oculto por el clasificador, que falla cerrado. La desactualizacion, aca,
corre para el lado seguro.

⚠️ Sobre la extraccion: `pdftotext -layout` **desalinea** este PDF — corre la
columna "Nombre Producto" un renglon hacia abajo, con lo cual cada producto
quedaria con la condicion de venta del anterior. En un comparador de precios eso
significa publicar el precio de un medicamento bajo receta: exactamente lo que
la Ley 1119/97 Art. 25 prohibe. Por eso se agrupa por coordenada `top` con
pdfplumber, que es lo que el PDF realmente dice, y ademas se verifica contra
filas de control leidas a mano antes de escribir nada.
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import unicodedata

import pdfplumber

RAIZ = pathlib.Path(__file__).resolve().parent.parent
# El PDF se versiona con el codigo (es un documento publico de DINAVISA) para
# que CI pueda regenerar el CSV sin depender de que la URL siga viva.
PDF = RAIZ / "scraper/datos/listado_medicamentos_diciembre_2023.pdf"
SALIDA = RAIZ / "scraper/datos/medicamentos.csv"

CAMPOS = [
    "nro_rs", "nombre", "razon_social", "condicion_venta_dinavisa",
    "forma_farmaceutica", "procedencia", "vencimiento", "precio",
]

# Las columnas se localizan por el x0 real del encabezado en cada pagina, en vez
# de hardcodear posiciones: si DINAVISA reacomoda el PDF, esto sigue andando o
# falla ruidosamente, pero no se desalinea en silencio.
ENCABEZADOS = [
    ("nro_rs", "Nro."),
    ("nombre", "Nombre"),
    ("razon_social", "Razon"),
    ("condicion_venta_dinavisa", "Condicion"),
    ("forma_farmaceutica", "Forma"),
    ("procedencia", "Procedencia"),
    ("vencimiento", "Vencimiento"),
    ("precio", "Precio"),
]

RE_NRO_RS = re.compile(r"^\d{5}-\d{2}-[A-Z]{2}$")


def _filas(pagina) -> list[list[dict]]:
    """Agrupa las palabras de la pagina en renglones por su coordenada `top`."""
    filas: dict[float, list[dict]] = {}
    for w in pagina.extract_words():
        # Se redondea porque todas las palabras de un renglon comparten `top`
        # salvo ruido de decimas.
        filas.setdefault(round(w["top"], 1), []).append(w)
    return [sorted(v, key=lambda w: w["x0"]) for _, v in sorted(filas.items())]


def _columnas(fila: list[dict]) -> list[tuple[str, float]] | None:
    """Devuelve [(campo, x0)] si la fila es el encabezado; None si no lo es.

    Solo la primera pagina repite el encabezado, asi que esto tiene que poder
    decir "no es encabezado" sin romper.
    """
    cols: list[tuple[str, float]] = []
    for campo, primera_palabra in ENCABEZADOS:
        for w in fila:
            if w["text"] == primera_palabra:
                cols.append((campo, w["x0"]))
                break
        else:
            return None
    return cols


def _repartir(fila: list[dict], cols: list[tuple[str, float]]) -> dict[str, str]:
    """Asigna cada palabra a la ultima columna que empieza a su izquierda."""
    salida: dict[str, list[str]] = {campo: [] for campo, _ in cols}
    for w in fila:
        campo = cols[0][0]
        for c, x0 in cols:
            # -3 de tolerancia: los numeros vienen alineados a la derecha y
            # pueden arrancar unos puntos antes del x0 del encabezado.
            if w["x0"] >= x0 - 3:
                campo = c
            else:
                break
        salida[campo].append(w["text"])
    return {c: " ".join(v).strip() for c, v in salida.items()}


def extraer(pdf_path: pathlib.Path = PDF) -> list[dict]:
    registros: list[dict] = []
    cols: list[tuple[str, float]] | None = None
    with pdfplumber.open(pdf_path) as pdf:
        for n, pagina in enumerate(pdf.pages, 1):
            for fila in _filas(pagina):
                if (nuevas := _columnas(fila)) is not None:
                    # Solo la pagina 1 trae encabezado; el resto hereda estas
                    # posiciones. Se re-lee por si alguna pagina lo repitiera.
                    cols = nuevas
                    continue
                if cols is None:
                    raise RuntimeError(f"Pagina {n}: hay datos antes del encabezado")
                r = _repartir(fila, cols)
                # El numero de registro sanitario es la unica ancla confiable:
                # si el renglon no empieza con uno, no es una fila de datos.
                if RE_NRO_RS.match(r["nro_rs"]):
                    registros.append(r)
    return registros


# --- Normalizacion y clasificacion -----------------------------------------

def normalizar(nombre: str) -> str:
    """Nombre comparable: sin tildes, sin puntuacion, espacios colapsados."""
    base = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", base.lower())).strip()


def a_condicion(texto: str) -> str:
    """Mapea la condicion de DINAVISA al vocabulario de la base.

    DINAVISA usa cuatro categorias; el esquema usa tres. La cuadruplicada es
    psicotropico/estupefaciente -> `controlado`. Cualquier texto que no se
    reconozca cae en `bajo_receta`: no se inventa una liberacion.
    """
    t = texto.upper()
    if "CUADRUPLICADA" in t:
        return "controlado"
    if "LIBRE" in t:
        return "libre"
    return "bajo_receta"


def esta_cancelado(nombre: str) -> bool:
    """El PDF marca las bajas dentro del propio nombre del producto."""
    return "CANCELAD" in nombre.upper()


# Filas leidas a mano de la pagina 1 del PDF. Si la extraccion se desalinea —el
# modo de falla real de este PDF— esto lo detecta antes de que un precio de Rx
# llegue al sitio.
CONTROL = [
    ("00052-07-EF", "ANGINOVAG", "BAJO RECETA"),
    ("00054-05-EF", "VITAFORTE PLUS", "LIBRE EN FARMACIA"),
    ("00087-06-EF", "VINIL 75", "BAJO RECETA"),
]


def verificar(registros: list[dict]) -> list[str]:
    por_rs = {r["nro_rs"]: r for r in registros}
    fallos = []
    for nro, nombre, condicion in CONTROL:
        r = por_rs.get(nro)
        if r is None:
            fallos.append(f"{nro}: no se extrajo")
        elif r["nombre"] != nombre or r["condicion_venta_dinavisa"] != condicion:
            fallos.append(
                f"{nro}: se esperaba ({nombre!r}, {condicion!r}) "
                f"y salio ({r['nombre']!r}, {r['condicion_venta_dinavisa']!r})"
            )
    return fallos


def main() -> None:
    ap = argparse.ArgumentParser(description="Extrae el listado de DINAVISA a CSV")
    ap.add_argument("--salida", type=pathlib.Path, default=SALIDA)
    args = ap.parse_args()

    registros = extraer()
    if fallos := verificar(registros):
        raise SystemExit(
            "La extraccion quedo desalineada, no se escribe nada:\n  " + "\n  ".join(fallos)
        )

    args.salida.parent.mkdir(parents=True, exist_ok=True)
    with args.salida.open("w", encoding="utf-8", newline="") as fh:
        esc = csv.DictWriter(fh, fieldnames=CAMPOS)
        esc.writeheader()
        esc.writerows(registros)

    conteo: dict[str, int] = {}
    for r in registros:
        c = a_condicion(r["condicion_venta_dinavisa"])
        conteo[c] = conteo.get(c, 0) + 1
    print(json.dumps(
        {
            "registros": len(registros),
            "por_condicion": conteo,
            "cancelados": sum(1 for r in registros if esta_cancelado(r["nombre"])),
            "nombres_unicos": len({normalizar(r["nombre"]) for r in registros}),
            "salida": str(args.salida),
        },
        ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
