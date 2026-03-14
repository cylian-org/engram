# Engram — Knowledge Base MCP Server
# Persistent knowledge base with Xapian full-text search

FROM python:3.13-alpine

WORKDIR /app

# Install Python dependencies (xapian via pip binary wheels)
COPY src/requirements.txt .
RUN pip install --no-cache-dir xapian-bindings-binary -r requirements.txt

# Copy application
COPY src/server.py src/database.py ./

# Data volume
VOLUME /knowledge

EXPOSE 8192

ENTRYPOINT ["python", "server.py"]
CMD []
