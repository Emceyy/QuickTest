PYTHON ?= /Users/emreceylanuysal/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3

.PHONY: dev import check

dev:
	$(PYTHON) app.py

import:
	$(PYTHON) importer.py

check:
	$(PYTHON) -m py_compile app.py importer.py
	/Users/emreceylanuysal/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check static/app.js

