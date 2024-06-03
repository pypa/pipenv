# Pipfile & Pipfile.lock

`Pipfile` contains the specification for the project top-level requirements and any desired specifiers.
This file is managed by the developers invoking pipenv commands.
The `Pipfile` uses inline tables and the [TOML Spec](https://toml.io/en/latest#spec).

`Pipfile.lock` replaces the `requirements.txt` file used in most Python projects and adds
security benefits of tracking the packages hashes that were last locked.
This file is managed automatically through locking actions.

You should add both `Pipfile` and `Pipfile.lock` to the project's source control.

## `[pipenv]` Directives

`Pipfile` may contain a `[pipenv]` section to control the behaviour of pipenv itself. Some available settings include:

* `allow_prereleases` - Tell pipenv to install pre-release versions of a package -i.e. a version with an alpha/beta/etc. suffix, such as _1.0b1_. Equivalent to passing the `--pre` flag on the command line.
* `disable_pip_input` - Prevent pipenv from asking for input. Equivalent to the `--no-input` flag.
* `install_search_all_sources` - Allow installation of packages from an existing `Pipfile.lock` to search all defined indexes for the constrained package version and hash signatures. See [Specifying Package Indexes](indexes.md).
* `sort_pipfile` - Sort package names alphabetically inside each category. Categories will be sorted and updated on `install` and `uninstall`. This is purely cosmetic to make reading easier for humans, and has no effect on installation order or dependency resolution. Note that `Pipfile.lock` packages are always sorted alphabetically.


## Example Pipfile

Here is a simple example of a `Pipfile` and the resulting `Pipfile.lock`.

    [[source]]
    url = "https://pypi.org/simple"
    verify_ssl = true
    name = "pypi"

    [packages]
    Django = "==4.*"
    waitress = {version = "*", markers="sys_platform == 'win32'"}
    gunicorn = {version = "*", markers="sys_platform == 'linux'"}

    [dev-packages]
    pytest-cov = "==3.*"


## Example Pipfile.lock

    {
        "_meta": {
            "hash": {
                "sha256": "d09f41c21ecfb3b019ace66b61ea1174f99e8b0da0d39e70a5c1cf2363d8b88d"
            },
            "pipfile-spec": 6,
            "requires": {},
            "sources": [
                {
                    "name": "pypi",
                    "url": "https://pypi.org/simple",
                    "verify_ssl": true
                }
            ]
        },
        "default": {
            "asgiref": {
                "hashes": [
                    "sha256:71e68008da809b957b7ee4b43dbccff33d1b23519fb8344e33f049897077afac",
                    "sha256:9567dfe7bd8d3c8c892227827c41cce860b368104c3431da67a0c5a65a949506"
                ],
                "markers": "python_version >= '3.7'",
                "version": "==3.6.0"
            },
            "django": {
                "hashes": [
                    "sha256:44f714b81c5f190d9d2ddad01a532fe502fa01c4cb8faf1d081f4264ed15dcd8",
                    "sha256:f2f431e75adc40039ace496ad3b9f17227022e8b11566f4b363da44c7e44761e"
                ],
                "index": "pypi",
                "version": "==4.1.7"
            },
            "gunicorn": {
                "hashes": [
                    "sha256:9dcc4547dbb1cb284accfb15ab5667a0e5d1881cc443e0677b4882a4067a807e",
                    "sha256:e0a968b5ba15f8a328fdfd7ab1fcb5af4470c28aaf7e55df02a99bc13138e6e8"
                ],
                "index": "pypi",
                "markers": "sys_platform == 'linux'",
                "version": "==20.1.0"
            },
            "setuptools": {
                "hashes": [
                    "sha256:95f00380ef2ffa41d9bba85d95b27689d923c93dfbafed4aecd7cf988a25e012",
                    "sha256:bb6d8e508de562768f2027902929f8523932fcd1fb784e6d573d2cafac995a48"
                ],
                "markers": "python_version >= '3.7'",
                "version": "==67.3.2"
            },
            "sqlparse": {
                "hashes": [
                    "sha256:0323c0ec29cd52bceabc1b4d9d579e311f3e4961b98d174201d5622a23b85e34",
                    "sha256:69ca804846bb114d2ec380e4360a8a340db83f0ccf3afceeb1404df028f57268"
                ],
                "markers": "python_version >= '3.5'",
                "version": "==0.4.3"
            },
            "waitress": {
                "hashes": [
                    "sha256:7500c9625927c8ec60f54377d590f67b30c8e70ef4b8894214ac6e4cad233d2a",
                    "sha256:780a4082c5fbc0fde6a2fcfe5e26e6efc1e8f425730863c04085769781f51eba"
                ],
                "markers": "sys_platform == 'win32'",
                "version": "==2.1.2"
            }
        },
        "develop": {
            "attrs": {
                "hashes": [
                    "sha256:29e95c7f6778868dbd49170f98f8818f78f3dc5e0e37c0b1f474e3561b240836",
                    "sha256:c9227bfc2f01993c03f68db37d1d15c9690188323c067c641f1a35ca58185f99"
                ],
                "markers": "python_version >= '3.6'",
                "version": "==22.2.0"
            },
            "coverage": {
                "extras": [
                    "toml"
                ],
                "hashes": [
                    "sha256:04481245ef966fbd24ae9b9e537ce899ae584d521dfbe78f89cad003c38ca2ab",
                    "sha256:0c45948f613d5d18c9ec5eaa203ce06a653334cf1bd47c783a12d0dd4fd9c851",
                    "sha256:10188fe543560ec4874f974b5305cd1a8bdcfa885ee00ea3a03733464c4ca265",
                    "sha256:218fe982371ac7387304153ecd51205f14e9d731b34fb0568181abaf7b443ba0",
                    "sha256:29571503c37f2ef2138a306d23e7270687c0efb9cab4bd8038d609b5c2393a3a",
                    "sha256:2a60d6513781e87047c3e630b33b4d1e89f39836dac6e069ffee28c4786715f5",
                    "sha256:2bf1d5f2084c3932b56b962a683074a3692bce7cabd3aa023c987a2a8e7612f6",
                    "sha256:3164d31078fa9efe406e198aecd2a02d32a62fecbdef74f76dad6a46c7e48311",
                    "sha256:32df215215f3af2c1617a55dbdfb403b772d463d54d219985ac7cd3bf124cada",
                    "sha256:33d1ae9d4079e05ac4cc1ef9e20c648f5afabf1a92adfaf2ccf509c50b85717f",
                    "sha256:33ff26d0f6cc3ca8de13d14fde1ff8efe1456b53e3f0273e63cc8b3c84a063d8",
                    "sha256:38da2db80cc505a611938d8624801158e409928b136c8916cd2e203970dde4dc",
                    "sha256:3b155caf3760408d1cb903b21e6a97ad4e2bdad43cbc265e3ce0afb8e0057e73",
                    "sha256:3b946bbcd5a8231383450b195cfb58cb01cbe7f8949f5758566b881df4b33baf",
                    "sha256:3baf5f126f30781b5e93dbefcc8271cb2491647f8283f20ac54d12161dff080e",
                    "sha256:4b14d5e09c656de5038a3f9bfe5228f53439282abcab87317c9f7f1acb280352",
                    "sha256:51b236e764840a6df0661b67e50697aaa0e7d4124ca95e5058fa3d7cbc240b7c",
                    "sha256:63ffd21aa133ff48c4dff7adcc46b7ec8b565491bfc371212122dd999812ea1c",
                    "sha256:6a43c7823cd7427b4ed763aa7fb63901ca8288591323b58c9cd6ec31ad910f3c",
                    "sha256:755e89e32376c850f826c425ece2c35a4fc266c081490eb0a841e7c1cb0d3bda",
                    "sha256:7a726d742816cb3a8973c8c9a97539c734b3a309345236cd533c4883dda05b8d",
                    "sha256:7c7c0d0827e853315c9bbd43c1162c006dd808dbbe297db7ae66cd17b07830f0",
                    "sha256:7ed681b0f8e8bcbbffa58ba26fcf5dbc8f79e7997595bf071ed5430d8c08d6f3",
                    "sha256:7ee5c9bb51695f80878faaa5598040dd6c9e172ddcf490382e8aedb8ec3fec8d",
                    "sha256:8361be1c2c073919500b6601220a6f2f98ea0b6d2fec5014c1d9cfa23dd07038",
                    "sha256:8ae125d1134bf236acba8b83e74c603d1b30e207266121e76484562bc816344c",
                    "sha256:9817733f0d3ea91bea80de0f79ef971ae94f81ca52f9b66500c6a2fea8e4b4f8",
                    "sha256:98b85dd86514d889a2e3dd22ab3c18c9d0019e696478391d86708b805f4ea0fa",
                    "sha256:9ccb092c9ede70b2517a57382a601619d20981f56f440eae7e4d7eaafd1d1d09",
                    "sha256:9d58885215094ab4a86a6aef044e42994a2bd76a446dc59b352622655ba6621b",
                    "sha256:b643cb30821e7570c0aaf54feaf0bfb630b79059f85741843e9dc23f33aaca2c",
                    "sha256:bc7c85a150501286f8b56bd8ed3aa4093f4b88fb68c0843d21ff9656f0009d6a",
                    "sha256:beeb129cacea34490ffd4d6153af70509aa3cda20fdda2ea1a2be870dfec8d52",
                    "sha256:c31b75ae466c053a98bf26843563b3b3517b8f37da4d47b1c582fdc703112bc3",
                    "sha256:c4e4881fa9e9667afcc742f0c244d9364d197490fbc91d12ac3b5de0bf2df146",
                    "sha256:c5b15ed7644ae4bee0ecf74fee95808dcc34ba6ace87e8dfbf5cb0dc20eab45a",
                    "sha256:d12d076582507ea460ea2a89a8c85cb558f83406c8a41dd641d7be9a32e1274f",
                    "sha256:d248cd4a92065a4d4543b8331660121b31c4148dd00a691bfb7a5cdc7483cfa4",
                    "sha256:d47dd659a4ee952e90dc56c97d78132573dc5c7b09d61b416a9deef4ebe01a0c",
                    "sha256:d4a5a5879a939cb84959d86869132b00176197ca561c664fc21478c1eee60d75",
                    "sha256:da9b41d4539eefd408c46725fb76ecba3a50a3367cafb7dea5f250d0653c1040",
                    "sha256:db61a79c07331e88b9a9974815c075fbd812bc9dbc4dc44b366b5368a2936063",
                    "sha256:ddb726cb861c3117a553f940372a495fe1078249ff5f8a5478c0576c7be12050",
                    "sha256:ded59300d6330be27bc6cf0b74b89ada58069ced87c48eaf9344e5e84b0072f7",
                    "sha256:e2617759031dae1bf183c16cef8fcfb3de7617f394c813fa5e8e46e9b82d4222",
                    "sha256:e5cdbb5cafcedea04924568d990e20ce7f1945a1dd54b560f879ee2d57226912",
                    "sha256:ec8e767f13be637d056f7e07e61d089e555f719b387a7070154ad80a0ff31801",
                    "sha256:ef382417db92ba23dfb5864a3fc9be27ea4894e86620d342a116b243ade5d35d",
                    "sha256:f2cba5c6db29ce991029b5e4ac51eb36774458f0a3b8d3137241b32d1bb91f06",
                    "sha256:f5b4198d85a3755d27e64c52f8c95d6333119e49fd001ae5798dac872c95e0f8",
                    "sha256:ffeeb38ee4a80a30a6877c5c4c359e5498eec095878f1581453202bfacc8fbc2"
                ],
                "markers": "python_version >= '3.7'",
                "version": "==7.1.0"
            },
            "iniconfig": {
                "hashes": [
                    "sha256:2d91e135bf72d31a410b17c16da610a82cb55f6b0477d1a902134b24a455b8b3",
                    "sha256:b6a85871a79d2e3b22d2d1b94ac2824226a63c6b741c88f7ae975f18b6778374"
                ],
                "markers": "python_version >= '3.7'",
                "version": "==2.0.0"
            },
            "packaging": {
                "hashes": [
                    "sha256:714ac14496c3e68c99c29b00845f7a2b85f3bb6f1078fd9f72fd20f0570002b2",
                    "sha256:b6ad297f8907de0fa2fe1ccbd26fdaf387f5f47c7275fedf8cce89f99446cf97"
                ],
                "markers": "python_version >= '3.7'",
                "version": "==23.0"
            },
            "pluggy": {
                "hashes": [
                    "sha256:4224373bacce55f955a878bf9cfa763c1e360858e330072059e10bad68531159",
                    "sha256:74134bbf457f031a36d68416e1509f34bd5ccc019f0bcc952c7b909d06b37bd3"
                ],
                "markers": "python_version >= '3.6'",
                "version": "==1.0.0"
            },
            "pytest": {
                "hashes": [
                    "sha256:c7c6ca206e93355074ae32f7403e8ea12163b1163c976fee7d4d84027c162be5",
                    "sha256:d45e0952f3727241918b8fd0f376f5ff6b301cc0777c6f9a556935c92d8a7d42"
                ],
                "markers": "python_version >= '3.7'",
                "version": "==7.2.1"
            },
            "pytest-cov": {
                "hashes": [
                    "sha256:578d5d15ac4a25e5f961c938b85a05b09fdaae9deef3bb6de9a6e766622ca7a6",
                    "sha256:e7f0f5b1617d2210a2cabc266dfe2f4c75a8d32fb89eafb7ad9d06f6d076d470"
                ],
                "index": "pypi",
                "version": "==3.0.0"
            }
        }
    }


## Importing from requirements.txt

For projects utilizing a `requirements.txt` pipenv can import the contents of this file and create a
`Pipfile` and `Pipfile.lock` for you:

    $ pipenv install -r path/to/requirements.txt

If your requirements file has version numbers pinned, you'll likely want to edit the new `Pipfile`
to only keep track of top level dependencies and let `pipenv` keep track of pinning sub-dependencies in the lock file.


## Pipfile.lock Security Features

`Pipfile.lock` leverages the security of package hash validation in `pip`.
The `Pipfile.lock` is generated with the sha256 hashes of each downloaded package.
This guarantees you're installing the same exact packages on any network as the one
where the lock file was last updated, even on untrusted networks.

We recommend designing CI/CD deployments whereby the build does not alter the lock file as a side effect.
In other words, you can use `pipenv lock` or `pipenv upgrade` to adjust your lockfile through local development.
The PR process of reviewing and approving those lock changes before deploying to production that version of the lockfile
is a recommended best practice.
In other words: always avoid having your CI issue `lock`, `update`, `upgrade` `uninstall` or any commands that will relock.

```{admonition} Generate requirements.txt output from lock file
  $ pipenv requirements
```

## Package Category Groups

Pipenv supports arbitrarily named package categories in the Pipfile/Pipfile.lock for organizing dependencies into different groups.

Traditionally there were only two package groups, and they were named different between the `Pipfile` and `Pipfile.lock`:

* `packages` in the `Pipfile` corresponds to `default` group in the lockfile.
* `dev-packages` in the `Pipfile` corresponds to `develop` group in the lockfile.

The default/packages group is what you interact with when specifying no particular categories,
whereas the develop/dev-packages group is typically what you interact with when specifying the `--dev` or `-d` flag.

Beginning in `pipenv==2022.10.9` support for named package categories was generalized such that any
non-reserved keywords may be used to create named package groups other than the original groups.
All named categories (other than the special default/develop) will use the category name consistently between the `Pipfile` and `Pipfile.lock`

## General Notes and Recommendations

- Keep both `Pipfile` and `Pipfile.lock` in version control.
- `pipenv install package-name` adds specifiers to `Pipfile` and rebuilds the lock file based on the Pipfile specs, by utilizing the internal resolver of `pip`.
- Not all the required sub-dependencies need be specified in `Pipfile`, instead only add specifiers that make sense for the stability of your project.
Example:  `requests` requires `cryptography` but (for reasons) you want to ensure `cryptography` is pinned to a particular version set.
- Consider specifying your target Python version in your `Pipfile`'s `[requires]` section.
For this use either `python_version` in the format `X.Y` (or `X`) or `python_full_version` in `X.Y.Z` format.
- Considering making use of named package categories to further isolate dependency install groups for large monoliths.
