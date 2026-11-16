# AlphaCourt. Run from the repository root.
PORT ?= 8787
# The deploy scripts need huggingface_hub, which is not in this environment: DEPLOY_PY is a Python that has it.
DEPLOY_PY ?= python

.PHONY: setup test web gateway vercel static-space live-space dataset

setup:
	uv sync
	cd web && npm install

test:
	uv run pytest

web:
	cd web && npm run build

gateway:
	uv run uvicorn gateway.app:app --host 127.0.0.1 --port $(PORT)

vercel:
	$(DEPLOY_PY) scripts/deploy_vercel.py

static-space:
	$(DEPLOY_PY) scripts/deploy_static_space.py

live-space:
	$(DEPLOY_PY) scripts/deploy_live_space.py all

dataset:
	$(DEPLOY_PY) scripts/deploy_dataset.py

paper:  ## Fill the result slots, check, and build paper/main.pdf (4 pages)
	python3 scripts/make_paper.py
	cd paper && tectonic --outdir . main.tex
	python3 scripts/check_paper.py
