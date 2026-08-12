"""Filesystem layout for the project."""
from __future__ import annotations

import os

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(PACKAGE_DIR)

DATA_DIR = os.path.join(ROOT_DIR, "data")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
ARCHIVE_DIR = os.path.join(DATA_DIR, "archive")
SITE_DIR = os.path.join(ROOT_DIR, "site")

TEMPLATE_DIR = os.path.join(PACKAGE_DIR, "render", "templates")
STATIC_DIR = os.path.join(PACKAGE_DIR, "render", "static")

for _directory in (DATA_DIR, CACHE_DIR, ARCHIVE_DIR, SITE_DIR):
    os.makedirs(_directory, exist_ok=True)
