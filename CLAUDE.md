# Engram — Knowledge Base MCP Server

## Conventions

- Source de vérité = fichiers Markdown. L'index Xapian est un cache reconstituable.
- Thread safety : un seul Xapian writer
- Pattern identique à mcp-ssh (FastMCP, argparse, file-only logging)
- `python3-xapian` via apt (accessible via `--system-site-packages`), `mcp` via pip en venv

## Usage

### Rôle

Engram est la **base de savoir principale** de Claude. Tout savoir opérationnel durable et réutilisable y est stocké.

### Granularité

**Un document = une information complète et atomique.** Autosuffisant mais focalisé sur un seul sujet.

### Quand stocker

- Diagnostic résolu (root cause + fix)
- Procédure exécutée pour la première fois
- Décision d'architecture avec son "pourquoi"
- Info infra découverte en cours de travail

### Quand NE PAS stocker

- Info déjà dans CLAUDE.md ou MEMORY.md
- Info dérivable du code ou de git
- Détails éphémères de la conversation en cours

### Frontière avec MEMORY.md

| MEMORY.md | Engram |
|-----------|--------|
| Feedback comportemental | Savoir opérationnel |
| Règles process | Procédures, diagnostics |
| Références externes | Architecture, décisions techniques |
| Profil utilisateur | Info infra, déploiement |
