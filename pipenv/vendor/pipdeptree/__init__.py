import os
import sys

pardir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# for finding pipdeptree itself
sys.path.append(pardir)
# for finding stuff in vendor and patched
sys.path.append(os.path.dirname(os.path.dirname(pardir)))

