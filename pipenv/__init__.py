# |~~\'    |~~
# |__/||~~\|--|/~\\  /
# |   ||__/|__|   |\/
#      |

import os
import sys

# Inject vendored directory into system path.
v_path = os.path.abspath(os.path.sep.join([os.path.dirname(os.path.realpath(__file__)), 'vendor']))
sys.path.insert(0, v_path)

# Inject patched directory into system path.
v_path = os.path.abspath(os.path.sep.join([os.path.dirname(os.path.realpath(__file__)), 'patched']))
sys.path.insert(0, v_path)

if __name__ == '__main__':
    from .cli import cli
    cli()
