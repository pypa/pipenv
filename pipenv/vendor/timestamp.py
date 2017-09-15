import sys

def timestamp(d=None):
	import datetime
	import time
	return int(time.mktime(d.timetuple()) * 1000) if d else int(time.time() * 1000)

sys.modules[__name__] = timestamp

