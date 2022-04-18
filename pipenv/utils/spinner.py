import contextlib


@contextlib.contextmanager
def create_spinner(text, setting, nospin=None, spinner_name=None):
    from pipenv.vendor.vistir import spin
    from pipenv.vendor.vistir.misc import fs_str

    if not spinner_name:
        spinner_name = setting.PIPENV_SPINNER
    if nospin is None:
        nospin = setting.PIPENV_NOSPIN
    with spin.create_spinner(
        spinner_name=spinner_name,
        start_text=fs_str(text),
        nospin=nospin,
        write_to_stdout=False,
    ) as sp:
        yield sp
