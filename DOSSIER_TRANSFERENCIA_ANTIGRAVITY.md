# Dossier de transferencia técnica — SOLVI

**Fecha de corte:** 20 de septiembre de 2026  
**Estado Git:** cambios locales sin commit. Este documento describe el árbol de trabajo actual, no necesariamente `main` remoto.

## 1. Propósito y límites del producto

SOLVI es una PWA de apoyo documental para ingeniería de servicio de aceleradores lineales Elekta. Busca información en un corpus indexado de 19 manuales y ofrece:

- búsqueda por texto en modo online y offline;
- correlación documental de síntomas/interlocks;
- análisis causal remoto con Gemini, restringido a evidencia recuperada del corpus;
- análisis local de logs;
- apuntes sincronizables y formulario local de informes;
- consulta de PDFs bajo demanda, sin descargar por defecto el corpus completo.

No es un sistema de control clínico, no certifica cableado físico, no ejecuta acciones sobre el equipo y no debe inventar mediciones, puntos de prueba, interlocks, componentes, conexiones ni códigos.

## 2. Arquitectura comprobada

| Capa | Implementación | Evidencia principal |
|---|---|---|
| Backend | Python 3.12, Flask, Gunicorn | `scripts/api.py`, `Procfile` |
| Búsqueda online | índice en memoria Python | `scripts/search_engine.py` |
| Búsqueda offline | Web Worker Vanilla JS | `scripts/static/search-worker.js` |
| UI | HTML, CSS y JavaScript nativo | `scripts/templates/index.html`, `scripts/static/app.js` |
| IA | Google Gemini con waterfall, caché LRU/TTL y failover documental | `scripts/ai_service.py` |
| PWA | Service Worker y Cache Storage | `sw.js`, `manifest.json` |
| Datos | fragmentos JSON de 19 manuales; PDFs no versionados por tamaño | `data/search/catalog.json`, `data/pages/` |
| Notas | Supabase; el backend conserva la frontera de privilegios | `scripts/api.py`, `supabase/migrations/` |
| PDFs | Cloudflare R2 o ruta configurada; caché solo por descarga explícita | `scripts/static/app.js`, `sw.js` |

### Paridad obligatoria

Las reglas de normalización, tokenización, filtrado y puntuación deben mantenerse equivalentes en `scripts/search_engine.py` y `scripts/static/search-worker.js`. Cualquier cambio en uno exige prueba de paridad en el otro.

## 3. Cambios ya realizados en este árbol de trabajo

### 3.1 Retiro de Esquemas y Multímetro

Se retiraron de la interfaz, rutas API/OpenAPI y caché PWA los módulos que mostraban información no suficientemente verificable.

- Eliminados: `scripts/graph_engine.py`, `scripts/circuit_data.py`, `scripts/multimeter_service.py`, visualizador SVG, multímetro JS, datos de rutas/mediciones y generadores de grafo.
- Las rutas antiguas `/diagnose/graph`, `/circuits/*` y `/multimeter/*` deben responder **404**.
- No deben existir botones `navC` ni `navM`, ni recursos retirados en `CORE` del Service Worker.
- `sw.js` usa ahora la caché versionada `solvi-v31` y deja fuera recursos retirados.
- `scripts/static/log-parser.js` ya no ofrece un botón hacia rutas de esquemas inexistentes.

Contrato actual: `tests/test_removed_modules_contract.py` y `tests/browser_smoke.mjs`.

### 3.2 Diagnóstico causal

- El servicio Gemini conserva waterfall de modelos, timeout de 90 segundos, caché LRU de una hora, extracción resistente de JSON y saneamiento de errores.
- Ante indisponibilidad/503 se usa contingencia documental local en vez de publicar la respuesta cruda del proveedor.
- La evidencia debe provenir de páginas recuperadas; el modelo no es una fuente de verdad técnica.
- La interfaz muestra señales/puntos de comprobación como referencias, no como una orden de medición ni como una tolerancia canónica.

### 3.3 PWA, PDFs y offline

- El catálogo de búsqueda se precachea; los fragmentos por manual se cargan bajo demanda.
- Los PDFs completos no se precachean. Una descarga explícita puede conservar un manual para uso offline.
- La navegación shell se valida en modo offline después del registro del Service Worker.
- PDF.js debe cancelar/destrozar la carga anterior antes de abrir otro PDF para evitar acumulación de RAM.

### 3.4 Informes

Existe una pantalla inicial de **Informes** con campos editables para cliente, servicio, equipo, incidente, diagnóstico, revisión/trabajo, conclusiones, imágenes y una tabla dinámica de repuestos (P/N, descripción, cantidad).

**Importante:** todavía es un formulario local. No existe implementación validada de generación/descarga DOCX/PDF ni persistencia de informes. El modelo visual debe conservar como referencia el DOCX suministrado por el dueño del producto: cabecera institucional, bloques de contexto, incidente, diagnóstico, revisión, trabajo realizado, conclusiones, imágenes y tabla de repuestos.

## 4. Validación ejecutada

| Comprobación | Resultado | Alcance |
|---|---:|---|
| `python -m unittest discover -s tests -v` con `.venv-solvi312` | OK, 96 tests | backend, búsqueda, IA, PWA, datos, logs, notas, contratos |
| `node --check scripts/static/app.js` | OK | sintaxis frontend |
| `node --check scripts/static/log-parser.js` | OK | sintaxis parser |
| `node --check sw.js` | OK | sintaxis Service Worker |
| `node --check tests/browser_smoke.mjs` | OK | sintaxis prueba E2E |
| Chromium real / Playwright | OK | Buscar, diagnóstico documental/causal, Registros, Informes, rutas 404, SW y recarga offline |
| `git diff --check` | OK | sin errores de espacios en diff |

La prueba de navegador comprueba expresamente que escribir en Buscar no dispara consulta y que Enter sí lo hace; detecta una regresión previa de búsqueda por tecla.

## 5. Riesgos y decisiones que debe revisar Antigravity

### Crítico / alto

1. **Cobertura eliminada en el árbol actual.** Hay múltiples archivos de tests borrados y la suite pasó de una base mucho mayor a 96 pruebas. No asumir que “96 OK” representa cobertura equivalente. Revisar el diff de eliminaciones antes de commit y restaurar/reemplazar pruebas útiles de API, integración, rendimiento, PWA y flujo técnico.
2. **Código muerto residual de grafo.** Aunque no hay navegación, rutas ni assets publicados, `scripts/static/app.js` y `scripts/static/search-worker.js` conservan funciones internas históricas de grafo no alcanzables. Retirarlas completamente, junto con estilos y comentarios relacionados, en un cambio aislado; después actualizar las pruebas de contrato para impedir su retorno.
3. **Documentación histórica contradictoria.** `INFORME_TECNICO_ARQUITECTURA_Y_VERIFICACION.md` e informes históricos mencionan visualizador, rutas, multímetro o archivos ya eliminados. No son documentación vigente. Actualizarlos, archivarlos explícitamente como históricos o crear un único documento de arquitectura vigente.
4. **Informes no terminados.** La pantalla no genera un artefacto entregable ni aplica el formato del DOCX modelo. No publicitarla como generador de informes hasta implementar, renderizar y revisar visualmente DOCX/PDF.

### Medio

5. **Verificación humana de evidencia.** `data/documentary_traceability.json` conserva una matriz de afirmación/manual/página/extracto, pero la certificación final debe ser humana y trazable. Añadir estado de revisión, autor, fecha, hash de manual y criterio de aprobación.
6. **IA y seguridad operacional.** Prohibir que la respuesta IA se presente como instrucción clínica o sustituto de manual/procedimiento. Debe incluir citas clicables, incertidumbre y aviso para personal autorizado.
7. **Pruebas de despliegue Render.** Se validó configuración estática, no un despliegue real reciente en Render. Ejecutar smoke test posterior a deploy contra URL de staging.

## 6. Plan recomendado por fases

### Fase A — Higiene y contratos de retiro

1. Revisar cada test eliminado; restaurar o sustituir pruebas con valor real.
2. Eliminar por completo los restos de funciones de grafo en `app.js` y `search-worker.js`; borrar estilos CSS sin uso.
3. Actualizar/archivar documentación histórica.
4. Añadir un test que asegure que Service Worker, HTML, OpenAPI y Worker no contengan ni soliciten recursos de módulos retirados.

### Fase B — Informes entregables

1. Diseñar un modelo de datos de informe validado en backend.
2. Implementar vista previa responsive basada en el DOCX de referencia.
3. Implementar generación DOCX, idealmente mediante plantilla controlada; usar Gemini solo para proponer texto del cuerpo y siempre como borrador editable con citas.
4. Añadir imágenes, repetición dinámica de repuestos, exportación y pruebas visuales/renderizadas.

### Fase C — Calidad, seguridad y despliegue

1. Restaurar cobertura API/contrato, tests de Supabase/R2 y pruebas de renderizado de informes.
2. Añadir E2E en CI: Chromium, Service Worker, offline, una respuesta Gemini 503 y Render smoke.
3. Ejecutar `pip check`, análisis de vulnerabilidades y prueba de CORS/autorización con entorno de staging.
4. Confirmar migraciones RLS en Supabase antes de habilitar escritura remota de informes.

## 7. Reglas de implementación no negociables

- No inventar valores eléctricos, tolerancias, TP, PCB, cables, interlocks ni rutas físicas.
- Cada afirmación canónica requiere manual, página física, extracto y estado verificable.
- No incluir claves de Gemini, Supabase o R2 en frontend, repositorio o logs.
- No descargar/precachear todos los PDFs por defecto.
- Mantener `localStorage` dentro de `try/catch`.
- Preservar la paridad entre ambos motores de búsqueda.
- Antes de enviar a `main`, ejecutar la suite Python, verificaciones JS, prueba E2E Chromium y `git diff --check`.

## 8. Comandos de reproducción local

```powershell
# Bootstrap local si aún no existe el entorno
$env:SOLVI_PYTHON312 = "<ruta-a-python-3.12>"
.\scripts\bootstrap_local.ps1 -VenvPath ".venv-solvi312"

# Suite Python
.\.venv-solvi312\Scripts\python.exe -m unittest discover -s tests -v

# Verificación de sintaxis JavaScript
node --check scripts\static\app.js
node --check scripts\static\log-parser.js
node --check sw.js
node --check tests\browser_smoke.mjs

# Servidor local
.\.venv-solvi312\Scripts\python.exe scripts\api.py

# E2E Chromium (con Playwright instalado y servidor activo)
$env:SOLVI_BASE_URL = "http://127.0.0.1:5000"
$env:SOLVI_PLAYWRIGHT_ROOT = "<ruta-a-playwright>"
node tests\browser_smoke.mjs
```

## 9. Prompt de transferencia sugerido

```text
Actúa como principal engineer full-stack, QA de PWA, auditor de seguridad y revisor de calidad para SOLVI. Lee primero DOSSIER_TRANSFERENCIA_ANTIGRAVITY.md y AGENTS.md completos. Trabaja sobre el árbol actual sin descartar cambios no confirmados y no hagas refactors grandes sin evidencia.

Objetivo inmediato: preparar el proyecto para un commit/deploy seguro en Render. Prioriza: (1) recuperar o reemplazar cobertura útil eliminada; (2) eliminar completamente el código muerto de grafo/esquemas/multímetro que quede en app.js, search-worker.js, CSS o documentación; (3) completar Informes como un flujo real basado en el DOCX de referencia, con campos editables, imágenes, repuestos dinámicos, vista previa y exportación controlada; (4) garantizar que Gemini solo redacte borradores sustentados por citas reales de los manuales.

Reglas críticas: no inventes datos técnicos; conserva paridad backend/offline; no expongas secretos; no precachees todos los PDFs; trata cualquier salida de IA como hipótesis editable y enlazada a evidencia. Antes de modificar, inspecciona git diff/status y ejecuta las pruebas existentes. Después de cada fase ejecuta tests Python, checks JS, Playwright Chromium, git diff --check y, si es posible, smoke contra staging Render.

Entrega un informe con cambios, archivos/líneas, pruebas ejecutadas, cobertura recuperada, riesgos no resueltos y una decisión clara listo/no listo para commit. No declares nada correcto sin evidencia de código, test o ejecución real.
```
