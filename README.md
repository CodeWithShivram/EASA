# EASA — Enterprise AI Support Agent

A learning and portfolio project. The goal is an enterprise-style AI support agent: authorized employees ask questions about company knowledge and get answers grounded in approved documents, with citations and server-side access control.

> **Status: Phase 1 (Foundation and Architecture), in progress.**
> The repository is being scaffolded. **No application code exists yet**, so nothing can be installed or run.
> This is not production software. All company documents and employee data used in this project are synthetic.

## Planned structure

```
easa/
  apps/api/   FastAPI backend (Python 3.14, uv)         [not yet created]
  apps/web/   Next.js frontend (TypeScript, Tailwind)   [not yet created]
  docs/       Architecture, security and API documents  [not yet created]
  scripts/    Development and check scripts             [not yet created]
```

## Prerequisites

Verified on the development machine (Windows 11):

| Tool    | Version verified |
|---------|------------------|
| Git     | 2.55.0           |
| Node.js | 24.13.0          |
| npm     | 11.6.2           |
| Python  | 3.14.7 (`py -3.14`) |
| uv      | 0.12.9           |

Not required for Phase 1: PostgreSQL (SQLite is used initially), Ollama and Docker.

## Setup

Setup instructions will be added as each component is built and its commands are verified.

## Local data

Runtime data, including the SQLite database, is stored in `var/` directories. Git ignores these directories, as well as all `*.db` / `*.sqlite*` files and `.env` files.

## Project guide

See [CLAUDE_DEVELOPMENT_GUIDE.txt](CLAUDE_DEVELOPMENT_GUIDE.txt) for engineering standards and the phased roadmap.
