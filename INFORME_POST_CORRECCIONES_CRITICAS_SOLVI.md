# SOLVI — Informe técnico posterior a correcciones críticas

Fecha: 2026-09-17  
Repositorio: `C:\Users\CGutierrez\Desktop\proyecto_interlocks`  
Destinatario: siguiente IA o desarrollador senior responsable de revisión, commit y despliegue.

## Dictamen ejecutivo

**LISTO PARA REVISIÓN DE COMMIT.**

Los tres bloqueos identificados en `REVISION_FINAL_PRECOMMIT_SOLVI.md` fueron corregidos:

1. El arranque del frontend ya tolera que `localStorage` lance `SecurityError`.
2. C-1 ahora cuenta con pruebas HTTP conductuales que demuestran 201, 200 idempotente, 409 sin sobrescritura y 502 controlado.
3. `tests/` dejó de estar ignorado y puede incorporarse al control de versiones.

También se hicieron dos mejoras directamente relacionadas con la confiabilidad del ciclo:

- Se añadió `requirements-dev.txt` para reconstruir el entorno de QA.
- Se corrigió un benchmark preexistente inestable, separando explícitamente latencia fría y rendimiento sostenido.

La validación final terminó con **296/296 pruebas aprobadas**. No se creó commit ni se modificaron datos o manuales.

Después de esa revisión se incorporó además una puerta de calidad GitHub → Render. La suite queda versionada y se ejecuta en GitHub Actions, pero Render continúa instalando solamente dependencias de producción. Un fallo de CI impide el autodespliegue.

## Alcance acumulado de la rama de trabajo

Este estado incluye las correcciones previas C-1, C-2 y C-3 más el cierre de los bloqueos pre-commit:

- `scripts/api.py`: idempotencia segura de notas, protección contra sobrescritura y respuestas JSON controladas.
- `scripts/static/app.js`: sincronización offline inicializada correctamente, protección multi-pestaña, búsqueda con Enter y storage seguro.
- `scripts/search_engine.py`: determinismo y paridad del motor Python.
- `scripts/static/search-worker.js`: paridad online/offline del motor JavaScript.
- `.gitignore`: permite versionar pruebas e ignora entornos virtuales temporales `.venv*`.
- `requirements-dev.txt`: dependencias funcionales más Ruff y Mypy.
- `tests/`: suite completa ahora visible para Git, con nuevas pruebas conductuales.
- `.github/workflows/ci.yml`: validación automática en cada push o pull request hacia `main`.
- `render.yaml`: despliegue condicionado a checks aprobados, filtro de cambios de runtime y raíz de ejecución corregida.
- `README.md`: instrucciones reproducibles para desarrollo, CI y despliegue.

## Corrección 6 — Separación correcta entre QA en GitHub y runtime en Render

### Problema

Excluir `tests/` de Git evitaba que un clon limpio —incluido GitHub Actions— pudiera detectar regresiones antes del despliegue. Al mismo tiempo, el `rootDir: scripts` de Render hacía que el servicio no tuviera una vista coherente de recursos que realmente residen en la raíz: `data/`, `manifest.json`, `sw.js` y `requirements.txt`.

Un entorno virtual no debe subirse al repositorio: contiene rutas y binarios específicos de una máquina. Lo reproducible son los archivos de dependencias y los comandos automatizados.

### Implementación

- Se añadió `.github/workflows/ci.yml` con Python 3.12 y Node 20.
- CI instala `requirements-dev.txt`, valida dependencias, compila los fuentes Python, ejecuta las 296 pruebas y comprueba sintaxis de los seis JavaScript críticos.
- `render.yaml` usa `autoDeployTrigger: checksPass`; Render no autodespliega un commit cuyos checks de GitHub fallen.
- `buildFilter.paths` limita los despliegues a cambios en runtime: `scripts/**`, `data/**`, `requirements.txt`, `render.yaml`, `manifest.json`, `sw.js` y `Procfile`.
- Se eliminó `rootDir: scripts`. El build corre desde la raíz con `pip install -r requirements.txt` y Gunicorn arranca mediante `--chdir scripts`.
- Render no instala `requirements-dev.txt`; Ruff, Mypy y demás herramientas de QA quedan fuera del entorno productivo.
- `.venv*/` permanece ignorado; cada desarrollador y GitHub Actions reconstruyen su propio entorno.

### Por qué las pruebas sí deben estar en Git

Versionar pruebas no equivale a instalarlas como dependencia ni ejecutarlas en producción. En el runtime nativo de Render el checkout puede contenerlas, pero no son importadas por Gunicorn y su tamaño actual es de aproximadamente 231 KB. Excluirlas físicamente exigiría migrar a una imagen Docker con una etapa de empaquetado; esa complejidad no aporta una mejora operativa proporcional en este proyecto.

### Protección añadida

`tests/test_architectural_restructure_and_resilience.py` ahora comprueba el contrato de despliegue: puerta `checksPass`, filtro de build, comando de instalación productivo, arranque con `--chdir scripts`, ausencia del antiguo `rootDir` y presencia del workflow de CI.

## Corrección 1 — Lectura segura de localStorage

### Problema

`scripts/static/app.js` leía `localStorage.getItem("r2url")` durante la evaluación inicial del script y fuera de `try/catch`. En Safari/iOS, navegación privada o contextos con storage bloqueado, esa lectura puede lanzar `SecurityError` y detener toda la aplicación antes de `DOMContentLoaded`.

### Implementación

- `scripts/static/app.js:23`: se añadió `safeLocalStorageGet(key, fallback)`.
- El helper devuelve el valor almacenado o el fallback.
- Cualquier excepción del navegador se absorbe únicamente en este límite de compatibilidad.
- `scripts/static/app.js:58-59`: las dos lecturas tempranas de `r2url` usan el helper.
- Los demás accesos directos a `localStorage.getItem` ya estaban dentro de bloques `try/catch`.

### Pruebas

- `tests/test_notes_offline_storage.py:35`: extrae y ejecuta el helper JavaScript real mediante Node.js con un `localStorage.getItem()` que lanza `DOMException("SecurityError")`.
- Verifica que el proceso no falle y que retorne el fallback.
- `tests/test_notes_offline_storage.py:61`: comprueba que el arranque de R2 no vuelva a usar una lectura directa.

### Riesgo residual

Bajo. El helper no escribe ni altera storage; solo encapsula la lectura. Si Node.js no existe en una máquina de QA, la prueba dinámica se omite explícitamente, pero la prueba estructural continúa cubriendo el uso del helper.

## Corrección 2 — Pruebas reales para idempotencia de notas

### Problema

El test anterior solo buscaba cadenas como `insert()` y `note_id_conflict` en el código. Ese enfoque podía producir falsos positivos sin demostrar el comportamiento del endpoint.

### Implementación de producción reforzada

- `scripts/api.py:691`: POST `/notes` usa `insert`, nunca `upsert`.
- `scripts/api.py:695`: errores previstos de PostgREST/HTTP activan la consulta por UUID.
- `scripts/api.py:700`: cualquier fallo del SDK/transporte durante la consulta se transforma en una salida controlada.
- `scripts/api.py:707`: reintento con contenido idéntico retorna HTTP 200.
- `scripts/api.py:709`: UUID existente con contenido distinto retorna HTTP 409 y no actualiza.
- `scripts/api.py:718`: excepciones inesperadas de integración retornan JSON 502 sin exponer el detalle al cliente.
- Las capturas amplias están justificadas con `noqa: BLE001` porque son límites HTTP/SDK y el endpoint debe conservar un contrato JSON.

### Pruebas conductuales añadidas

En `tests/test_api_endpoints.py` se añadió un fake de Supabase con almacenamiento real en memoria y semántica de `insert/select/eq/limit/execute`.

- Línea aproximada 237: alta nueva retorna 201; reintento idéntico retorna 200; existe una sola fila.
- Línea aproximada 256: mismo UUID con contenido diferente retorna 409; la fila original permanece idéntica.
- Línea aproximada 282: conflicto seguido de fallo de consulta retorna JSON 502.
- Línea aproximada 300: excepción inesperada retorna JSON 502 y no filtra el mensaje interno.

Estas pruebas llaman al endpoint Flask real mediante `app.test_client()`. No son snapshots ni verificaciones de texto fuente.

## Corrección 3 — Suite incorporable al repositorio

### Problema

`.gitignore` excluía `tests/`, por lo que ninguna de las 290 pruebas previas ni las regresiones nuevas podía formar parte del commit o ejecutarse desde un clon limpio.

### Implementación

- Se eliminó la regla `tests/` de `.gitignore`.
- La carpeta completa aparece ahora como contenido no rastreado listo para añadir.
- Se revisaron los archivos con patrones conocidos de claves Gemini, Supabase y claves privadas: no se encontraron secretos.
- Se añadió `.venv*/` a `.gitignore` para evitar incorporar entornos temporales.

### Precaución para el commit

La suite completa nunca estuvo versionada en el estado base. El próximo agente debe añadir deliberadamente los 21 archivos de `tests/`, no solo los dos modificados, para que un clon limpio tenga la misma cobertura validada aquí.

No usar `git add .` sin revisar primero `git status --short --untracked-files=all`, porque también existen dos informes Markdown no rastreados.

## Corrección 4 — Entorno de QA reproducible

### Problema

El directorio `venv/` existente está roto: referencia una instalación eliminada de Python 3.11. `requirements.txt` contiene runtime, pero no Ruff ni Mypy.

### Implementación

Se añadió `requirements-dev.txt`:

```text
-r requirements.txt

ruff>=0.16.0
mypy>=1.15.0
```

Comandos recomendados para Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

No se reemplazó ni eliminó el `venv/` del usuario. Los entornos temporales utilizados para validar se eliminaron al finalizar.

## Corrección 5 — Benchmark no determinista

### Problema observado

`test_circuit_matcher_high_performance_and_no_truncation` exigía menos de 30 ms en una única llamada. Esa llamada podía incluir la construcción perezosa del índice y fluctuaba entre aproximadamente 32 y 38 ms, aunque las llamadas operativas calientes quedaban entre 12.4 y 14.2 ms.

### Corrección

`tests/test_audit_fixes.py:359` ahora mide dos contratos diferentes:

- Primera ejecución fría: menos de 50 ms.
- Cinco ejecuciones calientes: mediana menor de 30 ms.

No se elevó el límite operativo caliente ni se omitió la aserción funcional. La prueba sigue comprobando el subsistema y nodos encontrados.

## Resultados de validación

### Suite completa

Comando:

```powershell
.\.venv-ci-check\Scripts\python.exe -m unittest discover -s tests -v
```

Resultado final:

- **296 tests ejecutados**.
- **296 tests aprobados**.
- Duración: **32.970 s** en un entorno virtual nuevo.
- Benchmark masivo: 100 consultas en 1.45 s; 14.54 ms/consulta en esa ejecución.

La suite pasó después de todas las modificaciones y se ejecutó sin otros procesos de validación en paralelo.

### Validaciones adicionales

| Verificación | Resultado |
|---|---|
| `node --check scripts/static/app.js` | OK |
| `node --check scripts/static/search-worker.js` | OK |
| `node --check` sobre circuit visualizer, log parser, multimeter y service worker | OK |
| `python -m pip check` | OK, sin dependencias rotas |
| Parseo YAML de `render.yaml` y `.github/workflows/ci.yml` | OK |
| Prueba específica del contrato GitHub/Render | OK |
| `git diff --check` | OK; solo avisos LF→CRLF de Windows |
| Ruff sobre los dos tests modificados principales | OK, sin hallazgos |
| Escaneo de secretos en `tests/` | Sin coincidencias conocidas |
| Mypy focalizado | 7 errores base; ninguno corresponde a la lógica nueva |

### Deuda estática no introducida

Ruff conserva 7 hallazgos previos en `scripts/api.py` y `scripts/search_engine.py`:

- Captura silenciosa de excepción en enriquecimiento de esquema.
- Captura amplia en `/diagnose/ai`.
- Default entero para `PORT` en `os.environ.get`.
- Dos condicionales simplificables.
- Un retorno booleano simplificable.

Mypy conserva 7 errores base relacionados con el tipo de la caché, asignación de método Flask y agregación de objetos. Deben tratarse como una fase de tipado separada; no impiden estas correcciones y no se ocultaron globalmente.

## Estado Git esperado

Archivos rastreados modificados:

- `.gitignore`
- `README.md`
- `render.yaml`
- `scripts/api.py`
- `scripts/search_engine.py`
- `scripts/static/app.js`
- `scripts/static/search-worker.js`

Archivos nuevos importantes:

- `requirements-dev.txt`
- `.github/workflows/ci.yml`
- los 21 archivos bajo `tests/`
- `REVISION_FINAL_PRECOMMIT_SOLVI.md`
- `INFORME_POST_CORRECCIONES_CRITICAS_SOLVI.md`

No se creó commit. No incluir `venv/`, `.venv*`, cachés, `manuals/`, `.env` ni configuraciones locales.

## Instrucciones para la siguiente IA

1. Leer este informe y revisar el diff funcional de los cinco archivos rastreados modificados.
2. Confirmar con `git status --short --untracked-files=all` que solo se añadan los archivos enumerados.
3. Añadir la suite completa `tests/` al commit para no volver a perder reproducibilidad.
4. Ejecutar desde un entorno nuevo los 296 tests y los seis `node --check` del workflow.
5. No modificar la paridad entre `scripts/search_engine.py` y `scripts/static/search-worker.js` de forma unilateral.
6. No convertir nuevamente POST `/notes` a `upsert`; eso reintroduciría sobrescritura anónima.
7. Si se decide corregir Ruff/Mypy, hacerlo en un commit posterior para mantener trazabilidad.

## Propuesta de commits

Opción recomendada, dos commits:

1. `fix: harden notes sync and search parity`
   - Los cuatro archivos funcionales de C-1/C-2/C-3.
2. `test: version regression suite and dev tooling`
   - `.gitignore`, `requirements-dev.txt`, `.github/workflows/ci.yml`, `render.yaml`, `README.md`, `tests/` y, si se desean conservar, los informes.

Esta separación permite revertir o revisar producción independientemente de la incorporación histórica de la suite.

## Conclusión

Los tres puntos críticos solicitados están resueltos y verificados. El código queda **listo para revisión de commit**, con pruebas reproducibles y sin bloqueos funcionales conocidos dentro del alcance C-1/C-2/C-3. La única deuda restante identificada es estática/preexistente y está documentada para una fase posterior.
