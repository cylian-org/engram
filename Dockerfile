# Engram — Knowledge Base MCP Server
# Persistent knowledge base with pluggable search backends

FROM python:3.13-alpine

WORKDIR /app

# Install Python dependencies
COPY src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY src/ ./

# Non-root user
RUN addgroup -S engram && adduser -S engram -G engram
RUN mkdir -p /knowledge && chown engram:engram /knowledge
USER engram

# Default configuration (override via docker run -e or --arg)
ENV ENGRAM_DATA_PATH=/knowledge
ENV ENGRAM_BACKEND=xapian
ENV ENGRAM_LANGUAGE=en
ENV ENGRAM_TRANSPORT=stdio
ENV ENGRAM_HOST=0.0.0.0
ENV ENGRAM_PORT=8192

# Data volume
VOLUME /knowledge

EXPOSE 8192

ENTRYPOINT ["python", "server.py"]
CMD []
