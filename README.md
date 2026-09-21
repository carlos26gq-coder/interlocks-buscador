# SOLVI — Buscador técnico online y offline

SOLVI permite buscar texto dentro de manuales técnicos, abrir la página correspondiente del PDF en Cloudflare R2, guardar apuntes en Supabase y relacionar varios códigos o síntomas con evidencia de los manuales.

La consulta de manuales y el diagnóstico no requieren cuenta ni contraseña. La clave administrativa se usa únicamente para editar/eliminar apuntes y consultar el panel administrativo.

## Arquitectura

- **Online:** Flask utiliza un índice invertido construido al iniciar el servidor. `/search` ofrece resultados paginados y `/diagnose` combina varios síntomas.
- **Offline:** un Web Worker carga los fragmentos compactos de `data/search/`, crea su índice fuera del hilo visual y ejecuta la misma búsqueda localmente.
- **PWA:** el service worker guarda la aplicación y el catálogo; los fragmentos de manuales se descargan y cachean al realizar una búsqueda que los necesita. Los PDF permanecen en Cloudflare R2 y requieren conexión, salvo que el usuario los haya descargado.
- **PDF offline:** no se precargan los 19 manuales completos; cada PDF queda disponible sin conexión únicamente después de una descarga explícita y caché local.
- **Registro de mediciones:** el módulo recibe lecturas manuales tomadas por personal autorizado. No conecta instrumentos, no inyecta tensión/corriente ni simula fallas. Solo publica registros con valor, ubicación y evidencia trazables; si el manual no da un rango de aceptación, muestra la comparación como referencia sin OK/FALLA.
- **Trazabilidad:** las afirmaciones técnicas publicables se registran en `data/documentary_traceability.json` con manual, página y extracto.
- **Evidencia documental:** `data/documentary_traceability.json` mantiene afirmaciones verificables con manual, página física y extracto. SOLVI presenta resultados como referencias documentales; no publica rutas de cableado ni valores de medición inferidos.
- **Apuntes:** Supabase es la fuente compartida. Las notas nuevas creadas sin conexión quedan en una cola local y se eliminan de la cola solamente después de una respuesta exitosa del servidor.

## Variables de entorno

Configurar en Render, nunca dentro del repositorio:

```text
ADMIN_PASSWORD=...
R2_PUBLIC_URL=https://...r2.dev
SUPABASE_URL=https://...supabase.co
SUPABASE_KEY=clave_service_role_solo_en_Render
```

La tabla `notes` debe aceptar las columnas `id` (UUID), `title` (texto), `text` (texto) y `tags` (array de texto o JSON compatible). Revisar las políticas RLS: la API controla edición y eliminación mediante `ADMIN_PASSWORD`, pero la clave utilizada por el servidor también debe tener los permisos mínimos necesarios.

La migración reproducible está en `supabase/migrations/001_notes_rls.sql`. Activa RLS y bloquea el acceso directo de `anon`/`authenticated`; Render debe usar una clave `service_role` protegida. En despliegues con varios workers configure `RATELIMIT_STORAGE_URI` y `NOTES_CACHE_REDIS_URL` apuntando al mismo Redis; así los límites y la caché de apuntes no se dividen por proceso.

## Añadir o actualizar un manual

1. Colocar el PDF en `manuals/`. Su nombre debe coincidir con el que se subirá a Cloudflare R2.
2. Extraer el texto:

   ```powershell
   python scripts/extract_pages.py --pdf "manuals/nombre del manual.pdf"
   ```

3. Regenerar los índices online y offline:

   ```powershell
   python scripts/build_index.py
   ```

4. Revisar `data/extraction_report.json`. Las páginas listadas en `pages_without_text` contienen imágenes o diagramas sin una capa de texto utilizable y requieren OCR o revisión manual.
5. Subir el PDF a R2 con exactamente el nombre `<manual>.pdf`.
6. Ejecutar pruebas, agregar los cambios a Git y desplegar.

El catálogo y los nombres con hash se generan automáticamente. Al cambiar un solo manual, el navegador descarga el fragmento nuevo de ese manual y conserva el resto.

## Añadir una medición documentada

No agregue un TP, tolerancia, voltaje, corriente, inyección o interpretación de falla por analogía. Primero incorpore cada afirmación a `data/documentary_traceability.json` con manual, página física, extracto y estado `verified_text`. Después cree el registro único en `data/verified_measurement_catalog.json`, enlazando todos sus `citations` y usando `evaluation_policy: "reference_only"` salvo que el manual publique expresamente el rango y el contexto de aceptación. El catálogo se precachea para uso offline y también alimenta la API; no duplique valores en JavaScript o Python.

## Añadir una ruta o referencia documentada

No se deben inferir conexiones físicas a partir de coocurrencias en el índice. Toda conclusión mostrada debe poder remitirse a una entrada de `data/documentary_traceability.json` con manual, página física, extracto y estado verificable. Si una hoja únicamente etiqueta elementos, se presenta como referencia documental, sin pasos dirigidos ni efectos de falla inferidos.

## Pruebas y validación

Las pruebas se versionan en GitHub y funcionan como puerta de calidad antes del
despliegue. Para preparar un entorno local completo:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

El bootstrap reproducible valida Python 3.12, instala las dependencias fijadas
y ejecuta `pip check`:

```powershell
$env:SOLVI_PYTHON312 = "C:\ruta\a\python312\python.exe"
.\scripts\bootstrap_local.ps1 -VenvPath .venv-solvi312
```

Ejecutar la suite:

```powershell
python -m unittest discover -s tests -v
```

Validaciones adicionales:

```powershell
node --check scripts/static/app.js
node --check scripts/static/search-worker.js
node --check sw.js
```

El flujo real de navegador, DOM, Service Worker y registro de medición usa Playwright:

```powershell
npm install
npx playwright install chromium
$env:SOLVI_BASE_URL = "http://127.0.0.1:5000"
npm run test:browser
```

La prueba no necesita credenciales reales de Supabase, Redis o R2; valida sus
contratos locales. Los binarios de Chromium y los PDFs permanecen fuera de Git.

### Integración GitHub → Render

GitHub Actions ejecuta la suite completa y las validaciones de sintaxis. Render
usa `autoDeployTrigger: checksPass`, por lo que un commit con checks fallidos no
se despliega automáticamente.

El `buildFilter` de `render.yaml` solo dispara un deploy cuando cambian archivos
de runtime (`scripts/`, `data/`, dependencias o assets raíz). Un cambio exclusivo
en `tests/`, informes o documentación permanece versionado, pero no consume un
despliegue. En producción Render instala únicamente `requirements.txt`; las
herramientas de `requirements-dev.txt` no se instalan ni se ejecutan.

## Alcance del diagnóstico

El diagnóstico no genera conocimiento externo: ordena páginas según la coincidencia de códigos, interlocks, mensajes y observaciones, y muestra la evidencia encontrada. El porcentaje es una coincidencia relativa entre los resultados, no una probabilidad clínica ni una confirmación de falla. Siempre se deben seguir los procedimientos de seguridad del fabricante.

`pdfplumber` analiza el texto incorporado en cada PDF. Un diagrama vectorial puede aportar sus etiquetas si contiene texto; una imagen escaneada sin OCR no puede ser interpretada visualmente por este proceso.
