#!/usr/bin/env python

import keyboard

from numctl import operational, handler

if __name__ == '__main__':
    operational()
    keyboard.hook(handler)
    keyboard.wait()
