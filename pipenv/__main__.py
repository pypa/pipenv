import os

if __name__ == '__main__':
    pipenv_complete = os.environ.get("_PIPENV_COMPLETE")
    if pipenv_complete:
        import click_completion
        click_completion._shellcomplete(None, "pipenv")
    else:
        from .cli import cli
        cli()
