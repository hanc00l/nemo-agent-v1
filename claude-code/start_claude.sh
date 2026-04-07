#!/bin/bash

if command -v claude-trace &> /dev/null; then
    claude-trace --dangerously-skip-permissions
else
    claude --dangerously-skip-permissions
fi
