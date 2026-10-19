.PHONY: install test lint web run clean

install:
	cd backend && pip install -e ".[dev]"
	cd frontend && npm install

test:
	cd backend && python -m unittest discover -s tests -t . -v

lint:
	cd backend && ruff check . && mypy taxng
	cd frontend && npm run typecheck

web:
	cd frontend && npm run build

run:
	cd backend && python -m taxng

clean:
	rm -rf frontend/dist data
