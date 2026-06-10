#!/usr/bin/env bash
# setup-corporate-auth.sh
#
# One-time setup: authenticates the corporate Anthropic account for corp-data access.
# Run this once per machine before using /corp-data or /morning-briefing.
#
# Usage: bash scripts/setup-corporate-auth.sh
#
# Reads CORPORATE_EMAIL from .env (preferred) or prompts if not set.
# Copy .env.example to .env and set CORPORATE_EMAIL before running.

set -euo pipefail

CORPORATE_CONFIG_DIR="$HOME/.claude-corporate"

# Load .env if present
if [[ -f ".env" ]]; then
  # shellcheck disable=SC2046
  export $(grep -v '^#' .env | grep -v '^$' | xargs)
fi

CORPORATE_EMAIL="${CORPORATE_EMAIL:-${1:-}}"

echo ""
echo "TbAI OS — Corporate Auth Setup"
echo "================================"
echo ""

if [[ -z "$CORPORATE_EMAIL" ]]; then
  echo "CORPORATE_EMAIL not found in .env."
  echo ""
  echo "To set it permanently: add CORPORATE_EMAIL=you@yourcompany.com to your .env file."
  echo "(Copy .env.example to .env to get started.)"
  echo ""
  echo "Or enter your corporate email now (one-time, not saved):"
  read -r CORPORATE_EMAIL
fi

echo ""
echo "Setting up corporate auth for: $CORPORATE_EMAIL"
echo "Config directory: $CORPORATE_CONFIG_DIR"
echo ""

# Create the config directory if it doesn't exist
mkdir -p "$CORPORATE_CONFIG_DIR"

# Check if already configured
if [[ -f "$CORPORATE_CONFIG_DIR/.credentials.json" ]]; then
  echo "Corporate config already exists at $CORPORATE_CONFIG_DIR"
  echo "To re-authenticate, delete $CORPORATE_CONFIG_DIR/.credentials.json and run this script again."
  echo ""
  read -r -p "Re-authenticate anyway? (y/N): " confirm
  if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "Setup cancelled."
    exit 0
  fi
fi

echo ""
echo "Opening browser for corporate authentication..."
echo "Sign in with: $CORPORATE_EMAIL"
echo ""

# Run the claude auth login with the corporate config directory
CLAUDE_CONFIG_DIR="$CORPORATE_CONFIG_DIR" claude auth login

echo ""
echo "Authentication complete."
echo ""

# Verify the credentials file was created
if [[ -f "$CORPORATE_CONFIG_DIR/.credentials.json" ]]; then
  echo "✓ Corporate auth configured at: $CORPORATE_CONFIG_DIR"
  echo ""
  echo "You can now use /corp-data and /morning-briefing in your Claude Code sessions."
  echo ""
  echo "Test with:"
  echo "  CLAUDE_CODE_USE_VERTEX=\"\" ANTHROPIC_VERTEX_PROJECT_ID=\"\" CLAUDE_CONFIG_DIR=\"$CORPORATE_CONFIG_DIR\" claude -p \"Hello\" --model sonnet --print --no-session-persistence --dangerously-skip-permissions"
else
  echo "Warning: credentials file not found at expected location."
  echo "Authentication may not have completed. Try running this script again."
  exit 1
fi
