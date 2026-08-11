# SOLVI — Buscador técnico online y offline

SOLVI permite buscar texto dentro de manuales técnicos, abrir la página correspondiente del PDF en Cloudflare R2, guardar apuntes en Supabase y relacionar varios códigos o síntomas con evidencia de los manuales.

La consulta de manuales y el diagnóstico no requieren cuenta ni contraseña. La clave administrativa se usa únicamente para editar/eliminar apuntes y consultar el panel administrativo.

## Arquitectura

- **Online:** Flask utiliza un índice invertido construido al iniciar el servidor. `/search` ofrece resultados paginados y `/diagnose` combina varios síntomas.
- **Offline:** un Web Worker carga los fragmentos compactos de `data/search/`, crea su índice fuera del hilo visual y ejecuta la misma búsqueda localmente.
- **PWA:** el service worker guarda la aplicación, el catálogo y todos los fragmentos de manuales. Los PDF permanecen en Cloudflare R2 y requieren conexión, salvo que el usuario los haya descargado.
- **Apuntes:** Supabase es la fuente compartida. Las notas nuevas creadas sin conexión quedan en una cola local y se eliminan de la cola solamente después de una respuesta exitosa del servidor.

## Variables de entorno

Configurar en Render, nunca dentro del repositorio:

```text
ADMIN_PASSWORD=...
R2_PUBLIC_URL=https://...r2.dev
SUPABASE_URL=https://...supabase.co
SUPABASE_KEY=clave_publicable_o_anon
```

La tabla `notes` debe aceptar las columnas `id` (UUID), `title` (texto), `text` (texto) y `tags` (array de texto o JSON compatible). Revisar las políticas RLS: la API controla edición y eliminación mediante `ADMIN_PASSWORD`, pero la clave utilizada por el servidor también debe tener los permisos mínimos necesarios.

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

## Pruebas y validación

Las pruebas del motor y de los datos usan únicamente la biblioteca estándar:

```powershell
python -m unittest discover -s tests -v
```

Validaciones adicionales:

```powershell
node --check scripts/static/app.js
node --check scripts/static/search-worker.js
node --check sw.js
```

## Alcance del diagnóstico

El diagnóstico no genera conocimiento externo: ordena páginas según la coincidencia de códigos, interlocks, mensajes y observaciones, y muestra la evidencia encontrada. El porcentaje es una coincidencia relativa entre los resultados, no una probabilidad clínica ni una confirmación de falla. Siempre se deben seguir los procedimientos de seguridad del fabricante.

`pdfplumber` analiza el texto incorporado en cada PDF. Un diagrama vectorial puede aportar sus etiquetas si contiene texto; una imagen escaneada sin OCR no puede ser interpretada visualmente por este proceso.
