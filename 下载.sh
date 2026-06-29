#!/bin/bash
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8
python fetch_event_stories.py "$@"
