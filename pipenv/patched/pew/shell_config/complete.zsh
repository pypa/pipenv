#compdef pew

_pew_list_venvs () {
    local expl
    local -a venvs

    venvs=(${(f)"$(_call_program venvs pew ls | tr " " "\n" 2>/dev/null)"})
    _wanted venvs expl 'virtual envs' compadd -a venvs
}


local curcontext="$curcontext" state line
typeset -A opt_args

_arguments -C \
    ':subcommand:->subcommand' \
    '*::option:->option'

case $state in
    (subcommand)
        local -a subcommands
        subcommands=(
            'add:Add directories to python path of active virtualenv'
            'cp:Duplicate the named virtualenv to make a new one'
            'inall:Run a command in each virtualenv:command'
            'install:Use Pythonz to download and build the specified Python version'
            'list_pythons:List the pythons installed by Pythonz (or all the installable ones)'
            'locate_python:Locate the path for the python version installed by Pythonz'
            'ls:List all existing virtual environments'
            'lssitepackages:List currently active site-packages'
            'mkproject:Create environment with an associated project directory'
            'mktmpenv:Create a temporary virtualenv'
            'new:Create a new environment'
            'rename:Rename a virtualenv'
            'restore:Try to restore a broken virtualenv by reinstalling the same python version on top of it'
            'rm:Remove one or more environments'
            'setproject:Bind an existing virtualenv to an existing project directory'
            'show:Display currently active virtualenv'
            'sitepackages_dir:Location of the currently active site-packages'
            'toggleglobalsitepackages:Toggle access to global site-packages for current virtualenv'
            'wipeenv:Remove all installed packages from current env'
            'workon:Activates an existing virtual environment'
        )
        _describe -t commands 'pew subcommands' subcommands
    ;;

    (option)
        local -a new_env_options
        new_env_options=(
            '-h[Show help]'
            '-p[Python executable]:python:_command_names'
            '*-i[Install a package after the environment is created]:package name'
            '-a[Project directory to associate]:project directory:_path_files -/'
            '-r[Pip requirements file]:requirements file:_files'
        )

        case "$line[1]" in
            (mktmpenv)
                _arguments \
                    $new_env_options
            ;;
            (new)
                _arguments \
                    $new_env_options \
                    '1:new env name'
            ;;
            (mkproject)
                _arguments \
                    $new_env_options \
                    '*-t[Apply templates]' \
                    '-l[List available templates]' \
                    '1:new env name'
            ;;

            (ls)
                _arguments \
                    '(-l --long)--long[Verbose ls]' \
                    '(-b --brief)--brief[One line ls]'
            ;;
            (inall)
                _arguments \
                    '*:command'
            ;;

            (show|workon|rm|wipeenv|restore)
                _arguments \
                    '1:virtual env:_pew_list_venvs'
            ;;
            (cp)
                _arguments \
                    '1:virtual env:_pew_list_venvs' \
                    '2:new env name'
            ;;

            (add)
                _arguments \
                    '-h[Show help]' \
                    '-d[Removes previously added directories]' \
                    '*: :_directories -/'
            ;;
            (setproject)
                _arguments \
                    '1:virtual env:_pew_list_venvs' \
                    '*:project directory:_directories -/'
            ;;
        esac
esac
