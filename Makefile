.PHONY: test test-docker

test:
	uv run pytest -m "not integration" -v

test-docker:
	docker build -t invoice-extractor-test .
	docker run --rm invoice-extractor-test
