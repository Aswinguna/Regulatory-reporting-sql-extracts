.PHONY: run test clean

run:
	python -m regrep.pipeline --out build

test:
	python -m pytest

clean:
	rm -rf build .pytest_cache
