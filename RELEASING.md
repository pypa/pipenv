# Releasing Pipenv
The following steps are to be done when making a new release:

1.) Update the version number in __version__.py
2.) Run invoke release.generate-changelog
3.) Commit and push this to main
4.) Tag the main branch with v2022.6.28 assuming we did it today
5.) Push tag and verify pypi build works and happens
6.) Edit the release notes in github and click auto-generate the release notes button.
7.) Celebrate (edited)
