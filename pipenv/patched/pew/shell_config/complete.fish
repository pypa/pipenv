set pew pew


function __pew_needs_command
    set cmd (commandline -opc)
    if [ (count $cmd) -eq 1 -a $cmd[1] = "$pew" ]
        return 0
    end
    return 1
end



function __pew_list_envs
    eval "$pew ls" | tr " " "\n"
end

function __pew_using_command
    set cmd (commandline -opc)
    if test (count $cmd) -gt 1
        if test $argv[1] = $cmd[2]
            return 0
        end
    end
    return 1
end


#### new
complete -f -c $pew -n '__pew_needs_command' -a new -d 'Create a new environment'
complete -f -c $pew -n '__pew_using_command new' -s h -d 'Show help'
complete -f -c $pew -n '__pew_using_command new' -s p -l python -d 'Python executable'
complete -f -c $pew -n '__pew_using_command new' -s i -d 'Install a package after the environment is created'
complete -f -c $pew -n '__pew_using_command new' -s a -a '(__fish_complete_directories (commandline -ct))' -d 'Project directory to associate'
complete -f -c $pew -n '__pew_using_command new' -s r -d 'Pip requirements file'


#### workon
complete -f -c $pew -n '__pew_needs_command' -a workon -d 'Activates an existing virtual environment'
complete -f -c $pew -n '__pew_using_command workon' -a '(__pew_list_envs)' -d 'Virtual env'

#### mktmpenv
complete -f -c $pew -n '__pew_needs_command' -a mktmpenv -d 'Create a temporary virtualenv'
complete -f -c $pew -n '__pew_using_command mktmpenv' -s h -d 'Show help'
complete -f -c $pew -n '__pew_using_command mktmpenv' -s p -l python -d 'Python executable'
complete -f -c $pew -n '__pew_using_command mktmpenv' -s i -d 'Install a package after the environment is created'
complete -f -c $pew -n '__pew_using_command mktmpenv' -s a -d 'Project directory to associate'
complete -f -c $pew -n '__pew_using_command mktmpenv' -s r -d 'Pip requirements file'

#### ls
complete -f -c $pew -n '__pew_needs_command' -a ls -d 'List all existing virtual environments'
complete -f -c $pew -n '__pew_using_command ls' -s l -l long -d 'Verbose ls'
complete -f -c $pew -n '__pew_using_command ls' -s b -l brief -d 'One line ls'

#### show
complete -f -c $pew -n '__pew_needs_command' -a show -d 'Show'
complete -f -c $pew -n '__pew_using_command show' -a '(__pew_list_envs)' -d 'Virtual env'

#### rm
complete -f -c $pew -n '__pew_needs_command' -a rm -d 'Remove one or more environments'
complete -f -c $pew -n '__pew_using_command rm' -a '(__pew_list_envs)' -d 'Virtual env'

#### cp
complete -f -c $pew -n '__pew_needs_command' -a cp -d 'Duplicate an existing virtualenv environment'

#### sitepackages_dir
complete -f -c $pew -n '__pew_needs_command' -a sitepackages_dir -d 'Location of the currently active site-packages'

#### lssitepackages
complete -f -c $pew -n '__pew_needs_command' -a lssitepackages -d 'List currently active site-packages'


#### add
complete -f -c $pew -n '__pew_needs_command' -a add -d 'Adds the specified directories'
complete -f -c $pew -n '__pew_using_command add' -s h -d 'Show help'
complete -f -c $pew -n '__pew_using_command add' -s d -d 'Removes previously added directiories'

#### toggleglobalsitepackages
complete -f -c $pew -n '__pew_needs_command' -a toggleglobalsitepackages -d 'Active virtualenv can access global site-packages'

#### mkproject
complete -f -c $pew -n '__pew_needs_command' -a mkproject -d 'Create a new environment with a project directory'
complete -f -c $pew -n '__pew_using_command mkproject' -s h -d 'Show help'
complete -f -c $pew -n '__pew_using_command mkproject' -s p -l python -d 'Python executable'
complete -f -c $pew -n '__pew_using_command mkproject' -s i -d 'Install a package after the environment is created'
complete -f -c $pew -n '__pew_using_command mkproject' -s a -d 'Project directory to associate'
complete -f -c $pew -n '__pew_using_command mkproject' -s r -d 'Pip requirements file'
complete -f -c $pew -n '__pew_using_command mkproject' -s t -d 'Apply templates'
complete -f -c $pew -n '__pew_using_command mkproject' -s l -l list -d 'List available templates'


#### setproject
complete -f -c $pew -n '__pew_needs_command' -a setproject -d 'Bind an existing virtualenv to an existing project'

#### version
complete -f -c $pew -n '__pew_needs_command' -a version -d 'Prints current version'

#### wipeenv
complete -f -c $pew -n '__pew_needs_command' -a wipeenv -d 'Remove all installed packages from a virtualenv'
complete -f -c $pew -n '__pew_using_command workon' -a '(__pew_list_envs)' -d 'Virtual env'

#### restore
complete -f -c $pew -n '__pew_needs_command' -a restore -d 'Try to restore a broken virtualenv'
complete -f -c $pew -n '__pew_using_command workon' -a '(__pew_list_envs)' -d 'Virtual env'

#### rename
complete -f -c $pew -n '__pew_needs_command' -a rename -d 'Rename a virtualenv'

#### install
complete -f -c $pew -n '__pew_needs_command' -a install -d 'Use Pythonz to download and build a Python vm'

#### list_pythons
complete -f -c $pew -n '__pew_needs_command' -a list_pythons -d 'List the pythons installed by Pythonz'

#### locate_python
complete -f -c $pew -n '__pew_needs_command' -a locate_python -d 'Locate the path for the python version installed by Pythonz'
