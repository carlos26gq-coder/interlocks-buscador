# Tests Manuales Frontend (app.js)

## 1. test_sessionStorage_fallback (P0)
**Objetivo:** Verificar que el uso de sessionStorage no detiene la ejecución.
**Cómo ejecutarlo:** Abrir la aplicación en un iframe con sandbox restrictivo (sin allow-same-origin) o Safari en modo estricto. La app debe arrancar correctamente y `mostrarBienvenida` no debe lanzar `SecurityError`.

## 2. test_syncPendientes_409_conflict (P1)
**Objetivo:** Evitar que un error HTTP 409 rompa la sincronización.
**Cómo ejecutarlo:** 
1. Apagar la red (modo avión).
2. Crear un apunte (se encola).
3. Modificar manualmente el `id` en la BD remota para crear conflicto.
4. Reconectar la red. La sincronización debe asignar un UUID nuevo y terminar de procesar.

## 3. test_cargarNotas_null_strings (P4)
**Objetivo:** Evitar que n.text.substring falle.
**Cómo ejecutarlo:** 
1. En la BD, forzar el texto de un apunte a `NULL` (`UPDATE notes SET text = NULL WHERE ...`).
2. Recargar la página. La lista de notas debe cargar sin lanzar `TypeError`.
