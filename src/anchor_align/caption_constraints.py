"""Caption constraints shared by segmentation (S5) and QC (S8).

Kept in one place so the two stages that enforce the same limits cannot
drift apart.
"""

MAX_LINES = 2
MAX_LINE_CHARS = 42
MIN_DURATION_S = 1.0
MAX_DURATION_S = 7.0
MAX_CPS = 21.0
