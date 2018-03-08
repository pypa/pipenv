# Homebrew on Macs have version 1.3 of bash-completion which doesn't include
# _init_completion. This is a very minimal version of that function.
__my_init_completion()
{
    COMPREPLY=()
    _get_comp_words_by_ref cur prev words cword
}

_pew()
{
    local cur prev words cword args commands
    if declare -F _init_completions >/dev/null 2>&1; then
         _init_completion || return
    else
         __my_init_completion || return
    fi
    args="--help --python -i -a -r"
    commands="ls add mkproject rm lssitepackages cp workon new mktmpenv setproject show wipeenv sitepackages_dir inall toggleglobalsitepackages rename restore install list_pythons locate_python"

    case $prev in
        ls|show|rm|workon|cp|setproject|rename|wipeenv)
            COMPREPLY=( $(compgen -W "$(pew ls)" -- ${cur}) )
            return 0
            ;;
        inall)
            _command_offset 2
            return 0
            ;;
        mktmpenv|new)
            COMPREPLY=( $(compgen -W "${args}" -- ${cur}) )
            return 0
            ;;
        mkproject)
            COMPREPLY=( $(compgen -W "${args} -t --list" -- ${cur}) )
            return 0
            ;;
        add)
            COMPREPLY=( $(compgen -W "--help -d" -- ${cur}) )
            return 0
            ;;
    esac

    COMPREPLY=( $(compgen -W "${commands}" -- ${cur}) )

} &&
complete -o default -F _pew pew
