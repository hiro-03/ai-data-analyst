#!/bin/bash

# 設定
PACKAGE_DIR="package"
SRC_DIR="src"
ZIP_NAME="lambda_function.zip"

echo "--- 1. Cleaning up old artifacts ---"
rm -rf $PACKAGE_DIR
rm -f $ZIP_NAME

echo "--- 2. Installing dependencies ---"
# requirements.txt の内容を package フォルダにインストール
pip install -r requirements.txt -t $PACKAGE_DIR

echo "--- 3. Copying source code ---"
# src フォルダの中身を package フォルダにコピー
cp -r $SRC_DIR/* $PACKAGE_DIR/

echo "--- 4. Creating ZIP package ---"
# package フォルダに移動して ZIP を作成
cd $PACKAGE_DIR
zip -r ../$ZIP_NAME .
cd ..

echo "--- Done! ---"
echo "Generated: $ZIP_NAME"
