-- Farmaweb.py — T7/T9: vista publica de promociones para el frontend.
--
-- v_promos_vigentes ya filtra por estado y fecha, pero devuelve banco_id y un
-- array de farmacia_id: numeros que el navegador no puede mostrar. Esta vista
-- resuelve los nombres del lado del servidor para que el front no tenga que
-- hacer un segundo pedido ni conocer la tabla `bancos`.
--
-- El auto-ocultado por fecha vive en v_promos_vigentes (CURRENT_DATE between
-- vigente_desde and vigente_hasta) y se evalua en cada consulta: una promo que
-- vence esta noche desaparece manana sola, sin redeploy del sitio estatico.

create or replace view v_promos_publicas as
select pv.id,
       b.nombre  as banco_nombre,
       b.slug    as banco_slug,
       b.logo_url as banco_logo,
       pv.titulo,
       pv.tipo,
       pv.porcentaje,
       pv.tope_gs,
       pv.tarjetas,
       pv.dias_semana,
       pv.vigente_desde,
       pv.vigente_hasta,
       pv.url_bases,
       coalesce(
         (select array_agg(f.nombre order by f.nombre)
          from farmacias f
          where f.activa and f.id = any(pv.farmacias_aplicables)),
         '{}'
       ) as farmacias
from   v_promos_vigentes pv
join   bancos b on b.id = pv.banco_id;

grant select on v_promos_publicas to anon, authenticated;
