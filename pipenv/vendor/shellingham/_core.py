SHELL_NAMES = {
    'sh', 'bash', 'dash',           # Bourne.
    'csh', 'tcsh',                  # C.
    'ksh', 'zsh', 'fish',           # Common alternatives.
    'cmd', 'powershell', 'pwsh',    # Microsoft.
    'elvish', 'xonsh',              # More exotic.
}


class ShellDetectionFailure(EnvironmentError):
    pass
