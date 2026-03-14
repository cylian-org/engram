# Engram — Knowledge Base MCP Server
# Persistent knowledge base with Xapian full-text search

FROM python:3.13-alpine

WORKDIR /app

# Install Python dependencies (xapian via pip binary wheels)
COPY requirements.txt .
RUN pip install --no-cache-dir xapian-bindings-binary -r requirements.txt

# Copy application
COPY server.py database.py ./

# Data volume
VOLUME /data

# Log to stderr in container mode (no file)
ENV LOG_FILE=/dev/stderr

# Default transport
ENV TRANSPORT=stdio

EXPOSE 8080

ENTRYPOINT ["python", "server.py", "--data-path", "/data"]
CMD []
