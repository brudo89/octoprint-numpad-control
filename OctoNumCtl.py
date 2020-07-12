#!/usr/bin/env python

import keyboard
import logging

from numctl import keypress_handler, get_printer_status

logging.basicConfig(level=logging.DEBUG)

if __name__ == '__main__':
    status = get_printer_status() or dict()
    status = status.get('state', dict()).get('text')
    print('printer status = {}'.format(status))

    keyboard.hook(keypress_handler)
    keyboard.wait()
