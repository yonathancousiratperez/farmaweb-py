"""Cliente HTTP compartido por los scrapers de farmacias.

Tres compromisos que no son negociables (ver CLAUDE.md, "Scraping responsable"):
identificarnos con una URL de contacto, limitar la tasa por sitio, y no tocar
rutas prohibidas por robots.txt. Catedral exige Crawl-delay: 1 explicitamente;
las demas no declaran uno, pero igual se les pone tope.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import httpx

CONTACTO = "https://github.com/farmaweb-py"
USER_AGENT = f"FarmawebPyBot/0.1 (+{CONTACTO}; comparador de precios de farmacias PY)"


@dataclass(frozen=True)
class Limite:
    """Tope de peticiones por segundo para un sitio."""

    req_por_seg: float
    concurrencia: int = 1


class ClienteHTTP:
    """httpx.Client con rate-limit global y reintentos con backoff.

    El limitador es un simple intervalo minimo entre salidas, compartido por
    todos los hilos: con concurrencia N y req_por_seg R, el sitio ve R req/s en
    total, no R por hilo.
    """

    def __init__(self, limite: Limite, timeout: float = 45.0) -> None:
        self._intervalo = 1.0 / limite.req_por_seg
        self._lock = threading.Lock()
        self._proximo = 0.0
        self._cliente = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "es-PY,es;q=0.9"},
            timeout=timeout,
            follow_redirects=True,
        )

    def _esperar_turno(self) -> None:
        with self._lock:
            ahora = time.monotonic()
            espera = max(0.0, self._proximo - ahora)
            self._proximo = max(ahora, self._proximo) + self._intervalo
        if espera:
            time.sleep(espera)

    def get(self, url: str, intentos: int = 3) -> httpx.Response | None:
        """Devuelve la respuesta, o None si el recurso no existe o agoto reintentos."""
        for intento in range(1, intentos + 1):
            self._esperar_turno()
            try:
                r = self._cliente.get(url)
            except httpx.HTTPError:
                if intento == intentos:
                    return None
                time.sleep(2**intento)
                continue
            if r.status_code == 404:
                return None  # producto dado de baja: no es error, no reintentar
            if r.status_code < 400:
                return r
            if intento == intentos:
                return None
            time.sleep(2**intento)
        return None

    def close(self) -> None:
        self._cliente.close()

    def __enter__(self) -> "ClienteHTTP":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
