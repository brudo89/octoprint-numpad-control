#!/usr/bin/env python3

import datetime
import json
import logging
import os
import socket
from itertools import product
from pprint import pformat

import pygame
import requests
import yaml

logger = logging.getLogger()
logging.basicConfig(level=logging.DEBUG)

pygame.init()
screen = pygame.display.set_mode((320, 240))

CFG_FILE = os.path.expanduser('~/.octoprint/config.yaml')
OCTO_PORT = 80
OCTO_HOST = 'octopi'

if OCTO_HOST is None:
    OCTO_HOST = socket.gethostname()

logger.debug('reading config : %s', CFG_FILE)
with open(CFG_FILE) as fp:
    CONFIG = yaml.safe_load(fp)

HEADERS = {'Content-Type': 'application/json', 'X-Api-Key': CONFIG['api']['key']}

BED_WIDTH = BED_DEPTH = 220
SIDE_DIST = 40
JOG_HEIGHT = 10
POS_WIDTH = POS_DEPTH = [SIDE_DIST, BED_WIDTH/2, BED_WIDTH - SIDE_DIST]
BED_POS = list(product(POS_DEPTH, POS_WIDTH))
logger.debug('bed positions : %s', BED_POS)

JOG_STEP = JOG_STEP_X = JOG_STEP_Y = JOG_STEP_Z = 10
JOG_MOV = list(product([-JOG_STEP_Y, 0, JOG_STEP_Y], [-JOG_STEP_X, 0, JOG_STEP_X]))
logger.debug('jog movements : %s', BED_POS)

BED_ON_TEMP = 60
TOOL_ON_TEMP = 200

NUML_MOD = 4096  # numlock on
NUML_OFF = 0     # numlock off


def api_get(route, data=None, headers=HEADERS):
    url = 'http://{host}/api/{route}'.format(host='{}:{}'.format(OCTO_HOST, OCTO_PORT), route=route)
    data = json.dumps(data) if not isinstance(data, str) else data
    logger.debug('request: %s', json.dumps(dict(url=url, data=data, headers=headers), indent=4))
    return requests.get(url, data=data, headers=headers)


def api_post(route, data, headers=HEADERS):
    url = 'http://{host}/api/{route}'.format(host='{}:{}'.format(OCTO_HOST, OCTO_PORT), route=route)
    data = json.dumps(data) if not isinstance(data, str) else data
    logger.debug('request: %s', json.dumps(dict(url=url, data=data, headers=headers), indent=4))
    return requests.post(url, data=data, headers=headers)


def toggle_bed_temp(bed_is_on=None):

    if bed_is_on is None:
        status = api_get('printer/bed').json()
        logger.debug('bed_temp = %s', status)
        bed_is_on = status['bed']['target'] == BED_ON_TEMP

    bed_temp = 0 if bed_is_on else BED_ON_TEMP
    api_post('printer/bed', {'command': 'target', 'target': bed_temp})


def toggle_tool_temp(tool_is_on=None, tool='tool0'):

    if tool_is_on is None:
        status = api_get('printer/tool').json()
        logger.debug('tool_temp = %s', status)
        tool_is_on = status[tool]['target'] == TOOL_ON_TEMP

    tool_temp = 0 if tool_is_on else TOOL_ON_TEMP
    api_post('printer/tool', {'command': 'target', 'targets': {tool: tool_temp}})


key_map = {}

# add for both numlock on and off
for mod in (NUML_MOD, NUML_OFF):
    key_map[(256, mod)] = {'key_name': 'Num+0', 'route': 'printer/printhead', 'tasks': [
        {'command': 'home', 'axes': ['x', 'y', 'z']}
    ]}
    key_map[(266, mod)] = {'key_name': 'NumDot', 'route': 'printer/printhead', 'tasks': [
        {'command': 'home', 'axes': ['x', 'y']}
    ]}
    key_map[(271, mod)] = {'key_name': 'NumEnter', 'route': 'printer/printhead', 'tasks': [
        {'command': 'home', 'axes': ['z']}
    ]}

    key_map[(269, mod)] = {'key_name': 'NumMinus', 'route': 'printer/printhead', 'tasks': [
        {'command': 'jog', 'absolute': False, 'z': -10},
    ]}
    key_map[(270, mod)] = {'key_name': 'NumPlus', 'route': 'printer/printhead', 'tasks': [
        {'command': 'jog', 'absolute': False, 'z': 10},
    ]}

    key_map[(267, mod)] = {'key_name': 'NumDivide', 'func': toggle_bed_temp}
    key_map[(268, mod)] = {'key_name': 'NumMultiply', 'func': toggle_tool_temp}

for i, (y, x) in enumerate(BED_POS):
    # add absolute positions for leveling
    key = (i + 1 + 256, NUML_MOD)
    key_map[key] = {
        'key_name': 'NumLck{}'.format(i+1),
        'route': 'printer/printhead', 'tasks': [
            {'command': 'jog', 'absolute': True, 'z': JOG_STEP_Z},
            {'command': 'jog', 'absolute': True, 'x': x, 'y': y},
        ]}

for i, (y, x) in enumerate(JOG_MOV):
    # add relative positions for movement
    key = (i + 1 + 256, NUML_OFF)
    key_map[key] = {
        'key_name': 'NumOff{}'.format(i+1),
        'route': 'printer/printhead', 'tasks': [
            {'command': 'jog', 'absolute': False, 'x': x, 'y': y},
        ]}

logger.debug('registered keys: %s', pformat(key_map, indent=4))


def operational(task: dict = None, is_op=None):

    if task is None:
        task = dict()

    if is_op is None:
        is_op = task.get('operational')

    if is_op is None:
        response = api_get('printer', {'exclude': 'temperature'})
        data = response.json()
        logger.debug('response: %s : %s', response, json.dumps(data, indent=4))
        is_op = data['state']['flags']['operational']

    if is_op:
        logger.info('operational: %s', is_op)
    else:
        logger.warning('operational: %s', is_op)
    return is_op


def enabled(task):
    return operational(task)


def trigger(key, mod, **kwargs):
    action = key_map.get((key, mod))
    if action is None:
        logger.debug('nothing to do for key=%s mod=%s', key, mod)
    elif enabled(action):
        func = action.get('func')
        if func is not None:
            func(**kwargs)
        else:
            for data in action['tasks']:
                api_post(action['route'], data)
    else:
        logger.warning('task disabled while not operational!')


if __name__ == '__main__':
    operational()

    triggered = datetime.datetime.now() - datetime.timedelta(hours=1)
    delay = datetime.timedelta(seconds=0.1)

    logger.debug('waiting for keypress event')

    while True:
        for event in pygame.event.get():
            if event.type == pygame.KEYDOWN:
                now = datetime.datetime.now()
                delta = now - triggered
                if delta > delay:
                    triggered = now
                    logger.debug(event)
                    trigger(event.key, event.mod)
                    logger.debug('waiting for keypress event')
                else:
                    logger.warning('time delay not reached %s < %s', delta, delay)
