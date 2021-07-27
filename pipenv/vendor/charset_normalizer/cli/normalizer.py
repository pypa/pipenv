import argparse
import sys
from os.path import abspath
from json import dumps

from charset_normalizer import from_fp
from charset_normalizer.models import CliDetectionResult
from charset_normalizer.version import __version__

from platform import python_version


def query_yes_no(question, default="yes"):
    """Ask a yes/no question via input() and return their answer.

    "question" is a string that is presented to the user.
    "default" is the presumed answer if the user just hits <Enter>.
        It must be "yes" (the default), "no" or None (meaning
        an answer is required of the user).

    The "answer" return value is True for "yes" or False for "no".

    Credit goes to (c) https://stackoverflow.com/questions/3041986/apt-command-line-interface-like-yes-no-input
    """
    valid = {"yes": True, "y": True, "ye": True,
             "no": False, "n": False}
    if default is None:
        prompt = " [y/n] "
    elif default == "yes":
        prompt = " [Y/n] "
    elif default == "no":
        prompt = " [y/N] "
    else:
        raise ValueError("invalid default answer: '%s'" % default)

    while True:
        sys.stdout.write(question + prompt)
        choice = input().lower()
        if default is not None and choice == '':
            return valid[default]
        elif choice in valid:
            return valid[choice]
        else:
            sys.stdout.write("Please respond with 'yes' or 'no' "
                             "(or 'y' or 'n').\n")


def cli_detect(argv=None):
    """
    CLI assistant using ARGV and ArgumentParser
    :param argv:
    :return: 0 if everything is fine, anything else equal trouble
    """
    parser = argparse.ArgumentParser(
        description="The Real First Universal Charset Detector. "
                    "Discover originating encoding used on text file. "
                    "Normalize text to unicode."
    )

    parser.add_argument('files', type=argparse.FileType('rb'), nargs='+', help='File(s) to be analysed')
    parser.add_argument('-v', '--verbose', action="store_true", default=False, dest='verbose',
                        help='Display complementary information about file if any. Stdout will contain logs about the detection process.')
    parser.add_argument('-a', '--with-alternative', action="store_true", default=False, dest='alternatives',
                        help='Output complementary possibilities if any. Top-level JSON WILL be a list.')
    parser.add_argument('-n', '--normalize', action="store_true", default=False, dest='normalize',
                        help='Permit to normalize input file. If not set, program does not write anything.')
    parser.add_argument('-m', '--minimal', action="store_true", default=False, dest='minimal',
                        help='Only output the charset detected to STDOUT. Disabling JSON output.')
    parser.add_argument('-r', '--replace', action="store_true", default=False, dest='replace',
                        help='Replace file when trying to normalize it instead of creating a new one.')
    parser.add_argument('-f', '--force', action="store_true", default=False, dest='force',
                        help='Replace file without asking if you are sure, use this flag with caution.')
    parser.add_argument('-t', '--threshold', action="store", default=0.1, type=float, dest='threshold',
                        help="Define a custom maximum amount of chaos allowed in decoded content. 0. <= chaos <= 1.")
    parser.add_argument(
        "--version",
        action="version",
        version="Charset-Normalizer {} - Python {}".format(__version__, python_version()),
        help="Show version information and exit."
    )

    args = parser.parse_args(argv)

    if args.replace is True and args.normalize is False:
        print('Use --replace in addition of --normalize only.', file=sys.stderr)
        return 1

    if args.force is True and args.replace is False:
        print('Use --force in addition of --replace only.', file=sys.stderr)
        return 1

    if args.threshold < 0. or args.threshold > 1.:
        print('--threshold VALUE should be between 0. AND 1.', file=sys.stderr)
        return 1

    for my_file in args.files:

        matches = from_fp(
            my_file,
            threshold=args.threshold,
            explain=args.verbose
        )

        if len(matches) == 0:
            print('Unable to identify originating encoding for "{}". {}'.format(my_file.name, 'Maybe try increasing maximum amount of chaos.' if args.threshold < 1. else ''), file=sys.stderr)
            if my_file.closed is False:
                my_file.close()
            continue

        x_ = []

        r_ = matches.best()
        p_ = r_.first()

        x_.append(
            CliDetectionResult(
                abspath(my_file.name),
                p_.encoding,
                p_.encoding_aliases,
                [cp for cp in p_.could_be_from_charset if cp != p_.encoding],
                p_.language,
                p_.alphabets,
                p_.bom,
                p_.percent_chaos,
                p_.percent_coherence,
                None,
                True
            )
        )

        if len(matches) > 1 and args.alternatives:
            for el in matches:
                if el != p_:
                    x_.append(
                        CliDetectionResult(
                            abspath(my_file.name),
                            el.encoding,
                            el.encoding_aliases,
                            [cp for cp in el.could_be_from_charset if cp != el.encoding],
                            el.language,
                            el.alphabets,
                            el.bom,
                            el.percent_chaos,
                            el.percent_coherence,
                            None,
                            False
                        )
                    )

        if args.normalize is True:

            if p_.encoding.startswith('utf') is True:
                print('"{}" file does not need to be normalized, as it already came from unicode.'.format(my_file.name), file=sys.stderr)
                if my_file.closed is False:
                    my_file.close()
                continue

            o_ = my_file.name.split('.')  # type: list[str]

            if args.replace is False:
                o_.insert(-1, p_.encoding)
                if my_file.closed is False:
                    my_file.close()
            else:
                if args.force is False and query_yes_no(
                        'Are you sure to normalize "{}" by replacing it ?'.format(my_file.name), 'no') is False:
                    if my_file.closed is False:
                        my_file.close()
                    continue

            try:
                x_[0].unicode_path = './{}'.format('.'.join(o_))

                with open(x_[0].unicode_path, 'w', encoding='utf-8') as fp:
                    fp.write(
                        str(p_)
                    )
            except IOError as e:
                print(str(e), file=sys.stderr)
                if my_file.closed is False:
                    my_file.close()
                return 2

        if my_file.closed is False:
            my_file.close()

    if args.minimal is False:
        print(
            dumps(
                [
                    el.__dict__ for el in x_
                ] if args.alternatives else x_[0].__dict__,
                ensure_ascii=True,
                indent=4
            )
        )
    else:
        print(
            ', '.join(
                [
                    el.encoding for el in x_
                ]
            )
        )

    return 0


if __name__ == '__main__':
    cli_detect()
