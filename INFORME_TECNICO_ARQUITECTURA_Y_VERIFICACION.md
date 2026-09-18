# DOSSIER TÉCNICO DE ARQUITECTURA, CAMBIOS Y GUÍA DE VERIFICACIÓN
**Sistema:** SOLVI PWA — Plataforma Técnica de Diagnóstico, Esquemas y Mantenimiento Linac  
**Repositorio:** `proyecto_interlocks`  
**Estado:** Auditoría en curso / Offline-first parcial verificable / 325 tests Python aprobados localmente + smoke real de navegador
**Fecha de corte:** Septiembre 2026  

---

## 1. RESUMEN EJECUTIVO Y REGLAS CANÓNICAS

Este documento está diseñado para ser consumido por un **Arquitecto de Software Senior / Agente de Programación Experto** para continuar el mantenimiento, evolución y aseguramiento de calidad del proyecto.

### ⚠️ REGLAS NO NEGOCIABLES DEL PROYECTO
1. **CERO MENCIONES DE IA**: Queda terminantemente prohibido incluir términos como *"IA"*, *"AI"*, *"Inteligencia Artificial"* o derivados en cualquier texto visible para el usuario (interfaz, tooltips, modales, toasts, mensajes de error o logs de cliente). Utilizar siempre terminología técnica neutra: *"Análisis Heurístico"*, *"Diagnóstico Causal"*, *"Sistema de Inferencia Técnica"* o *"Modelo Predictivo"*.
2. **FILOSOFÍA OFFLINE-FIRST CON PDFs BAJO DEMANDA**: La búsqueda, esquemas y catálogo de medición funcionan con recursos locales; los PDFs no se precachean completos:
   - Los esquemas SVG vectoriales operan con datos estáticos locales.
   - El catálogo de multímetro y el visor PDF operan con archivos servidos desde el mismo origen (`/static/`).
   - Un PDF queda disponible sin red únicamente después de una descarga explícita y caché del navegador; no se distribuyen los 19 PDFs completos a cada dispositivo.
   - Las notas y órdenes técnicas se almacenan localmente en IndexedDB / localStorage con sincronización idempotente por lotes (`/notes/batch`).
3. **FUENTE ÚNICA DE VERDAD (SSOT)**: Los esquemas y catálogos tienen generadores automatizados (`scripts/tools/`). Toda modificación en los modelos de Python debe reflejarse en los JSON estáticos mediante los scripts de build correspondientes.
4. **INTEGRIDAD DE PRUEBAS**: No se admiten pruebas con `skipTest` artificiales ni mocks que encubran fallos funcionales. La suite debe pasar al 100% de manera determinista.

---

## 2. ARQUITECTURA TÉCNICA DEL SISTEMA

```
proyecto_interlocks/
├── scripts/
│   ├── api.py                    # API Flask, middleware de seguridad, CSP, endpoints REST
│   ├── circuit_data.py           # SSOT Python de los 5 subsistemas Linac (esquemas, nodos, cables)
│   ├── multimeter_service.py     # SSOT Python de los 20 Puntos de Prueba (TPs) y tolerancias
│   ├── graph_engine.py           # Motor de grafos Linac (1200+ nodos, BFS determinista)
│   ├── search_engine.py          # Motor de búsqueda y relevancia sobre los 19 manuales
│   ├── ai_service.py             # Pipeline heurístico/diagnóstico causal con fallback local
│   ├── static/
│   │   ├── app.js                # Orquestador UI, PWA, sincronizador IndexedDB, visor PDF
│   │   ├── circuit-visualizer.js # Renderizador vectorial SVG, zoom/pan focal, simulación de fallas
│   │   ├── multimeter.js         # Multímetro virtual, display 7-segmentos, modo HUD acoplado
│   │   ├── log-parser.js         # Parser y visualizador de cascadas de interlocks
│   │   ├── search-worker.js      # Web Worker de búsqueda y diagnóstico offline
│   │   ├── circuit_schematics.json # Archivo canónico distribuido de esquemas
│   │   ├── multimeter_catalog.json # Archivo canónico distribuido de puntos de prueba
│   │   ├── pdf.min.js            # Visor PDF alojado localmente (v3.11.174)
│   │   └── pdf.worker.min.js     # Web Worker local para renderizado PDF
│   ├── templates/
│   │   └── index.html            # Shell SPA responsive con diseño dark industrial
│   └── tools/
│       ├── generate_schematics.py# Generador SSOT de circuit_schematics.json
│       └── generate_multimeter.py# Generador SSOT de multimeter_catalog.json
├── data/
│   ├── search/catalog.json       # Índice maestro de los 19 manuales técnicos (6,322 págs)
│   ├── pages/                    # Extracción de texto estructurado por página
│   └── linac_graph.json          # Grafo topológico compilado
├── tests/                        # Suite Python + contratos + smoke Playwright
├── sw.js                         # Service Worker v28 con soporte HTTP 206 Partial Content
└── Procfile                      # Configuración de despliegue PaaS (Gunicorn multi-worker)
```

---

## 3. REGISTRO DETALLADO DE CAMBIOS RECIENTES (COMMITS CRÍTICOS)

### Commit `76db400`: Corrección de Veracidad Documental y HUD Multímetro
* **Veracidad Documental**:
  * `radiation_beam`: Renombrada la placa `PCB 22` a su designación técnica canónica **`PCB PPG`** (*Pulse Power Generator Board* / Placa Control de Modulador) y actualizados los cables `W202`, `W203` y `W215`.
  * `dosimetry`: Renombradas las placas analógicas `PCB 17` y `PCB 18` a **`PCB 12B`** (Canal 1) y **`PCB 12S`** (Canal 2).
  * Interlocks de dosimetría: Corregidos los códigos a los enclavamientos verídicos **`ITEM 456`** e **`ITEM 506`**.
  * Polarización de Cámara de Ionización (`TP100` y `HV_BIAS`): Corregido el valor nominal y de especificación a **`-320.0V DC`** (nominal `-320.0V`, límites `-325.0V` a `-315.0V`, advertencias `-323.0V` y `-317.0V`).
* **Multímetro HUD No Invasivo**:
  * Rediseñado el modal del multímetro (`#dmmFloatingModal`) a un **HUD flotante compacto en la esquina inferior derecha** (`bottom: 20px; right: 20px; max-width: 360px`).
  * Eliminado el fondo oscurecido (`backdrop`) de pantalla completa, permitiendo realizar zoom, paneo e interactuar con el esquema del circuito mientras se mide simultáneamente en el multímetro.
  * Protección de viewport en dispositivos móviles (`max-width: calc(100vw - 40px)`).
* **Trazabilidad**: Las referencias se registran en `data/documentary_traceability.json`; `data/search/catalog.json` distingue páginas indexadas de `physical_pages`. TP100 conserva la evidencia funcional de -320 V DC en dosimetría p. 43, pero esa página no se presenta como etiqueta textual TP100.

### Commit `84aa580`: SSOT de Circuitos, Simulación Interactiva y Leyenda
* **Fuente Única de Verdad (SSOT)**:
  * Creados los generadores `generate_schematics.py` y `generate_multimeter.py`.
  * Eliminada la duplicación hardcodeada de objetos JSON dentro de los archivos JavaScript.
  * Sincronizados `circuit_schematics.json` y `multimeter_catalog.json` dentro de `CORE` en `sw.js`; los fragmentos grandes de búsqueda se cargan bajo demanda y los PDFs permanecen bajo demanda.
* **Simulación Interactiva de Fallas**:
  * Implementada la función `toggleNodeState(nodeId)` en `circuit-visualizer.js`. El técnico puede hacer clic sobre cualquier componente para alternar entre **NOMINAL** y **FALLA / ABIERTO**, con feedback visual en rojo pulsante (`#ef4444`) y notificación de estado.
* **Búsqueda y Filtrado por Capas**:
  * La función `buscarEnEsquema(texto)` ahora permite aislar capas escribiendo **`POTENCIA`** (resalta cables `power` y `high_voltage`) o **`CONTROL`** (resalta cables `safety` y `feedback`).
* **Leyenda Técnica en UI**:
  * Agregado panel de leyenda explicativa en `scripts/templates/index.html` con codificación de colores estándar: 🟩 Verde (Nominal), 🟥 Rojo (Falla/Disparado), 🟧 Ámbar (Advertencia/Marginal).
* **Pruebas de Flujo**: Añadido `tests/test_technical_workflow.py` simulando carga de esquemas, interacción con TPs, simulación de fallas y filtrado de cables.

### Commit `c2fd33d`: Endpoint por Lotes y Hospedaje Local de PDF.js
* **Sincronización Masiva en Backend (`scripts/api.py`)**:
  * Creado `POST /notes/batch` que procesa hasta 50 apuntes por llamada con rate limit dedicado (`50 per hour`).
  * Verificación previa anti-sobreescritura (`select ... in_()`). Si el apunte existe con contenido idéntico es idempotente; si tiene contenido distinto responde `409 Conflict`.
* **Sincronización en Cliente (`scripts/static/app.js`)**:
  * `syncPendientes()` envía lotes en bloques de 50. Ante un `409 Conflict`, regenera UUIDs locales y reencola para evitar bloqueos de cola (*Head-of-Line*).
* **Hospedaje Local de PDF.js**:
  * Descargados `pdf.min.js` y `pdf.worker.min.js` directamente en `scripts/static/`.
  * Actualizado `sw.js` para precachear ambos recursos locales y eliminadas todas las referencias a `cdnjs.cloudflare.com` en los encabezados `Content-Security-Policy`.

### Commit `ed4450a`: Resiliencia en Almacenamiento e Infraestructura
* **Seguridad de `sessionStorage`**:
  * Creados helpers `safeSessionStorageGet` y `safeSessionStorageSet` respaldados por un `Map` volátil para tolerar `SecurityError` en Safari en navegación privada o WebViews médicas.
* **Protección contra valores nulos**:
  * Helper `safeStr(v)` aplicado a `.text` y `.title` en notas para evitar `TypeError: Cannot read properties of null (reading 'substring')`.
* **Alineación de Infraestructura (`Procfile`)**:
  * `web: gunicorn --chdir scripts api:app --bind 0.0.0.0:$PORT --timeout 120 --workers 2 --threads 2 --preload`.

---

## 4. MATRIZ DE VERIFICACIÓN PARA LA SIGUIENTE IA

La matriz canónica de afirmaciones es `data/documentary_traceability.json` y su explicación está en `MATRIZ_TRAZABILIDAD_SOLVI.md`. Ningún diagnóstico debe publicar PCB, interlock, tensión o página si no tiene una entrada verificable.

Antes de realizar nuevos cambios, ejecutar y validar el siguiente checklist:

| # | Área de Verificación | Comando / Procedimiento | Resultado Esperado |
|---|---|---|---|
| **Actual** | **Suite Python auditada** | `.venv-solvi312\\Scripts\\python.exe -m unittest discover -s tests -q` | **325/325 aprobadas**; la fila histórica inferior se conserva como referencia del dossier anterior. |
| 1 | **Suite de Pruebas** | `.\venv\Scripts\python.exe -m unittest discover -s tests` | Ejecutar en CI/Render con dependencias instaladas; 308 es conteo estático, no equivale a 308 aprobados. |
| 2 | **Paridad SSOT** | `.\venv\Scripts\python.exe scripts/tools/generate_schematics.py`<br>`.\venv\Scripts\python.exe scripts/tools/generate_multimeter.py` | Generación limpia sin discrepancias en Git status. |
| 3 | **Auditoría Documental** | `.\venv\Scripts\python.exe -m unittest tests/test_documentary_parity.py` | Verifica `physical_pages`, paridad indexada y matriz de trazabilidad. |
| 4 | **Flujo Técnico y DMM** | `.\venv\Scripts\python.exe -m unittest tests/test_technical_workflow.py` | Carga asíncrona y simulación virtual; no hay BLE/Web Serial. |
| 5 | **CERO Términos de IA** | Búsqueda por regex `\b(IA|AI|Inteligencia Artificial)\b` en `scripts/templates/index.html` | 0 coincidencias en etiquetas de texto visibles al usuario. |
| 6 | **Caché y CSP Offline** | Inspeccionar `CORE` en `sw.js` y CSP en `scripts/api.py` | No debe haber referencias a dominios externos de scripts/workers (`cdnjs`). |

---

## 5. DEUDA TÉCNICA Y ROADMAP DE MEJORAS SUGERIDAS

1. **Centralización de Caché Multi-Worker (Redis)**:
   * *Estado actual:* Redis es compatible mediante `NOTES_CACHE_REDIS_URL`/`REDIS_URL`; sin esa variable queda un fallback local de desarrollo.
   * *Recomendación:* Configurar Redis compartido en Render para que la garantía multi-worker sea efectiva.
2. **Auto-enrutamiento Ortogonal de Cables (Manhattan / A\*)**:
   * *Estado actual:* Los vértices de giro de cables SVG se calculan con coordenadas de puntos estáticas.
   * *Recomendación:* Implementar un algoritmo ortogonal ligero que calcule automáticamente los giros de 90° entre pines para facilitar la incorporación masiva de nuevos esquemas sin trazar vértices manualmente.
3. **Internacionalización de Filtros de Circuito**:
   * *Estado actual:* Las palabras clave `POTENCIA` y `CONTROL` en `buscarEnEsquema` están en español.
   * *Recomendación:* Mapear los filtros de tipo de cable mediante un diccionario configurable si se habilita soporte multi-idioma.
4. **Sincronización Dinámica de Planos**:
   * *Estado actual:* Los esquemas se distribuyen mediante el archivo estático compilado `circuit_schematics.json`.
   * *Recomendación:* Habilitar actualización diferencial de esquemas vía Supabase guardando versiones revisadas en IndexedDB.

## 6. ENDURECIMIENTO APLICADO EN ESTA ITERACIÓN

- **Datos y seguridad:** se añadió `supabase/migrations/001_notes_rls.sql` con esquema tipado, restricciones de longitud, índice temporal y RLS que bloquea acceso directo de `anon`/`authenticated`. Las rutas `/admin/*` y las mutaciones administrativas de apuntes tienen límites específicos además de la validación de contraseña.
- **Escalado:** Flask-Limiter acepta `RATELIMIT_STORAGE_URI` o `REDIS_URL`; la caché de apuntes acepta `NOTES_CACHE_REDIS_URL`/`REDIS_URL`. Sin Redis, el fallback en memoria se considera solo desarrollo y no una garantía multi-worker.
- **Apuntes:** `GET /notes?page=N&limit=M` pagina hasta 100 registros y conserva una respuesta de lista sin parámetros para clientes antiguos. Lotes y componentes rechazan tipos JSON incorrectos en lugar de convertirlos silenciosamente.
- **PWA:** el Service Worker ya no descarga todos los fragmentos durante `install`; los índices se solicitan al buscar. Las peticiones de red tienen timeout. El visor PDF cancela la tarea de carga anterior, evita retener buffers globales y solo conserva un PDF después de una descarga explícita.
- **UX/accesibilidad:** el manifiesto permite orientación horizontal, los controles principales tienen nombres accesibles y los estados de sincronización se exponen mediante `role=status`/`aria-live`.

## 7. QUINTA MEJORA — CALIDAD Y PRUEBAS EJECUTABLES

- **Bootstrap reproducible:** `scripts/bootstrap_local.ps1` busca explícitamente Python 3.12, crea el entorno virtual, instala `requirements-dev.txt` y termina con `pip check`. Se ejecutó con Python 3.12.14; no se versiona ningún `.venv`.
- **Dependencias fijadas:** `requirements.txt`, `requirements-dev.txt` y `requirements.lock` están fijados; el lock coincide con `pip freeze` del entorno auditado.
- **Contrato API:** `tests/test_api_contract.py` prueba `/health`, `/openapi.json`, paginación de `/search` y `/notes`, tipos estrictos y bloqueo de administración. La especificación OpenAPI declara también `/notes/batch` y sus parámetros.
- **Supabase/R2/Render:** `tests/test_integrations_contract.py` verifica la migración RLS, la frontera `service_role`, ausencia de secretos en el cliente, `R2_PUBLIC_URL`, `render.yaml`, `.python-version` y el lock de dependencias. No se inventa una conexión de producción: para validar datos reales se requieren credenciales del dueño del despliegue.
- **DOM, navegador y simulación:** `tests/browser_smoke.mjs` usa Chromium real con Playwright; abre la pantalla Multímetro, cambia a `Simulador Banco`, ejecuta la falla `Normal`, comprueba el resultado DOM, registra y controla el Service Worker, verifica el cache versionado sin precargar todos los chunks y recarga el shell offline. Ejecución local confirmada: `{ok:true, serviceWorker:true, simulation:true, dom:true}`.
- **Corrección encontrada por navegador:** la carga asíncrona del catálogo DMM podía renderizar un TP inexistente antes de terminar el `fetch`; se agregó una guarda de catálogo y formato `N/D` para que el flujo no rompa durante esa ventana.
- **CI/Render:** `.github/workflows/ci.yml` conserva la suite Python y agrega el job `browser-contract` con Python 3.12, Node 20, Playwright, servidor Flask local y apagado garantizado. `render.yaml` despliega solo `requirements.txt`; las dependencias de pruebas no llegan a producción.
- **Calidad estática:** `compileall`, `node --check` y `git diff --check` pasan. Ruff y mypy todavía reportan deuda preexistente (imports, tipado gradual y scripts de extracción); no se ocultó esa deuda ni se presentó como “lint limpio”.

---
*Fin del Dossier Técnico — Documento listo para transferencia y auditoría.*
