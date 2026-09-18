# Matriz de trazabilidad técnica SOLVI

Esta matriz separa una afirmación publicable de una asociación inferida. Una afirmación canónica debe apuntar a un manual, una página física y un extracto verificable del corpus local. Si no existe esa evidencia, el diagnóstico queda bloqueado como **Sin correlación documentada**.

## Estados

- `verified_text`: el identificador o afirmación aparece explícitamente en el extracto.
- `verified_voltage_not_label`: el manual verifica el valor y su función, pero no necesariamente la etiqueta de punto de prueba usada por la aplicación.
- `runtime_verified`: comportamiento comprobado en el código; no es una cita de manual.

## Fuentes y páginas

`data/documentary_traceability.json` contiene la fuente estructurada. `data/search/catalog.json` conserva `pages` como páginas indexadas para búsqueda y añade `physical_pages` como total físico del PDF raíz. No deben confundirse ambos valores: los índices pueden omitir portada, separadores o páginas sin texto.

## Regla de publicación

No se deben mostrar PCB, interlocks, tensiones, conectores, puntos de prueba ni páginas como canónicos cuando la matriz no contenga una entrada verificable. En particular, TP100 se mantiene como identificador operativo del catálogo, pero la cita de -320 V DC se atribuye a la evidencia funcional de dosimetría de la página 43, no a una etiqueta textual TP100.

La matriz es deliberadamente pequeña y auditable. Cada nueva afirmación técnica debe añadir primero su fila, revisar el PDF y el extracto, y después incorporarse a `circuit_data.py`, `multimeter_service.py` o los datos equivalentes.
