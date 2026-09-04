-- Farmaweb.py — T8: vista publica de farmacias para los filtros del buscador.
--
-- La tabla `farmacias` no se expone: tiene el flag `activa`, que es la palanca
-- de baja voluntaria y no es asunto del navegador. La vista publica solo las
-- activas, y solo los campos que el front necesita para pintar un filtro y un
-- deep-link.

create or replace view v_farmacias_publicas as
select f.id, f.nombre, f.slug, f.url_base, f.logo_url
from   farmacias f
where  f.activa;

grant select on v_farmacias_publicas to anon, authenticated;
