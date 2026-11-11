``pipenv install -r <url>`` now imports the downloaded requirements file.
The temporary file was deleted before it was read,
and on Windows the download could not open it.
