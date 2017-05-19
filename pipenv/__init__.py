# |~~\'    |~~
# |__/||~~\|--|/~\\  /
# |   ||__/|__|   |\/
#      |

import os
import sys

# Inject vendored directory into system path.
v_path = os.path.sep.join([os.path.dirname(os.path.realpath(__file__)), 'vendor'])
sys.path.insert(1, v_path)


from .cli import cli

if __name__ == '__main__':
    cli()
