import os
import sys

# Inject vendored directory into system path.
v_path = os.path.abspath(os.path.sep.join([os.path.dirname(os.path.realpath(__file__)), '_vendored']))
sys.path.insert(0, v_path)
