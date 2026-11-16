PYTHON := .venv/bin/python
export KUBECONFIG := $(CURDIR)/.runtime/kubeconfig
export PATH := $(CURDIR)/.tools:$(PATH)
.PHONY: setup up check check-k8s experiment-b experiment-c report down
setup:
	python3 scripts/install_tools.py
	uv sync --frozen --group dev
up:
	$(PYTHON) scripts/setup.py
check:
	$(PYTHON) -m unittest discover -s tests -p test_local.py -v
	helm lint charts/hw11
check-k8s:
	HW11_K8S=1 $(PYTHON) -m unittest discover -s tests -p test_kubernetes.py -v
experiment-b:
	$(PYTHON) scripts/experiments_b.py
experiment-c:
	$(PYTHON) scripts/experiments_c.py
report:
	$(PYTHON) scripts/footprint.py
	$(PYTHON) scripts/report.py
	$(PYTHON) scripts/audit.py
down:
	kind delete cluster --name hw11
