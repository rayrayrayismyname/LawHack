"""正式部署的進入點：gunicorn -c deploy/gunicorn.conf.py wsgi:app"""
from web.app import app  # noqa: F401
