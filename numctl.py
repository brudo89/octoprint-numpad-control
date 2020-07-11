
import json
import logging
import os
import socket
import sys
from itertools import product
from pprint import pformat

import requests
import yaml

from numcfg import *

logger = logging.getLogger()
logging.basicConfig(filename=LOGFILE, level=logging.DEBUG)

KDSETLED = 0x4B32
SCR_LED = 0x01
NUM_LED = 0x02
CAP_LED = 0x04

if TEST_MODE is None:
    TEST_MODE == '--test' in sys.argv[1:]

try:
    import fcntl
    logger.info('turning on num-lock led!')
    fd = os.open('/dev/console', os.O_NOCTTY)
    fcntl.ioctl(fd, KDSETLED, NUM_LED)
except (ModuleNotFoundError, PermissionError):
    fd = fcntl = None
    logger.warning('cannot control num-lock led!')

if API_KEY is None:
    CFG_FILE = '/home/pi/.octoprint/config.yaml'
    logger.debug('reading config : %s', CFG_FILE)
    with open(CFG_FILE) as fp:
        CONFIG = yaml.safe_load(fp)

if OCTO_HOST is None:
    OCTO_HOST = socket.gethostname()

HEADERS = {'Content-Type': 'application/json', 'X-Api-Key': CONFIG['api']['key']}

# leveling positions
POS_WIDTH = [SIDE_DIST, BED_WIDTH/2, BED_WIDTH - SIDE_DIST]
POS_DEPTH = [SIDE_DIST, BED_DEPTH/2, BED_DEPTH - SIDE_DIST]
BED_POS = list(product(POS_DEPTH, POS_WIDTH))
logger.debug('bed positions : %s', BED_POS)

JOG_MOV = list(product([-JOG_STEP_Y, 0, JOG_STEP_Y], [-JOG_STEP_X, 0, JOG_STEP_X]))
logger.debug('jog movements : %s', JOG_MOV)

NUM_LOCK = True   # current state (toggled)
NUML_MOD = True   # numlock on
NUML_OFF = False  # numlock off


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


def toggle_num_lock():
    global NUM_LOCK
    NUM_LOCK = not NUM_LOCK
    logger.info('NUM_LOCK: %s', NUM_LOCK)
    if fd and fcntl:
        fcntl.ioctl(fd, KDSETLED, NUM_LED if NUM_LOCK else 0)


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
    key_map[(SCN_0, mod)] = {'key_name': 'Num+0', 'route': 'printer/printhead', 'tasks': [
        {'command': 'home', 'axes': ['x', 'y', 'z']}
    ]}
    key_map[(SCN_DOT, mod)] = {'key_name': 'NumDot', 'route': 'printer/printhead', 'tasks': [
        {'command': 'home', 'axes': ['x', 'y']}
    ]}
    key_map[(SCN_ENTER, mod)] = {'key_name': 'NumEnter', 'route': 'printer/printhead', 'tasks': [
        {'command': 'home', 'axes': ['z']}
    ]}

    key_map[(SCN_MINUS, mod)] = {'key_name': 'NumMinus', 'route': 'printer/printhead', 'tasks': [
        {'command': 'jog', 'absolute': False, 'z': -JOG_STEP_Z},
    ]}
    key_map[(SCN_PLUS, mod)] = {'key_name': 'NumPlus', 'route': 'printer/printhead', 'tasks': [
        {'command': 'jog', 'absolute': False, 'z': JOG_STEP_Z},
    ]}

    key_map[(SCN_DIV, mod)] = {'key_name': 'NumDivide', 'func': toggle_bed_temp}
    key_map[(SCN_MULT, mod)] = {'key_name': 'NumMultiply', 'func': toggle_tool_temp}


for i, (py, px), (sy, sx) in zip(SCN_NUMS, BED_POS, JOG_MOV):
    # add absolute positions for leveling
    key_map[(i, NUML_MOD)] = {
        'key_name': 'NumLck{}'.format(i+1),
        'route': 'printer/printhead', 'tasks': [
            {'command': 'jog', 'absolute': True, 'z': JOG_STEP_Z},
            {'command': 'jog', 'absolute': True, 'x': px, 'y': py},
        ]}

    # add relative movements for manual control
    key_map[(i, NUML_OFF)] = {
        'key_name': 'NumOff{}'.format(i+1),
        'route': 'printer/printhead', 'tasks': [
            {'command': 'jog', 'absolute': False, 'x': sx, 'y': sy},
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


def in_bounds(task):
    # {'command': 'jog', 'absolute': True, 'x': px, 'y': py},
    # {'command': 'jog', 'absolute': False, 'x': sx, 'y': sy},
    is_in = True
    if task['command'] == 'jog':
        if task['absolute']:
            is_in = all([
                task.get('x', 0) <= BED_DEPTH,
                task.get('y', 0) <= BED_WIDTH,
                task.get('z', 0) <= MAX_HEIGHT,
            ])
        else:

            is_in = all([])



    return is_in


def enabled(task):
    return operational(task) and in_bounds(task)


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


def handler(event, event_type='down', test_mode=TEST_MODE):

    if event.event_type != event_type:
        return

    logger.debug(vars(event))

    if event.name == 'num lock':
        toggle_num_lock()

    elif not test_mode:
        trigger(event.scan_code, NUM_LOCK)
