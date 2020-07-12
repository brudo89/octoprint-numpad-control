#!/usr/bin/env python

import json

from numctl import get_connection_status, get_printer_status

if __name__ == '__main__':
    status = get_printer_status() or dict()
    status['connection'] = get_connection_status().get('current')
    print('status = {}'.format(json.dumps(status, indent=2, sort_keys=True)))
