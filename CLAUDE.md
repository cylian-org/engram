# MCP KB — Knowledge Base MCP Server

## Architecture

- **server.py** : FastMCP server (stdio transport) — 8 MCP tools prefixed `kb_`
- **database.py** : Classe KnowledgeBase — fichiers Markdown + index Xapian
- **Données** : `/opt/knowledge/entries/` (MD + frontmatter YAML)
- **Index** : `/opt/knowledge/index/fr/` (Xapian, stemmer français)
- **Log** : `/var/log/mcp-kb.log`

## Conventions

- Source de vérité = fichiers Markdown. L'index Xapian est un cache reconstituable.
- Chaque entrée = `<uuid>.md` avec frontmatter `id`, `title`, `tags`
- Tags normalisés : lowercase, triés, dédupliqués
- Thread safety : Xapian WritableDatabase = un seul writer
- Pattern identique à mcp-ssh (FastMCP, argparse, file-only logging)

## Dépendances

- `python3-xapian` (apt, accessible via `--system-site-packages` dans le venv)
- `mcp>=1.20.0` (pip dans le venv)
