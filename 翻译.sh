#!/bin/bash
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8
python extract_story.py "$@"
