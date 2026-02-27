# 変数定義
export PY_VERSION := 3.9
export PACKAGE_DIR := package
export SRC_DIR := src
export ZIP_NAME := lambda_function.zip

.PHONY: help build clean test

help:
	@echo "Usage:"
	@echo "  make build   - Create a ZIP package for AWS Lambda"
	@echo "  make clean   - Remove build artifacts"
	@echo "  make test    - Run pytest"

build: clean
	@echo "Installing dependencies into $(PACKAGE_DIR)..."
	pip install -r requirements.txt -t $(PACKAGE_DIR)
	@echo "Copying source files..."
	cp -r $(SRC_DIR)/* $(PACKAGE_DIR)/
	@echo "Creating ZIP file..."
	cd $(PACKAGE_DIR) && zip -r ../$(ZIP_NAME) .
	@echo "Done: $(ZIP_NAME)"

clean:
	rm -rf $(PACKAGE_DIR)
	rm -f $(ZIP_NAME)
	find . -type d -name "__pycache__" -exec rm -rf {} +

test:
	pytest tests/