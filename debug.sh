#!/usr/bin/env bash
cd "$(dirname "$0")" && exec python3 -X faulthandler debug_client.py "$@"
