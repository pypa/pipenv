fpath=( ${0:a:h} "${fpath[@]}" )
compinit

function virtualenv_prompt_info() {
    if [ -n "$VIRTUAL_ENV" ]; then
        local name=$(basename $VIRTUAL_ENV)
        echo "($name) "
    fi
}
PS1="$(virtualenv_prompt_info)$PS1"

# be sure to disable promptinit if the prompt is not updated
