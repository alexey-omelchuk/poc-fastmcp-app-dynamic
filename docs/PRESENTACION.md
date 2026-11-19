# Cómo presentar la exploración (≈7 min)

## La idea en una frase
> El formulario ya no está programado: **lo diseña el agente** con una definición que vive en el MCP, y el
> servidor se asegura de que lo que se guarda es siempre fiable.

## Antes de la reunión
```bash
cd "/mnt/c/Users/Alexey7123/Downloads/Nunsys/fastMCP - dynamic"
docker compose --profile visor down && rm -f data/ordenes.db && docker compose --profile visor up -d
```
Deja abiertos http://localhost:8011, una terminal y `formularios/alta_ot.json` en un editor. Ten a mano el vídeo `docs/demo.mp4`.

## Guion
1. **Contexto (1 min).** «En la v1 el formulario era fijo. Nos pedisteis que lo generara el LLM a partir de una
   descripción en el MCP, guardando igual. Esto es la exploración.»
2. **Enseña la definición (30 s).** Abre `formularios/alta_ot.json`: campos, obligatorios, opciones e instrucciones.
   «Esto es lo único que define el formulario. No es código.»
3. **Demo (3-4 min)** con los botones del chat:
   - **1 · OT del correo** → despliega «Usado abrir_formulario» para enseñar el JSON que diseñó el LLM. Crear orden dos veces → una sola OT.
   - **2 · Formulario mínimo** → solo equipo y avería.
   - **3 · Con datos extra** → aparecen turno, equipo parado y contacto. Se guardan en `datos_extra`.
   - **4 · Saltarse un obligatorio** → aviso amarillo de la capa de seguridad. Sin activo no se guarda.
   - Terminal: `docker compose exec mcp python scripts/ver_db.py`. Misma tabla y extras en JSON.
4. **(Opcional, 1 min) Campo nuevo sin código.** Añade `horas_estimadas` al JSON, `docker compose restart mcp` y
   pide otra orden mencionando las horas.
5. **Conclusión (1 min).** Tabla de `docs/EXPLORACION.md`: fijo vs. declarativo vs. código. «Recomiendo el
   declarativo: es dinámico, sin código y sin ejecutar nada del LLM. El modo código está preparado como
   experimento, pero obliga a resolver el sandbox.»

## Plan B
El vídeo `docs/demo.mp4` (2 min) enseña los 5 casos.

## Preguntas probables
| Pregunta | Respuesta |
|---|---|
| ¿Se puede saltar un obligatorio por prompt? | No. El servidor lo añade al pintar y lo exige al guardar (caso 4) |
| ¿El LLM ejecuta código? | En este enfoque, no: solo envía datos de una lista cerrada de 6 tipos de campo |
| ¿Cada usuario ve el mismo formulario? | La misma definición y las mismas validaciones. La presentación puede variar; se puede fijar si se quiere |
| ¿Dónde se guardan los campos nuevos? | En la misma tabla, columna `datos_extra` (JSON) |
| ¿Cómo sé qué vio el usuario? | Se guarda el formulario mostrado con cada orden (`ver_db.py --formulario OT-DEMO-0003`) |
| ¿Y el modo en que el LLM escribe código? | Preparado (`GENERATIVE_UI=1`), sin probar aquí; ver los riesgos en EXPLORACION.md |
