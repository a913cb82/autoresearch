#!/usr/bin/env python3
"""Fixture eval: score = file byte length."""

import sys

print(len(open(sys.argv[1], "rb").read()))
