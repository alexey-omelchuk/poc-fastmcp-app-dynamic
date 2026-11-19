# Servidor FastMCP – exploración de formularios dinámicos
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OT_DB_PATH=/app/data/ordenes.db
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 # Deno solo se usa en el experimento opcional GENERATIVE_UI=1 (sandbox Pyodide)
 && pip install --no-cache-dir deno==2.9.8
COPY server.py db.py catalogo.py formularios.py ./
COPY formularios ./formularios
COPY scripts ./scripts
EXPOSE 8000 8090
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import socket; socket.create_connection(('localhost', 8000), 3)" || exit 1
CMD ["python", "server.py"]
