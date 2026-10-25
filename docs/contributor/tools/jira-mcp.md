# Jira MCP Tooling

Last verified: 2026-05-18

## Purpose

Setup notes for Jira MCP access used in development workflows.

## Required Environment Variables

Create a local `.env` in repo root with:
- `JIRA_URL`
- `JIRA_USERNAME`
- `JIRA_API_TOKEN`

Do not commit this file.

## Server Command

```bash
uvx mcp-atlassian --env-file .env --read-only
```

For Jira Server/Data Center, use `JIRA_PERSONAL_TOKEN` when appropriate.

## After Editing Credentials

Restart MCP servers in VS Code MCP UI.

## Validation Prompts

- Find issue by key
- Show issue summary and status
- Search open bugs assigned to current user

## Security Notes

- Keep tokens local and untracked.
- Never include live credentials in docs, commits, or logs.
