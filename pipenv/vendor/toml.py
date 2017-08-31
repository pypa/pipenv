# This software is released under the MIT license

import re
import datetime

class TomlDecodeError(Exception):
    pass

class TomlTz(datetime.tzinfo):

    def __init__(self, toml_offset):
        if toml_offset == "Z":
            self._raw_offset = "+00:00"
        else:
            self._raw_offset = toml_offset
        self._hours = int(self._raw_offset[:3])
        self._minutes = int(self._raw_offset[4:6])

    def tzname(self, dt):
        return "UTC"+self._raw_offset

    def utcoffset(self, dt):
        return datetime.timedelta(hours=self._hours, minutes=self._minutes)

    def dst(self, dt):
        return datetime.timedelta(0)

try:
    _range = xrange
except NameError:
    unicode = str
    _range = range
    basestring = str
    unichr = chr

def load(f, _dict=dict):
    """Returns a dictionary containing the named file parsed as toml."""
    if isinstance(f, basestring):
        with open(f) as ffile:
            return loads(ffile.read(), _dict)
    elif isinstance(f, list):
        for l in f:
            if not isinstance(l, basestring):
                raise TypeError("Load expects a list to contain filenames only")
        d = _dict()
        for l in f:
            d.update(load(l))
        return d
    elif f.read:
        return loads(f.read(), _dict)
    else:
        raise TypeError("You can only load a file descriptor, filename or list")

_groupname_re = re.compile(r'^[A-Za-z0-9_-]+$')

def loads(s, _dict=dict):
    """Returns a dictionary containing s, a string, parsed as toml."""
    implicitgroups = []
    retval = _dict()
    currentlevel = retval
    if not isinstance(s, basestring):
        raise TypeError("What exactly are you trying to pull?")
    try:
        s = s.decode('utf8')
    except AttributeError:
        pass
    sl = list(s)
    openarr = 0
    openstring = False
    openstrchar = ""
    multilinestr = False
    arrayoftables = False
    beginline = True
    keygroup = False
    keyname = 0
    for i in _range(len(sl)):
        if sl[i] == '\r' and sl[i+1] == '\n':
            sl[i] = ' '
            continue
        if keyname:
            if sl[i] == '\n':
                raise TomlDecodeError("Key name found without value. Reached end of line.")
            if openstring:
                if sl[i] == openstrchar:
                    keyname = 2
                    openstring = False
                    openstrchar = ""
                continue
            elif keyname == 1:
                if sl[i].isspace():
                    keyname = 2
                    continue
                elif sl[i].isalnum() or sl[i] == '_' or sl[i] == '-':
                    continue
            elif keyname == 2 and sl[i].isspace():
                continue
            if sl[i] == '=':
                keyname = 0
            else:
                raise TomlDecodeError("Found invalid character in key name: '"+sl[i]+"'. Try quoting the key name.")
        if sl[i] == "'" and openstrchar != '"':
            k = 1
            try:
                while sl[i-k] == "'":
                    k += 1
                    if k == 3:
                        break
            except IndexError:
                pass
            if k == 3:
                multilinestr = not multilinestr
                openstring = multilinestr
            else:
                openstring = not openstring
            if openstring:
                openstrchar = "'"
            else:
                openstrchar = ""
        if sl[i] == '"' and openstrchar != "'":
            oddbackslash = False
            k = 1
            tripquote = False
            try:
                while sl[i-k] == '"':
                    k += 1
                    if k == 3:
                        tripquote = True
                        break
                while sl[i-k] == '\\':
                    oddbackslash = not oddbackslash
                    k += 1
            except IndexError:
                pass
            if not oddbackslash:
                if tripquote:
                    multilinestr = not multilinestr
                    openstring = multilinestr
                else:
                    openstring = not openstring
            if openstring:
                openstrchar = '"'
            else:
                openstrchar = ""
        if sl[i] == '#' and not openstring and not keygroup and \
                not arrayoftables:
            j = i
            try:
                while sl[j] != '\n':
                    sl[j] = ' '
                    j += 1
            except IndexError:
                break
        if sl[i] == '[' and not openstring and not keygroup and \
                not arrayoftables:
            if beginline:
                if sl[i+1] == '[':
                    arrayoftables = True
                else:
                    keygroup = True
            else:
                openarr += 1
        if sl[i] == ']' and not openstring:
            if keygroup:
                keygroup = False
            elif arrayoftables:
                if sl[i-1] == ']':
                    arrayoftables = False
            else:
                openarr -= 1
        if sl[i] == '\n':
            if openstring or multilinestr:
                if not multilinestr:
                    raise TomlDecodeError("Unbalanced quotes")
                if sl[i-1] == "'" or sl[i-1] == '"':
                    sl[i] = sl[i-1]
                    sl[i-3] = ' '
            elif openarr:
                sl[i] = ' '
            else:
                beginline = True
        elif beginline and sl[i] != ' ' and sl[i] != '\t':
            beginline = False
            if not keygroup and not arrayoftables:
                if sl[i] == '=':
                    raise TomlDecodeError("Found empty keyname. ")
                keyname = 1
    s = ''.join(sl)
    s = s.split('\n')
    multikey = None
    multilinestr = ""
    multibackslash = False
    for line in s:
        line = line.strip()
        if line == "":
            continue
        if multikey:
            if multibackslash:
                multilinestr += line
            else:
                multilinestr += line
            multibackslash = False
            if len(line) > 2 and line[-1] == multilinestr[0] and \
                    line[-2] == multilinestr[0] and line[-3] == multilinestr[0]:
                value, vtype = _load_value(multilinestr)
                currentlevel[multikey] = value
                multikey = None
                multilinestr = ""
            else:
                k = len(multilinestr) -1
                while k > -1 and multilinestr[k] == '\\':
                    multibackslash = not multibackslash
                    k -= 1
                if multibackslash:
                    multilinestr = multilinestr[:-1]
                else:
                    multilinestr += "\n"
            continue
        if line[0] == '[':
            arrayoftables = False
            if line[1] == '[':
                arrayoftables = True
                line = line[2:].split(']]', 1)
            else:
                line = line[1:].split(']', 1)
            if line[1].strip() != "":
                raise TomlDecodeError("Key group not on a line by itself.")
            groups = line[0].split('.')
            i = 0
            while i < len(groups):
                groups[i] = groups[i].strip()
                if groups[i][0] == '"' or groups[i][0] == "'":
                    groupstr = groups[i]
                    j = i+1
                    while not groupstr[0] == groupstr[-1]:
                        j += 1
                        groupstr = '.'.join(groups[i:j])
                    groups[i] = groupstr[1:-1]
                    groups[i+1:j] = []
                else:
                    if not _groupname_re.match(groups[i]):
                        raise TomlDecodeError("Invalid group name '"+groups[i]+"'. Try quoting it.")
                i += 1
            currentlevel = retval
            for i in _range(len(groups)):
                group = groups[i]
                if group == "":
                    raise TomlDecodeError("Can't have a keygroup with an empty name")
                try:
                    currentlevel[group]
                    if i == len(groups) - 1:
                        if group in implicitgroups:
                            implicitgroups.remove(group)
                            if arrayoftables:
                                raise TomlDecodeError("An implicitly defined table can't be an array")
                        elif arrayoftables:
                            currentlevel[group].append(_dict())
                        else:
                            raise TomlDecodeError("What? "+group+" already exists?"+str(currentlevel))
                except TypeError:
                    if i != len(groups) - 1:
                        implicitgroups.append(group)
                    currentlevel = currentlevel[-1]
                    try:
                        currentlevel[group]
                    except KeyError:
                        currentlevel[group] = _dict()
                        if i == len(groups) - 1 and arrayoftables:
                            currentlevel[group] = [_dict()]
                except KeyError:
                    if i != len(groups) - 1:
                        implicitgroups.append(group)
                    currentlevel[group] = _dict()
                    if i == len(groups) - 1 and arrayoftables:
                        currentlevel[group] = [_dict()]
                currentlevel = currentlevel[group]
                if arrayoftables:
                    try:
                        currentlevel = currentlevel[-1]
                    except KeyError:
                        pass
        elif line[0] == "{":
            if line[-1] != "}":
                raise TomlDecodeError("Line breaks are not allowed in inline objects")
            _load_inline_object(line, currentlevel, multikey, multibackslash)
        elif "=" in line:
            ret = _load_line(line, currentlevel, multikey, multibackslash)
            if ret is not None:
                multikey, multilinestr, multibackslash = ret
    return retval

def _load_inline_object(line, currentlevel, multikey=False, multibackslash=False):
    candidate_groups = line[1:-1].split(",")
    groups = []
    while len(candidate_groups) > 0:
        candidate_group = candidate_groups.pop(0)
        _, value = candidate_group.split('=', 1)
        value = value.strip()
        if (value[0] == value[-1] and value[0] in ('"', "'")) or \
                value[0] in '0123456789' or \
                value in ('true', 'false') or \
                value[0] == "[" and value[-1] == "]":
            groups.append(candidate_group)
        else:
            candidate_groups[0] = candidate_group + "," + candidate_groups[0]
    for group in groups:
        status = _load_line(group, currentlevel, multikey, multibackslash)
        if status is not None:
            break

# Matches a TOML number, which allows underscores for readability
_number_with_underscores = re.compile('([0-9])(_([0-9]))*')

def _load_line(line, currentlevel, multikey, multibackslash):
    i = 1
    pair = line.split('=', i)
    if _number_with_underscores.match(pair[-1]):
        pair[-1] = pair[-1].replace('_', '')
    while pair[-1][0] != ' ' and pair[-1][0] != '\t' and \
            pair[-1][0] != "'" and pair[-1][0] != '"' and \
            pair[-1][0] != '[' and pair[-1] != 'true' and \
            pair[-1] != 'false':
        try:
            float(pair[-1])
            break
        except ValueError:
            pass
        if _load_date(pair[-1]) is not None:
            break
        i += 1
        prev_val = pair[-1]
        pair = line.split('=', i)
        if prev_val == pair[-1]:
            raise TomlDecodeError("Invalid date or number")
    pair = ['='.join(pair[:-1]).strip(), pair[-1].strip()]
    if (pair[0][0] == '"' or pair[0][0] == "'") and \
            (pair[0][-1] == '"' or pair[0][-1] == "'"):
        pair[0] = pair[0][1:-1]
    if len(pair[1]) > 2 and (pair[1][0] == '"' or pair[1][0] == "'") \
            and pair[1][1] == pair[1][0] and pair[1][2] == pair[1][0] \
            and not (len(pair[1]) > 5 and pair[1][-1] == pair[1][0] and \
                         pair[1][-2] == pair[1][0] and \
                         pair[1][-3] == pair[1][0]):
        k = len(pair[1]) -1
        while k > -1 and pair[1][k] == '\\':
            multibackslash = not multibackslash
            k -= 1
        if multibackslash:
            multilinestr = pair[1][:-1]
        else:
            multilinestr = pair[1] + "\n"
        multikey = pair[0]
    else:
        value, vtype = _load_value(pair[1])
    try:
        currentlevel[pair[0]]
        raise TomlDecodeError("Duplicate keys!")
    except KeyError:
        if multikey:
            return multikey, multilinestr, multibackslash
        else:
            currentlevel[pair[0]] = value

def _load_date(val):
    microsecond = 0
    tz = None
    try:
        if len(val) > 19:
            if val[19] == '.':
                microsecond = int(val[20:26])
                if len(val) > 26:
                    tz = TomlTz(val[26:32])
            else:
                tz = TomlTz(val[19:25])
    except ValueError:
        tz = None
    try:
        d = datetime.datetime(int(val[:4]), int(val[5:7]), int(val[8:10]), int(val[11:13]), int(val[14:16]), int(val[17:19]), microsecond, tz)
    except ValueError:
        return None
    return d

def _load_unicode_escapes(v, hexbytes, prefix):
    hexchars = ['0', '1', '2', '3', '4', '5', '6', '7',
                '8', '9', 'a', 'b', 'c', 'd', 'e', 'f']
    skip = False
    i = len(v) - 1
    while i > -1 and v[i] == '\\':
        skip = not skip
        i -= 1
    for hx in hexbytes:
        if skip:
            skip = False
            i = len(hx) - 1
            while i > -1 and hx[i] == '\\':
                skip = not skip
                i -= 1
            v += prefix
            v += hx
            continue
        hxb = ""
        i = 0
        hxblen = 4
        if prefix == "\\U":
            hxblen = 8
        while i < hxblen:
            try:
                if not hx[i].lower() in hexchars:
                    raise IndexError("This is a hack")
            except IndexError:
                raise TomlDecodeError("Invalid escape sequence")
            hxb += hx[i].lower()
            i += 1
        v += unichr(int(hxb, 16))
        v += unicode(hx[len(hxb):])
    return v

# Unescape TOML string values.
_escapes = ['0', 'b', 'f', 'n', 'r', 't', '"'] # content after the \
_escapedchars = ['\0', '\b', '\f', '\n', '\r', '\t', '\"'] # What it should be replaced by
_escape_to_escapedchars = dict(zip(_escapes, _escapedchars)) # Used for substitution

# Regexp that matches escaped value, checking the parity of the number
# of backslashes
_escapes_re = re.compile("""
        (?P<prefix>([^\\\\](\\\\\\\\)*)) # Parity of the number of backslashs
        \\\\                             # The actual backslash before the escape
        (?P<escape>[%s])                 # The escape
        """ % ''.join(_escapes),
        re.VERBOSE)

def _unescape(v):
    """Unescape characters in a TOML string."""
    v = _escapes_re.sub(lambda match: match.group('prefix') + _escape_to_escapedchars[match.group('escape')], v)
    v = v.replace("\\\\", "\\")
    return v

def _load_value(v):
    if v == 'true':
        return (True, "bool")
    elif v == 'false':
        return (False, "bool")
    elif v[0] == '"':
        testv = v[1:].split('"')
        if testv[0] == '' and testv[1] == '':
            testv = testv[2:-2]
        closed = False
        for tv in testv:
            if tv == '':
                closed = True
            else:
                oddbackslash = False
                try:
                    i = -1
                    j = tv[i]
                    while j == '\\':
                        oddbackslash = not oddbackslash
                        i -= 1
                        j = tv[i]
                except IndexError:
                    pass
                if not oddbackslash:
                    if closed:
                        raise TomlDecodeError("Stuff after closed string. WTF?")
                    else:
                        closed = True
        escapeseqs = v.split('\\')[1:]
        backslash = False
        for i in escapeseqs:
            if i == '':
                backslash = not backslash
            else:
                if i[0] not in _escapes and i[0] != 'u' and i[0] != 'U' and \
                        not backslash:
                    raise TomlDecodeError("Reserved escape sequence used")
                if backslash:
                    backslash = False
        for prefix in ["\\u", "\\U"]:
            if prefix in v:
                hexbytes = v.split(prefix)
                v = _load_unicode_escapes(hexbytes[0], hexbytes[1:], prefix)
        v = _unescape(v)
        if v[1] == '"':
            v = v[2:-2]
        return (v[1:-1], "str")
    elif v[0] == "'":
        if v[1] == "'":
            v = v[2:-2]
        return (v[1:-1], "str")
    elif v[0] == '[':
        return (_load_array(v), "array")
    elif v[0] == '{':
        inline_object = {}
        _load_inline_object(v, inline_object)
        return (inline_object, "inline_object")
    else:
        parsed_date = _load_date(v)
        if parsed_date is not None:
            return (parsed_date, "date")
        itype = "int"
        neg = False
        if v[0] == '-':
            neg = True
            v = v[1:]
        if '.' in v or 'e' in v:
            if v.split('.', 1)[1] == '':
                raise TomlDecodeError("This float is missing digits after the point")
            if v[0] not in '0123456789':
                raise TomlDecodeError("This float doesn't have a leading digit")
            v = float(v)
            itype = "float"
        else:
            v = int(v)
        if neg:
            return (0 - v, itype)
        return (v, itype)

def _load_array(a):
    atype = None
    retval = []
    a = a.strip()
    if '[' not in a[1:-1]:
        strarray = False
        tmpa = a[1:-1].strip()
        if tmpa != '' and tmpa[0] == '"':
            strarray = True
        if '{' not in a[1:-1]:
            a = a[1:-1].split(',')
        else:
            # a is an inline object, we must find the matching parenthesis to difine groups
            new_a = []
            start_group_index = 1
            end_group_index = 2
            in_str = False
            while end_group_index < len(a[1:-1]):
                if a[end_group_index] == '"' or a[end_group_index] == "'":
                    in_str = not in_str
                if a[end_group_index] == '}' and not in_str:
                    # Increase end_group_index by 1 to get the closing bracket
                    end_group_index += 1
                    new_a.append(a[start_group_index:end_group_index])
                    # The next start index is at least after the closing bracket, a closing bracket
                    # can be followed by a comma since we are in an array.
                    start_group_index = end_group_index + 1
                    while a[start_group_index] != '{' and start_group_index < len(a[1:-1]):
                        start_group_index += 1
                    end_group_index = start_group_index + 1
                else:
                    end_group_index += 1
            a = new_a
        b = 0
        if strarray:
            while b < len(a) - 1:
                while a[b].strip()[-1] != '"' and a[b+1].strip()[0] != '"':
                    a[b] = a[b] + ',' + a[b+1]
                    if b < len(a) - 2:
                        a = a[:b+1] + a[b+2:]
                    else:
                        a = a[:b+1]
                b += 1
    else:
        al = list(a[1:-1])
        a = []
        openarr = 0
        j = 0
        for i in _range(len(al)):
            if al[i] == '[':
                openarr += 1
            elif al[i] == ']':
                openarr -= 1
            elif al[i] == ',' and not openarr:
                a.append(''.join(al[j:i]))
                j = i+1
        a.append(''.join(al[j:]))
    for i in _range(len(a)):
        a[i] = a[i].strip()
        if a[i] != '':
            nval, ntype = _load_value(a[i])
            if atype:
                if ntype != atype:
                    raise TomlDecodeError("Not a homogeneous array")
            else:
                atype = ntype
            retval.append(nval)
    return retval

def dump(o, f):
    """Writes out to f the toml corresponding to o. Returns said toml."""
    if not f.write:
        raise TypeError("You can only dump an object to a file descriptor")
    d = dumps(o)
    f.write(d)
    return d

def dumps(o):
    """Returns a string containing the toml corresponding to o, a dictionary"""
    retval = ""
    addtoretval, sections = _dump_sections(o, "")
    retval += addtoretval
    while sections != {}:
        newsections = {}
        for section in sections:
            addtoretval, addtosections = _dump_sections(sections[section], section)
            if addtoretval:
                retval += "["+section+"]\n"
                retval += addtoretval
            for s in addtosections:
                newsections[section+"."+s] = addtosections[s]
        sections = newsections
    return retval

def _dump_sections(o, sup):
    retstr = ""
    if sup != "" and sup[-1] != ".":
        sup += '.'
    retdict = {}
    arraystr = ""
    for section in o:
        qsection = section
        if not re.match(r'^[A-Za-z0-9_-]+$', section):
            if '"' in section:
                qsection = "'" + section + "'"
            else:
                qsection = '"' + section + '"'
        if not isinstance(o[section], dict):
            arrayoftables = False
            if isinstance(o[section], list):
                for a in o[section]:
                    if isinstance(a, dict):
                        arrayoftables = True
            if arrayoftables:
                for a in o[section]:
                    arraytabstr = ""
                    arraystr += "[["+sup+qsection+"]]\n"
                    s, d = _dump_sections(a, sup+qsection)
                    if s:
                        if s[0] == "[":
                            arraytabstr += s
                        else:
                            arraystr += s
                    while d != {}:
                        newd = {}
                        for dsec in d:
                            s1, d1 = _dump_sections(d[dsec], sup+qsection+"."+dsec)
                            if s1:
                                arraytabstr += "["+sup+qsection+"."+dsec+"]\n"
                                arraytabstr += s1
                            for s1 in d1:
                                newd[dsec+"."+s1] = d1[s1]
                        d = newd
                    arraystr += arraytabstr
            else:
                if o[section] is not None:
                    retstr += (qsection + " = " +
                               str(_dump_value(o[section])) + '\n')
        else:
            retdict[qsection] = o[section]
    retstr += arraystr
    return (retstr, retdict)

def _dump_value(v):
    if isinstance(v, list):
        t = []
        retval = "["
        for u in v:
            t.append(_dump_value(u))
        while t != []:
            s = []
            for u in t:
                if isinstance(u, list):
                    for r in u:
                        s.append(r)
                else:
                    retval += " " + str(u) + ","
            t = s
        retval += "]"
        return retval
    if isinstance(v, (str, unicode)):
        v = "%r" % v
        if v[0] == 'u':
            v = v[1:]
        singlequote = v[0] == "'"
        v = v[1:-1]
        if singlequote:
            v = v.replace("\\'", "'")
            v = v.replace('"', '\\"')
        v = v.replace("\\x", "\\u00")
        return str('"'+v+'"')
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, datetime.datetime):
        return v.isoformat()[:19]+'Z'
    if isinstance(v, float):
        return str(v)
    return v
