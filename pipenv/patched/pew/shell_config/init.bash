source "$( dirname "${BASH_SOURCE[0]}" )"/complete.bash

PS1="\[\033[01;34m\]\$(basename '$VIRTUAL_ENV')\[\e[0m\]$PS1"
