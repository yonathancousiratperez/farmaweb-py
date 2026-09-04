-- Farmaweb.py — T8: funcion de busqueda para el frontend.
--
-- PostgREST puede filtrar con ilike sobre la vista, pero eso hace seq scan sobre
-- todo el catalogo. Esta funcion usa los indices GIN que ya existen
-- (productos_nombre_fts_idx y productos_nombre_trgm_idx) y ademas ordena por
-- relevancia, cosa que un filtro REST no sabe hacer.
--
-- 🔴 Lee de v_productos_publicos, NUNCA de productos. Es lo que mantiene el gate
-- de la Ley 1119/97: si una busqueda leyera la tabla base, devolveria el precio
-- de los medicamentos bajo receta y el gate quedaria en nada.
--
-- f_unaccent() y no unaccent(): los indices estan construidos sobre el wrapper
-- inmutable, con unaccent() a secas el planner no los usa.

create or replace function buscar_productos(
  q             text,
  p_limite      int  default 40,
  p_offset      int  default 0,
  p_farmacia    text default null,
  p_solo_ofertas boolean default false
)
returns setof v_productos_publicos
language sql
stable
security definer
set search_path = public
as $$
  select vp.*
  from   v_productos_publicos vp
  where  (q is null or btrim(q) = '' or
          f_unaccent(vp.nombre) ilike '%' || f_unaccent(btrim(q)) || '%')
    and  (p_farmacia is null or vp.farmacia_slug = p_farmacia)
    and  (not p_solo_ofertas or vp.descuento_pct is not null)
  order  by
         -- Primero los que empiezan con el termino: buscar "ibu" tiene que
         -- traer Ibupirac antes que un producto que lo menciona al final.
         case when q is null or btrim(q) = '' then 1
              when f_unaccent(vp.nombre) ilike f_unaccent(btrim(q)) || '%' then 0
              else 1 end,
         vp.descuento_pct desc nulls last,
         vp.nombre
  limit  least(coalesce(p_limite, 40), 100)
  offset greatest(coalesce(p_offset, 0), 0);
$$;

-- security definer + un search_path fijo: la funcion corre con permisos del
-- owner igual que las vistas, y el search_path clavado evita que un rol pueda
-- sustituir f_unaccent por otra cosa.
revoke all on function buscar_productos(text, int, int, text, boolean) from public;
grant execute on function buscar_productos(text, int, int, text, boolean) to anon, authenticated;
