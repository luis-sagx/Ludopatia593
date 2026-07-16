#!/bin/sh
set -e
python -m app.ml.train
python -m app.seed
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --no-server-header
