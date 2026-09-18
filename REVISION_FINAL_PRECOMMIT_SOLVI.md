# SOLVI — Revisión final pre-commit de C-1, C-2 y C-3

Fecha de revisión: 2026-09-17  
Repositorio: `C:\Users\CGutierrez\Desktop\proyecto_interlocks`  
Alcance: cambios locales aún no confirmados en `scripts/api.py`, `scripts/search_engine.py`, `scripts/static/app.js` y `scripts/static/search-worker.js`.

## Veredicto

**NO LISTO PARA COMMIT todavía.**

La implementación funcional revisada es coherente y la suite completa pasa, pero quedan tres condiciones que deben cerrarse antes de considerar el cambio entregable y reproducible:

1. `tests/` está ignorado por Git; por ello, la modificación del test de C-1 no entraría en el commit.
2. El test nuevo de C-1 valida cadenas de código, no el comportamiento HTTP real de creación idempotente y conflicto.
3. C-2 protege la sincronización hasta que IndexedDB esté listo, pero `app.js` todavía accede a `localStorage` sin `try/catch` durante la carga inicial. En navegadores que bloquean storage, la aplicación puede fallar antes de llegar a la protección nueva.

No se detectó corrupción de datos ni una regresión demostrada en C-1/C-3. El estado puede pasar a **LISTO PARA COMMIT** con cambios pequeños y localizados descritos al final.

## Resumen del diff

- 4 archivos modificados.
- 108 inserciones y 136 eliminaciones.
- Sin archivos funcionales inesperados en el diff.
- `git diff --check`: correcto; solo aparecen avisos informativos LF→CRLF de Windows.
- No se creó commit.

Archivos modificados:

- `scripts/api.py`: C-1, creación de notas sin sobrescritura anónima.
- `scripts/static/app.js`: C-2, secuencia de inicialización/sincronización y búsqueda con Enter.
- `scripts/search_engine.py`: C-3, determinismo y paridad del motor Python.
- `scripts/static/search-worker.js`: C-3, paridad online/offline del motor JavaScript.

## Evaluación por corrección

### C-1 — Idempotencia y seguridad de POST `/notes`

Estado: **implementación correcta con cobertura automatizada insuficiente**.

Evidencia positiva:

- `scripts/api.py:231`: `_note_by_id()` consulta una nota por UUID.
- `scripts/api.py:245`: `_same_note_content()` compara título, texto y etiquetas.
- `scripts/api.py:691`: POST usa `insert()` en lugar de `upsert()`.
- `scripts/api.py:695`: fallos esperados de PostgREST/HTTP activan verificación idempotente.
- `scripts/api.py:707`: un reintento con contenido idéntico devuelve HTTP 200.
- `scripts/api.py:709`: el mismo UUID con contenido diferente devuelve HTTP 409 `note_id_conflict`.
- PUT y DELETE continúan protegidos por `@require_admin`.
- Prueba funcional ejecutada durante el ciclo: creación 201, reintento idéntico 200, colisión diferente 409 y conservación del título original.

Riesgo pendiente:

- `tests/test_audit_p0_p1_end_to_end.py:170` usa `assertIn`/`assertNotIn` sobre el texto fuente. Puede pasar aunque el flujo HTTP esté roto.
- La carpeta completa `tests/` está excluida por `.gitignore:14`; `git ls-files tests` no devuelve archivos.
- Las excepciones inesperadas distintas de `APIError`/`HTTPError` terminan en el manejador global 500, no en la respuesta 502 específica. No produce sobrescritura, pero conviene decidir y probar explícitamente el contrato.

Prueba requerida antes del commit:

- Mockear el cliente Supabase y llamar al endpoint Flask real.
- Afirmar 201 para alta nueva.
- Afirmar 200 para reintento idéntico tras conflicto o respuesta perdida.
- Afirmar 409 para UUID existente con contenido diferente.
- Afirmar que el registro persistido original no fue modificado.
- Afirmar que un fallo de inserción más fallo de consulta produce una respuesta JSON controlada.

### C-2 — Sincronización offline y búsqueda

Estado: **lógica principal corregida, con bloqueo residual de storage**.

Evidencia positiva:

- `scripts/static/app.js:20`: `_notesStorageReady` existe antes de registrar eventos de red.
- `scripts/static/app.js:35`: la reconexión no sincroniza antes de finalizar la carga local.
- `scripts/static/app.js:1721`: `initNotesStorage()` se espera con `await`.
- `scripts/static/app.js:1722`: el estado ready se activa después de inicializar IndexedDB/fallback.
- `scripts/static/app.js:1948`: `_isSyncingNotes` evita sincronizaciones simultáneas en la pestaña.
- `scripts/static/app.js:1993`: `navigator.locks` coordina múltiples pestañas cuando está disponible.
- `scripts/static/app.js:804` y `:1644`: búsqueda centralizada y ejecución inmediata con Enter.

Bloqueo funcional:

- `scripts/static/app.js:49` lee `localStorage.getItem("r2url")` sin `try/catch`.
- `scripts/static/app.js:50` vuelve a leer `localStorage` fuera del bloque protegido.
- Esto contradice la directiva del repositorio que exige proteger todo acceso a `localStorage` y puede abortar el script en navegación privada/restrictiva antes de ejecutar `DOMContentLoaded` e `initNotesStorage()`.

Corrección mínima sugerida:

- Crear `safeLocalStorageGet(key, fallback)` junto a `safeLocalStorageSet` o declarar un helper temprano antes de la inicialización de `_r2url`.
- Sustituir las dos lecturas tempranas por el helper.
- Añadir una prueba ejecutable en JavaScript (o navegador) donde `localStorage.getItem` lance `SecurityError` y comprobar que la aplicación continúa inicializando.

### C-3 — Paridad online/offline del motor de búsqueda

Estado: **correcto y listo técnicamente**.

Evidencia positiva:

- Python y JavaScript usan normalización NFKD.
- El worker elimina marcas Unicode y conserva letras/números Unicode al generar contexto.
- Los desempates son deterministas por puntuación, manual y página.
- La selección de tokens de contexto se ordena en ambos motores.
- El flujo legacy usa los campos fijos `interlock`, `error`, `message`, `observations` y delega al mismo algoritmo de síntomas en ambos lados.
- El límite solicitado se respeta en el worker offline.
- Se eliminó del worker el algoritmo legacy divergente y su código ya inaccesible.
- Prueba de paridad ejecutada durante el ciclo: igualdad exacta Python/JS para búsquedas fullwidth (`ＰＣＢ 22`, `ＤＯＳＥ 1`, `ＩＴＥＭ 409`), consultas normales, diagnóstico por síntomas y diagnóstico legacy.
- Prueba funcional en navegador durante el ciclo: búsqueda online y fallback offline correctos, badge `OFFLINE` visible y sin errores de consola inesperados.

Riesgo bajo aceptable:

- `\p{M}` y expresiones Unicode requieren un navegador moderno. Es compatible con el objetivo PWA actual, pero debería constar en la matriz mínima de navegadores.

## Validaciones ejecutadas

Entorno limpio creado temporalmente con Python 3.12 y dependencias de `requirements.txt`, `ruff` y `mypy`.

| Comando / prueba | Resultado |
|---|---|
| `python -m unittest discover -s tests -v` | **290/290 OK**, 26.106 s |
| `node --check scripts/static/app.js` | OK |
| `node --check scripts/static/search-worker.js` | OK |
| `python -m pip check` | OK, sin dependencias rotas |
| `git diff --check` | OK; avisos LF→CRLF únicamente |
| `ruff check scripts/api.py scripts/search_engine.py` | 7 observaciones preexistentes, ninguna en la lógica añadida |
| `mypy scripts/api.py scripts/search_engine.py` | No limpio: errores base de tipado/configuración; no se identificó uno originado en C-1/C-3 |

Observaciones de entorno:

- El `venv/` existente está roto porque referencia `C:\Users\CGutierrez\AppData\Local\Programs\Python\Python311\python.exe`, que ya no existe.
- La suite sí pasa en el entorno limpio temporal.
- `requirements.txt` no incluye herramientas de desarrollo (`ruff`, `mypy`) ni existe un archivo de dependencias de desarrollo reproducible.

## Hallazgos priorizados para el siguiente agente

### Alto — Tests excluidos del control de versiones

Evidencia: `.gitignore:14` contiene `tests/`; `git status --ignored` muestra `!! tests/`; `git ls-files tests` no lista archivos.

Impacto: el commit puede cambiar seguridad, sincronización y motores de búsqueda sin entregar las pruebas que justifican el cambio. Otra máquina o CI no puede reproducir las 290 verificaciones desde el repositorio.

Acción: dejar de ignorar `tests/` o añadir explícitamente al menos los tests de regresión necesarios. Verificar cuidadosamente que no se incluyan fixtures sensibles o artefactos grandes.

### Alto — Lecturas tempranas de localStorage no protegidas

Evidencia: `scripts/static/app.js:49-50`.

Impacto: posible fallo total del frontend en navegadores con storage bloqueado; invalida parcialmente el objetivo de resiliencia de C-2.

Acción: helper seguro para lecturas y prueba con `SecurityError`.

### Medio — Test de C-1 comprueba implementación, no comportamiento

Evidencia: `tests/test_audit_p0_p1_end_to_end.py:170-175`.

Impacto: falsos positivos; cambiar nombres o conservar cadenas podría hacer pasar el test sin garantizar idempotencia/no sobrescritura.

Acción: reemplazar o complementar con prueba HTTP conductual usando un fake de Supabase.

### Medio — Entorno oficial no reproducible

Evidencia: `venv/` no puede iniciar; no hay `requirements-dev.txt`/grupo dev fijado.

Impacto: el comando obligatorio de `AGENTS.md` falla en esta máquina sin recrear manualmente el entorno.

Acción: recrear `venv/` o documentar el comando de bootstrap; añadir dependencias de calidad en un archivo de desarrollo.

### Bajo — Deuda estática preexistente

Ruff informa 7 observaciones: captura ciega/silenciosa de excepciones, default no-string para `PORT` y simplificaciones de condicionales. Mypy tampoco está limpio por tipado débil de cachés/importación del paquete. No bloquean estas correcciones por sí solos, pero deben registrarse como deuda separada.

## Criterios para cambiar el veredicto a “LISTO PARA COMMIT”

1. Proteger las lecturas de `localStorage` de `scripts/static/app.js:49-50`.
2. Incorporar una prueba conductual de C-1 con los casos 201/200/409/no sobrescritura/error doble.
3. Hacer que ese test quede versionado; idealmente versionar toda la suite y configurar CI.
4. Ejecutar nuevamente los 290 tests, checks de sintaxis JavaScript, `pip check` y `git diff --check`.
5. Revisar `git diff --stat` y `git status --short` para confirmar que no entren `.venv-review`, cachés, secretos o data generada.

## Secuencia mínima recomendada

1. Corregir el acceso temprano a storage (C-2 residual).
2. Convertir el test estático de C-1 en test conductual.
3. Resolver la política de versionado de `tests/`.
4. Repetir validación completa.
5. Si todo pasa, crear un commit único sugerido: `fix: harden notes sync and search parity`.

## Estado final para traspaso

- C-1: funcionalmente válido; falta cobertura conductual versionada.
- C-2: mejora válida; falta cerrar el acceso temprano inseguro a `localStorage`.
- C-3: válido, paritario y probado.
- Suite: 290/290 pasa en entorno limpio.
- Commit: no creado.
- Decisión: **NO LISTO PARA COMMIT hasta cerrar los tres criterios bloqueantes**.
