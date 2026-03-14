# Engram — Knowledge Base MCP Server

## Architecture

- **server.py** : FastMCP server (stdio transport) — 7 MCP tools (remember, recall, search, list, tags, forget, rebuild)
- **database.py** : Classe KnowledgeBase — fichiers Markdown + index Xapian
- **Données** : `/opt/knowledge/entries/` (MD + frontmatter YAML)
- **Index** : `/opt/knowledge/index/fr/` (Xapian, stemmer français)
- **Log** : stderr (par défaut) ou `--log-file <path>`

## Conventions

- Source de vérité = fichiers Markdown. L'index Xapian est un cache reconstituable.
- Chaque entrée = `<uuid>.md` avec frontmatter `id`, `title`, `tags`
- Tags normalisés : lowercase, triés, dédupliqués
- Thread safety : Xapian WritableDatabase = un seul writer
- Pattern identique à mcp-ssh (FastMCP, argparse, file-only logging)

## Dépendances

- `python3-xapian` (apt, accessible via `--system-site-packages` dans le venv)
- `mcp>=1.20.0` (pip dans le venv)

## Usage — Conventions

### Rôle

KB est la **base de savoir principale** de Claude. Tout savoir opérationnel durable et réutilisable y est stocké.

### Alimentation

- **Implicite** : Claude stocke automatiquement après un diagnostic, une procédure, une découverte infra, une décision d'architecture. Signalé brièvement : "→ KB: [titre]"
- **Explicite** : sur demande de l'utilisateur

### Granularité

**Un document = une information complète et atomique.** Autosuffisant (pas besoin de chercher ailleurs) mais focalisé sur un seul sujet. La recherche assemble les pièces.

### Liens entre articles

Convention Markdown standard : `[Titre de l'article](kb://<uuid>)` dans le contenu.

### Quand stocker

- Diagnostic résolu (root cause + fix)
- Procédure exécutée pour la première fois
- Décision d'architecture avec son "pourquoi"
- Info infra découverte en cours de travail

### Quand NE PAS stocker

- Info déjà dans CLAUDE.md ou MEMORY.md (feedback/préférences)
- Info dérivable du code ou de git
- Détails éphémères de la conversation en cours

### Cycle de vie

- Maintenance au fil de l'eau : `remember` avec `entry_id` quand une info est revalidée
- Pas d'expiration automatique

### Frontière avec MEMORY.md

| MEMORY.md | KB |
|-----------|-----|
| Feedback comportemental | Savoir opérationnel |
| Règles process | Procédures, diagnostics |
| Références externes | Architecture, décisions techniques |
| Profil utilisateur | Info infra, déploiement |
