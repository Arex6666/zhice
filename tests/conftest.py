"""保证测试无论从哪个目录运行，相对路径（services/、tests/fixtures/）都成立。"""
import os
import pathlib

# 仓库根目录 = 本文件(tests/conftest.py)的上一级
os.chdir(pathlib.Path(__file__).resolve().parent.parent)
