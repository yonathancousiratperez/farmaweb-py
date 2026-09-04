"""Aplica un .sql de db/migrations/ contra Supabase.

El MCP de Supabase apunta al proyecto viejo de RASI: no sirve aca. Se va
directo al pooler en modo sesion (5432), que es el que acepta DDL.

Uso: python db/aplicar_migracion.py db/migrations/002_seed_farmacias.sql
"""
import pathlib
import sys

import psycopg

RAIZ = pathlib.Path(__file__).resolve().parent.parent
REF = "wdbezekfcmntcoagmlzm"


def password() -> str:
    for linea in (RAIZ / ".env").read_text(encoding="utf-8").splitlines():
        if linea.startswith("FARMAWEB_SUPABASE_DB_PASSWORD="):
            return linea.split("=", 1)[1].strip()
    sys.exit("Falta FARMAWEB_SUPABASE_DB_PASSWORD en .env")


def main() -> None:
    ruta = pathlib.Path(sys.argv[1])
    sql = ruta.read_text(encoding="utf-8")
    dsn = (
        f"postgresql://postgres.{REF}:{password()}"
        "@aws-0-sa-east-1.pooler.supabase.com:5432/postgres?sslmode=require"
    )
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql)
    print(f"aplicada: {ruta.name}")


if __name__ == "__main__":
    main()
