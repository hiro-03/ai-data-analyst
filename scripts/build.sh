#!/bin/bash
set -e

echo "--- 1. Cleaning up old artifacts ---"
rm -rf package
rm -f weather-observation-api.zip
rm -f weather-fallback-api.zip

echo "--- 2. Installing runtime dependencies ---"
pip install -r requirements-runtime.txt -t package

echo "--- 2.5 Scrubbing unnecessary files ---"
rm -rf package/bin
find package -type d -name "__pycache__" -exec rm -rf {} +
find package -type d -name "*.dist-info" -exec rm -rf {} +
find package -type f -name "*.pyd" -exec rm -f {} +
find package -type f -name "*.dll" -exec rm -f {} +

echo "--- 3. Copying Lambda source code ---"
cp -r lambda/weather-observation-api/* package/
find package -type d -name "__pycache__" -exec rm -rf {} +

echo "--- 4. Creating ZIP package with 7-Zip ---"
cd package
7z a ../weather-observation-api.zip ./* > /dev/null
cd ..

rm -rf package
mkdir package
cp -r lambda/weather-fallback-api/* package/
find package -type d -name "__pycache__" -exec rm -rf {} +

cd package
7z a ../weather-fallback-api.zip ./* > /dev/null
cd ..

echo "--- Done! ---"