// Datos de contacto del sitio, centralizados a proposito: reemplazarlos por los
// reales tiene que ser cambiar UN archivo, no buscar por todo el proyecto (T14).

export const DATOS_DE_PRUEBA = true; // ← poner en false al tener los datos reales

// Se eligieron valores estructuralmente NO asignables en vez de unos verosimiles.
// Un "+595 981 xxx xxx" plausible es, con alta probabilidad, el celular de una
// persona real que recibiria llamadas de usuarios del sitio.
//   · example.com esta reservado por RFC 2606: no llega a nadie.
//   · El prefijo 900 no es un rango movil asignable en Paraguay.
//   · La direccion no lleva calle ni numero: una inventada puede caer en un
//     domicilio real.
export const CONTACTO = {
  email: "contacto@example.com",
  telefono: "+595 21 000 000",
  whatsapp: "+595 900 000 000",
  direccion: "Asuncion, Paraguay",
  redes: { facebook: "#", instagram: "#", x: "#" },
};

export const SITIO = {
  nombre: "Farmaweb.py",
  descripcion:
    "Compara precios de farmacias del Paraguay y calcula el precio final con el reintegro de tu banco.",
};
