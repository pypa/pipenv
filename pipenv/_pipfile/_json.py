import _ctypes
import json
import re
from collections import OrderedDict

# http://stackoverflow.com/questions/13249415/can-i-implement-custom-indentation-for-pretty-printing-in-python-s-json-module
#
def di(obj_id):
    # from http://stackoverflow.com/a/15012814/355230
    """ Reverse of id() function. """
    return _ctypes.PyObj_FromPtr(obj_id)

class NoIndent(object):
    def __init__(self, value):
        self.value = value
    def __repr__(self):
        if isinstance(self.value, OrderedDict):
            return json.dumps(self.value)
        if not isinstance(self.value, list):
            return repr(self.value)
        else:  # the sort the representation of any dicts in the list
            reps = ('{{{}}}'.format(', '.join(('{!r}:{}'.format(
                                        k, v) for k, v in sorted(v.items()))))
                    if isinstance(v, dict) else repr(v) for v in self.value)

            return '[' + ', '.join(reps) + ']'

class NoIndentEncoder(json.JSONEncoder):
    FORMAT_SPEC = "@@{}@@"
    regex = re.compile(FORMAT_SPEC.format(r"(\d+)"))

    def default(self, obj):
        if not isinstance(obj, NoIndent):
            return super(NoIndentEncoder, self).default(obj)
        return self.FORMAT_SPEC.format(id(obj))

    def encode(self, obj):
        format_spec = self.FORMAT_SPEC  # local var to expedite access
        result = super(NoIndentEncoder, self).encode(obj)
        for match in self.regex.finditer(result):
            id = int(match.group(1))
            result = result.replace('"{}"'.format(format_spec.format(id)),
                                    repr(di(int(id))))
        return result


def dumps(obj):
    """Returns specific data in a specific format."""
    obj['_meta']['requires'] = [NoIndent(i) for i in obj['_meta']['requires']]
    obj['_meta']['sources'] = [NoIndent(i) for i in obj['_meta']['sources']]
    obj['default'] = [NoIndent(i) for i in obj['default']]
    obj['develop'] = [NoIndent(i) for i in obj['develop']]

    return json.dumps(obj, sort_keys=True, cls=NoIndentEncoder, indent=4, separators=(',', ': '))