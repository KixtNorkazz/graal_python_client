#!/usr/bin/env bash
cd "$(dirname "$0")" && exec python3 -X faulthandler tools/debug_client.py "$@"
