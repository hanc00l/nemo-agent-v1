#!/bin/bash
export IS_SANDBOX=1
if command -v claude-trace &> /dev/null; then
    claude-trace --dangerously-skip-permissions
else
    claude --dangerously-skip-permissions
fi
