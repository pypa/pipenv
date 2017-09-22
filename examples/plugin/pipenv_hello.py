import click


@click.command()
def main():
    """The Hello Plugin"""
    click.echo("Hello from pipenv plugin")
