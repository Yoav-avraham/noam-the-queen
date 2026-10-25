# GitHub MCP Tooling

Last verified: 2026-05-18

## Purpose

Setup notes for GitHub MCP access used in development and review workflows.

## Current Configuration

Configured in `.vscode/mcp.json` as a Docker-based stdio server:

- Image: `ghcr.io/github/github-mcp-server`
- Env var passed into container: `GITHUB_PERSONAL_ACCESS_TOKEN`
- Input prompt id: `github_token`

## Prerequisites

- Docker installed and running.
- A GitHub Personal Access Token (PAT).

## Token Setup

The MCP client prompts for token input using `inputs` in `.vscode/mcp.json`:

- Input id: `github_token`
- Prompt type: `promptString`
- Password mode: enabled

When prompted, provide a PAT with the scopes you need for your workflow.

## Effective Server Command

```bash
docker run -i --rm \
  -e GITHUB_PERSONAL_ACCESS_TOKEN \
  ghcr.io/github/github-mcp-server
```

## Validation

After MCP restart, try a simple GitHub action in chat, for example:

- List open pull requests in a repository.
- Get details for a specific issue.

## Security Notes

- Do not commit PATs into repository files.
- Keep token use scoped to least privilege.
- Rotate tokens if exposure is suspected.
