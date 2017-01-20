import delegator
import click
import crayons


def ensure_latest_pip():

    # Ensure that pip is installed.
    c = delegator.run('pip install pip')

    # Check if version is out of date.
    if 'however' in c.err:
        # If version is out of date, update.
        print crayons.yellow('Pip is out of date... updating to latest.')
        c = delegator.run('pip install pip --upgrade', block=False)
        print crayons.blue(c.out)

def ensure_virtualenv():
    c = delegator.run('pip install virtualenv')
    print c.out


@click.command()
def main():
    # Ensure that pip is installed and up-to-date.
    ensure_latest_pip()

    # Ensure that virtualenv is installed.
    ensure_virtualenv()

if __name__ == '__main__':
    main()