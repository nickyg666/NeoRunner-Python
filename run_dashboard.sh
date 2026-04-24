#!/bin/bash
# Dashboard runner with gunicorn for production
cd /home/host/neorunner
exec gunicorn --bind 0.0.0.0:8000 --workers 2 --threads 2 "dashboard:app"