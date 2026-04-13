"""Gunicorn configuration for development."""

bind = "0.0.0.0:8000"

# Number of worker processes. For dev, 2 is enough.
workers = 2

# Reload workers when source code changes (development only).
reload = True

# Log to stdout/stderr so Docker captures them.
accesslog = "-"
errorlog = "-"
loglevel = "info"

# Timeout (seconds). Increase if you have slow admin operations.
timeout = 120
