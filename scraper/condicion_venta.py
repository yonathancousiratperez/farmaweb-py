"""T5 — Clasificador de condicion de venta contra el registro de DINAVISA.

El problema que resuelve: los cinco scrapers fallan cerrado. Ninguna de las
farmacias declara la condicion de venta en la ficha (salvo Farmacenter), asi que
todo lo que cuelga de la categoria "Medicamentos" sale como `bajo_receta` y por
lo tanto **sin precio**. Se paga de mas: jarabes, analgesicos y antigripales de
venta libre quedan ocultos junto con los que si lo requieren.

Este modulo cruza el catalogo contra el listado oficial de registros sanitarios
(ver `scraper/dinavisa.py`) y corrige en las dos direcciones:

  · **Liberar** (`bajo_receta` -> `libre`): solo si DINAVISA dice, sin ninguna
    ambiguedad, que ese producto es de venta libre en farmacia.
  · **Restringir** (`no_medicamento` -> `bajo_receta`/`controlado`): si un
    medicamento con receta esta publicado fuera de la categoria "Medicamentos"
    —pasa, las farmacias mezclan— el scraper lo dio por producto comun y le
    mostro el precio. Esta direccion siempre se aplica.

Reglas de prudencia, en orden de importancia:

  1. **Un nombre con condiciones en conflicto no libera nada.** Hay 4.955
     registros y 4.683 nombres distintos: varias marcas repiten nombre en
     presentaciones con distinta condicion. Cuando el nombre normalizado apunta
     a mas de una condicion, gana la mas estricta.
  2. **Los registros cancelados no liberan.** Un registro dado de baja no
     autoriza nada.
  3. **Nombres cortos no liberan.** Un nombre de 4 letras engancha con
     cualquier cosa; el umbral evita liberar por coincidencia.
  4. El match es por nombre normalizado exacto o por prefijo con corte de
     palabra ("CECAN 1 g." libera "CECAN 1 G X 10 COMPRIMIDOS", pero "SOMIT"
     nunca libera "SOMITEX").

Toda la asimetria del modulo apunta al mismo lado: **equivocarse ocultando un
producto cuesta una ficha; equivocarse mostrando el precio de un medicamento
bajo receta viola la Ley 1119/97 Art. 25 inc. 10.**
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib

import psycopg

from .dinavisa import SALIDA as CSV_DINAVISA, a_condicion, esta_cancelado, normalizar
from .db import conectar

# Un nombre mas corto que esto no se usa para liberar: el riesgo de enganchar
# con un producto que no es cae mucho mas rapido que el beneficio.
MIN_LARGO_NOMBRE = 6

# Cuanto mas estricto, mas alto. Se usa para resolver nombres repetidos.
ORDEN = {"libre": 0, "bajo_receta": 1, "controlado": 2}


def indice(csv_path: pathlib.Path = CSV_DINAVISA) -> dict[str, tuple[str, str]]:
    """{nombre normalizado: (condicion, nro_rs)} con la condicion mas estricta."""
    if not csv_path.exists():
        raise SystemExit(
            f"Falta {csv_path}. Generalo con: python -m scraper.dinavisa"
        )
    idx: dict[str, tuple[str, str]] = {}
    with csv_path.open(encoding="utf-8", newline="") as fh:
        for fila in csv.DictReader(fh):
            if esta_cancelado(fila["nombre"]):
                continue
            nombre = normalizar(fila["nombre"])
            if len(nombre) < MIN_LARGO_NOMBRE:
                continue
            cond = a_condicion(fila["condicion_venta_dinavisa"])
            previo = idx.get(nombre)
            # Ante nombres repetidos con condiciones distintas, gana la mas
            # estricta: es la unica resolucion que no puede publicar un precio
            # que no corresponda.
            if previo is None or ORDEN[cond] > ORDEN[previo[0]]:
                idx[nombre] = (cond, fila["nro_rs"])
    return idx


# Palabras que en una ficha de farmacia solo aparecen describiendo dosis o
# envase. Que una de estas siga al nombre es lo que distingue "ASPIRINA 1 TIRA
# X 10" (el medicamento) de "SELENE MEDIA BASICA" (un par de medias, que apenas
# comparte la primera palabra con el inyectable SELENE).
TOKENS_PRESENTACION = {
    "mg", "mcg", "ug", "g", "gr", "kg", "ml", "cc", "l", "ui", "mgs",
    "x", "caja", "cja", "blister", "tira", "frasco", "fco", "envase", "pack",
    "comp", "comprimidos", "comprimido", "caps", "capsulas", "capsula",
    "tabletas", "tableta", "grageas", "sobres", "sobre", "amp", "ampolla",
    "ampollas", "jbe", "jarabe", "susp", "suspension", "sol", "solucion",
    "gotas", "crema", "unguento", "pomada", "spray", "aerosol", "supositorios",
    "inyectable", "polvo", "granulado", "forte", "pediatrico", "pediatrica",
    "unidades", "und", "u",
}


def _prefijo_plausible(prefijo: str, siguiente: str) -> bool:
    """Decide si un prefijo del nombre del producto puede ser un medicamento.

    Un registro de varias palabras ("ASPIRINA FORTE", "CECAN 1 g.") ya es
    especifico por si mismo. Uno de una sola palabra, en cambio, engancha con
    cualquier producto que empiece igual, asi que se exige que lo que sigue sea
    dosis o presentacion y no otra palabra descriptiva.
    """
    if " " in prefijo:
        return True
    return siguiente.isdigit() or siguiente in TOKENS_PRESENTACION


def buscar(nombre_producto: str, idx: dict[str, tuple[str, str]]) -> tuple[str, str] | None:
    """Match exacto, o el prefijo mas largo del registro con corte de palabra."""
    n = normalizar(nombre_producto)
    if not n:
        return None
    if (hit := idx.get(n)) is not None:
        return hit
    # Se prueban prefijos del nombre del producto, del mas largo al mas corto:
    # "cecan 1 g x 10 comprimidos" -> "cecan 1 g x 10" -> ... -> "cecan 1 g".
    # El primero que exista en el registro es el match mas especifico posible.
    palabras = n.split()
    for corte in range(len(palabras) - 1, 0, -1):
        prefijo = " ".join(palabras[:corte])
        if len(prefijo) < MIN_LARGO_NOMBRE:
            continue
        if (hit := idx.get(prefijo)) is not None and _prefijo_plausible(prefijo, palabras[corte]):
            return hit
    return None


SQL_PRODUCTOS = """
select id, nombre, condicion_venta
from   productos
where  activo
"""

SQL_APLICAR = """
update productos
set    condicion_venta_dinavisa = %(cond)s,
       dinavisa_nro_rs          = %(rs)s,
       condicion_venta          = %(cond)s
where  id = %(id)s
"""


# El sufijo del numero de registro dice de que clase de producto se trata:
# EF = especialidad farmaceutica, FH = fitoterapico/homeopatico, SD = suplemento
# dietario. Los dos primeros son medicamentos; SD no lo es.
CLASES_MEDICAMENTO = {"EF", "FH"}


def es_medicamento(nro_rs: str) -> bool:
    return nro_rs.rsplit("-", 1)[-1].upper() in CLASES_MEDICAMENTO


def decidir(actual: str, dinavisa: str, nro_rs: str) -> str | None:
    """Devuelve la condicion a escribir, o None si no hay que tocar nada.

    Solo dos movimientos estan permitidos, y ninguno es discrecional:
      · liberar lo que el scraper oculto de mas, cuando DINAVISA lo declara libre;
      · restringir lo que el scraper dejo pasar como producto comun.
    Todo lo demas se deja como esta.
    """
    if actual == dinavisa:
        return None
    if actual == "bajo_receta" and dinavisa == "libre":
        return "libre"
    if actual == "no_medicamento" and dinavisa in ("bajo_receta", "controlado"):
        # Solo se restringe por un registro que sea de medicamento. Las leches
        # de formula y los suplementos (clase SD) figuran como "bajo receta" en
        # el registro, pero la Ley 1119/97 habla de medicamentos: ocultarle el
        # precio de la leche de su bebe a una madre no lo pide ninguna norma.
        return dinavisa if es_medicamento(nro_rs) else None
    if actual == "bajo_receta" and dinavisa == "controlado":
        # Mas estricto que lo que habia: se aplica, aunque hoy la vista publica
        # trate a los dos igual. Manana puede no ser asi.
        return "controlado"
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Clasifica condicion_venta con DINAVISA")
    ap.add_argument("--sin-guardar", action="store_true",
                    help="muestra que cambiaria, sin escribir en la base")
    ap.add_argument("--muestra", type=int, default=25,
                    help="cuantos cambios listar en el informe")
    args = ap.parse_args()

    idx = indice()
    cambios: list[tuple[int, str, str, str, str]] = []
    sin_match = 0

    conn: psycopg.Connection
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(SQL_PRODUCTOS)
            filas = cur.fetchall()

        for pid, nombre, actual in filas:
            hit = buscar(nombre, idx)
            if hit is None:
                sin_match += 1
                continue
            cond, rs = hit
            if (nueva := decidir(actual, cond, rs)) is not None:
                cambios.append((pid, nombre, actual, nueva, rs))

        if not args.sin_guardar:
            with conn.cursor() as cur:
                for pid, _, _, nueva, rs in cambios:
                    cur.execute(SQL_APLICAR, {"id": pid, "cond": nueva, "rs": rs})

    liberados = [c for c in cambios if c[3] == "libre"]
    restringidos = [c for c in cambios if c[3] != "libre"]

    print(json.dumps({
        "productos_activos": len(filas),
        "sin_match_en_dinavisa": sin_match,
        "liberados": len(liberados),
        "restringidos": len(restringidos),
        "escrito": not args.sin_guardar,
    }, ensure_ascii=False, indent=2))

    for titulo, grupo in (("LIBERADOS", liberados), ("RESTRINGIDOS", restringidos)):
        if not grupo:
            continue
        print(f"\n-- {titulo} ({len(grupo)}) --")
        for _, nombre, actual, nueva, rs in grupo[:args.muestra]:
            print(f"  {actual:15} -> {nueva:14} [{rs}] {nombre[:60]}")


if __name__ == "__main__":
    main()
