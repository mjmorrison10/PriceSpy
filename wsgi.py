"""WSGI entry point for gunicorn on Render.
Point Render's start command to: gunicorn wsgi:app"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from server import app
