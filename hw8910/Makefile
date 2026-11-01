PYTHON ?= .venv/bin/python
.PHONY: check check-negative prove experiments fetch-model prepare-real release serve stop benchmark
check:
	$(PYTHON) scripts/check_fingerprints.py
	$(PYTHON) -m compileall -q release.py lab.py service.py src scripts tests
	$(PYTHON) -m unittest discover -s tests -v
	cd ../hw67 && ../hw8910/$(PYTHON) -m unittest discover -s tests -p 'test_*.py' -v

check-negative:
	$(PYTHON) scripts/check_negative_ci.py

prove:
	$(PYTHON) scripts/prove_regressions.py

experiments:
	$(PYTHON) scripts/demonstrate.py

fetch-model:
	$(PYTHON) scripts/fetch_model.py

prepare-real:
	$(PYTHON) -m src.model_release prepare

release:
	$(PYTHON) -m src.pipeline --workspace .runtime/real --manifest manifest-model.json --report release-report.json

serve:
	bash scripts/start_service.sh

stop:
	systemctl --user stop mlops-hw8910-serving.service

benchmark:
	$(PYTHON) scripts/benchmark.py
