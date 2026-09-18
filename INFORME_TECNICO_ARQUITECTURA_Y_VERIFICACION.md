# DOSSIER TÉCNICO DE ARQUITECTURA, CAMBIOS Y GUÍA DE VERIFICACIÓN
**Sistema:** SOLVI PWA — Plataforma Técnica de Diagnóstico, Esquemas y Mantenimiento Linac  
**Repositorio:** `proyecto_interlocks`  
**Estado:** Producción / Offline-First / 308 Tests Aprobados (0 skipped, 0 fallos)  
**Fecha de corte:** Septiembre 2026  

---

## 1. RESUMEN EJECUTIVO Y REGLAS CANÓNICAS

Este documento está diseñado para ser consumido por un **Arquitecto de Software Senior / Agente de Programación Experto** para continuar el mantenimiento, evolución y aseguramiento de calidad del proyecto.

### ⚠️ REGLAS NO NEGOCIABLES DEL PROYECTO
1. **CERO MENCIONES DE IA**: Queda terminantemente prohibido incluir términos como *"IA"*, *"AI"*, *"Inteligencia Artificial"* o derivados en cualquier texto visible para el usuario (interfaz, tooltips, modales, toasts, mensajes de error o logs de cliente). Utilizar siempre terminología técnica neutra: *"Análisis Heurístico"*, *"Diagnóstico Causal"*, *"Sistema de Inferencia Técnica"* o *"Modelo Predictivo"*.
2. **FILOSOFÍA OFFLINE-FIRST REAL**: La aplicación debe ser 100% operativa en búnkeres radiológicos sin conexión a internet ni red local:
   - Los esquemas SVG vectoriales operan con datos estáticos locales.
   - El catálogo de multímetro y el visor PDF operan con archivos servidos desde el mismo origen (`/static/`).
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
│   │   ├── search-worker.js      # Web Worker de búsqueda y diagnóstico offline (BM25/TF-IDF)
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
├── tests/                        # 22 módulos de pruebas automatizadas (308 tests)
├── sw.js                         # Service Worker v27 con soporte HTTP 206 Partial Content
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
* **Pruebas**: Creado `tests/test_documentary_parity.py` validando que todos los manuales y páginas referenciadas existan en `catalog.json` y no excedan el límite físico de páginas del manual.

### Commit `84aa580`: SSOT de Circuitos, Simulación Interactiva y Leyenda
* **Fuente Única de Verdad (SSOT)**:
  * Creados los generadores `generate_schematics.py` y `generate_multimeter.py`.
  * Eliminada la duplicación hardcodeada de objetos JSON dentro de los archivos JavaScript.
  * Sincronizados `circuit_schematics.json` y `multimeter_catalog.json` dentro de `CORE` en `sw.js` para garantizar precarga offline.
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

Antes de realizar nuevos cambios, ejecutar y validar el siguiente checklist:

| # | Área de Verificación | Comando / Procedimiento | Resultado Esperado |
|---|---|---|---|
| 1 | **Suite de Pruebas** | `.\venv\Scripts\python.exe -m unittest discover -s tests` | 308 tests OK, 0 skipped, 0 errores en < 10 segundos. |
| 2 | **Paridad SSOT** | `.\venv\Scripts\python.exe scripts/tools/generate_schematics.py`<br>`.\venv\Scripts\python.exe scripts/tools/generate_multimeter.py` | Generación limpia sin discrepancias en Git status. |
| 3 | **Auditoría Documental** | `.\venv\Scripts\python.exe -m unittest tests/test_documentary_parity.py` | Todas las páginas y manuales mapeados coinciden con `catalog.json`. |
| 4 | **Flujo Técnico y DMM** | `.\venv\Scripts\python.exe -m unittest tests/test_technical_workflow.py` | Carga asíncrona, getter de catálogo e inyección de fallas validadas. |
| 5 | **CERO Términos de IA** | Búsqueda por regex `\b(IA|AI|Inteligencia Artificial)\b` en `scripts/templates/index.html` | 0 coincidencias en etiquetas de texto visibles al usuario. |
| 6 | **Caché y CSP Offline** | Inspeccionar `CORE` en `sw.js` y CSP en `scripts/api.py` | No debe haber referencias a dominios externos de scripts/workers (`cdnjs`). |

---

## 5. DEUDA TÉCNICA Y ROADMAP DE MEJORAS SUGERIDAS

1. **Centralización de Caché Multi-Worker (Redis)**:
   * *Estado actual:* `NOTES_CACHE_SECONDS = 5` en memoria por proceso con Gunicorn `--workers 2`.
   * *Recomendación:* Cuando el despliegue escale a múltiples réplicas o contenedores paralelos, migrar `_notes_cache` a Redis para invalidación atómica inmediata.
2. **Auto-enrutamiento Ortogonal de Cables (Manhattan / A\*)**:
   * *Estado actual:* Los vértices de giro de cables SVG se calculan con coordenadas de puntos estáticas.
   * *Recomendación:* Implementar un algoritmo ortogonal ligero que calcule automáticamente los giros de 90° entre pines para facilitar la incorporación masiva de nuevos esquemas sin trazar vértices manualmente.
3. **Internacionalización de Filtros de Circuito**:
   * *Estado actual:* Las palabras clave `POTENCIA` y `CONTROL` en `buscarEnEsquema` están en español.
   * *Recomendación:* Mapear los filtros de tipo de cable mediante un diccionario configurable si se habilita soporte multi-idioma.
4. **Sincronización Dinámica de Planos**:
   * *Estado actual:* Los esquemas se distribuyen mediante el archivo estático compilado `circuit_schematics.json`.
   * *Recomendación:* Habilitar actualización diferencial de esquemas vía Supabase guardando versiones revisadas en IndexedDB.

---
*Fin del Dossier Técnico — Documento listo para transferencia y auditoría.*
