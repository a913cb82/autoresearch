#!/usr/bin/env python3
"""Score byte length; record AUTORESEARCH_SEED beside the target."""

import os
import sys
from pathlib import Path

target = Path(sys.argv[1])
target.with_name("env_seen").write_text(os.environ.get("AUTORESEARCH_SEED", "<unset>"))
print(len(target.read_bytes()))
