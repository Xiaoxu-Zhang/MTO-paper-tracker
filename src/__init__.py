#!usr/bin/env/ python
# -*- coding:utf-8 -*-
"""
@Author :Xiaoxu Zhang
@Date   :2024/12/20
"""
import sys
import os

# 获取当前文件所在的目录
current_dir = os.path.dirname(os.path.abspath(__file__))
# 将当前目录添加到 sys.path 中
if current_dir not in sys.path:
    sys.path.append(current_dir)