import datetime
import json
import logging
import os
import socket
import sys
from itertools import product
from pprint import pformat
from functools import wraps

import requests
import yaml

from numcfg import *

logger = logging.getLogger(__name__)
TEST_MODE = '--test' in sys.argv[1:]


try:
    KDSETLED = 0x4B32
    NUM_LED = 0x02
    import fcntl
    fd = os.open('/dev/console', os.O_NOCTTY)
    fcntl.ioctl(fd, KDSETLED, NUM_LED)
    logger.warning('turning on num-lock led!')
except (ModuleNotFoundError, PermissionError):
    fd = fcntl = None
    logger.warning('cannot control num-lock led!')


if OCTO_HOST is None:
    OCTO_HOST = socket.gethostname()

if API_KEY is None:
    CFG_FILE = '/home/pi/.octoprint/config.yaml'
    logger.debug('reading config : %s', CFG_FILE)
    with open(CFG_FILE) as fp:
        CONFIG = yaml.safe_load(fp)

API_URL = 'http://{host}:{port}/api'.format(host=OCTO_HOST, port=OCTO_PORT)
HEADERS = {'Content-Type': 'application/json', 'X-Api-Key': CONFIG['api']['key']}

# leveling positions
POS_WIDTH = [SIDE_DIST, BED_WIDTH/2, BED_WIDTH - SIDE_DIST]
POS_DEPTH = [SIDE_DIST, BED_DEPTH/2, BED_DEPTH - SIDE_DIST]
BED_POS = list(product(POS_DEPTH, POS_WIDTH))
logger.debug('bed positions : %s', BED_POS)

JOG_MOV = list(product([-JOG_STEP_Y, 0, JOG_STEP_Y], [-JOG_STEP_X, 0, JOG_STEP_X]))
logger.debug('jog movements : %s', JOG_MOV)

LED_STATE = True    # current state (toggled)
LED_ON = True       # numlock on
LED_OFF = False     # numlock off

LAST_CONNECT = datetime.datetime.now() - datetime.timedelta(days=1)
CONNECT_TIMEOUT = datetime.timedelta(seconds=10)


def api_request(func, route, data=None, headers=HEADERS):
    url = '{apiurl}/{route}'.format(apiurl=API_URL, route=route)
    data = json.dumps(data) if not isinstance(data, str) else data
    logger.debug('request (%s): %s',func.__name__, json.dumps(dict(url=url, data=data, headers=headers), indent=4))
    return func(url, data=data, headers=headers)


def api_get(route, data=None, headers=HEADERS):
    return api_request(requests.get, route, data, headers)


def api_post(route, data=None, headers=HEADERS):
    return api_request(requests.post, route, data, headers)


def get_connection_status():
    status = api_get('connection', {'exclude': 'sd'})
    logger.debug('connection = {}'.format(json.dumps(status.json(), indent=4)))
    return status.json()


def is_connected():
    current_status = get_connection_status().get('current')
    is_conn = current_status and all(current_status.values())
    logger.debug('connected = {}'.format(is_conn))
    return is_conn


def connect_printer(timeout=CONNECT_TIMEOUT):
    global LAST_CONNECT
    is_conn = is_connected()
    if not is_conn and datetime.datetime.now() - LAST_CONNECT > timeout:
        LAST_CONNECT = datetime.datetime.now()
        api_post('connection', {'command': 'connect'})
        is_conn = is_connected()
    return is_conn


def connected(autoconnect=True, timeout=CONNECT_TIMEOUT):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if is_connected() or (autoconnect and connect_printer(timeout=timeout)):
                return func(*args, **kwargs)
            else:
                logger.warning('printer is not connected!')
        return wrapper
    return decorator


@connected()
def get_printer_status():
    res = api_get('printer', {'exclude': 'temperature,sd'})
    logger.debug('response = %s', res)
    try:
        return res.json()
    except Exception as e:
        logger.error('%s: %s', e.__class__.__name__, e)


def toggle_led_state():
    if fd and fcntl:
        global LED_STATE
        LED_STATE = not LED_STATE
        logger.info('turning led %s', 'on' if LED_STATE else 'off')
        fcntl.ioctl(fd, KDSETLED, NUM_LED if LED_STATE else 0)
    else:
        logger.warning('cannot control num-lock led!')


@connected()
def disable_steppers():
    api_post('printer/command', {'command': 'M18'})


@connected()
def toggle_bed_temp(bed_is_on=None):

    if bed_is_on is None:
        status = api_get('printer/bed').json()
        logger.debug('bed_temp = %s', status)
        bed_is_on = status['bed']['target'] == BED_ON_TEMP

    bed_temp = 0 if bed_is_on else BED_ON_TEMP
    api_post('printer/bed', {'command': 'target', 'target': bed_temp})


@connected()
def toggle_tool_temp(tool_is_on=None, tool='tool0'):

    if tool_is_on is None:
        status = api_get('printer/tool').json()
        logger.debug('tool_temp = %s', status)
        tool_is_on = status[tool]['target'] == TOOL_ON_TEMP

    tool_temp = 0 if tool_is_on else TOOL_ON_TEMP
    api_post('printer/tool', {'command': 'target', 'targets': {tool: tool_temp}})


key_map = {}

# LED_ON: use +/- to move z-axis up / down
key_map[(SCN_MINUS, LED_ON)] = {'key_name': 'NumMinus', 'route': 'printer/printhead', 'tasks': [
    {'command': 'jog', 'absolute': False, 'z': -JOG_STEP_Z},
]}
key_map[(SCN_PLUS, LED_ON)] = {'key_name': 'NumPlus', 'route': 'printer/printhead', 'tasks': [
    {'command': 'jog', 'absolute': False, 'z': JOG_STEP_Z},
]}

# LED_ON: use +/- to move z-axis up / down
key_map[(SCN_MINUS, LED_OFF)] = {'key_name': 'NumMinus', 'route': 'printer/tool', 'tasks': [
    {'command': 'extrude', 'amount': -EXTRUDE_STEP},
]}
key_map[(SCN_PLUS, LED_OFF)] = {'key_name': 'NumPlus', 'route': 'printer/tool', 'tasks': [
    {'command': 'extrude', 'amount': EXTRUDE_STEP},
]}

# add for both numlock on and off
for led_state in (LED_ON, LED_OFF):
    key_map[(SCN_0, led_state)] = {'key_name': 'Num+0', 'route': 'printer/printhead', 'tasks': [
        {'command': 'home', 'axes': ['x', 'y', 'z']}
    ]}
    key_map[(SCN_DOT, led_state)] = {'key_name': 'NumDot', 'route': 'printer/printhead', 'tasks': [
        {'command': 'home', 'axes': ['x', 'y']}
    ]}
    key_map[(SCN_ENTER, led_state)] = {'key_name': 'NumEnter', 'route': 'printer/printhead', 'tasks': [
        {'command': 'home', 'axes': ['z']}
    ]}

    key_map[(SCN_DIV, led_state)] = {'key_name': 'NumDivide', 'func': toggle_bed_temp}
    key_map[(SCN_MULT, led_state)] = {'key_name': 'NumMultiply', 'func': toggle_tool_temp}
    key_map[(SCN_BCKSP, led_state)] = {'key_name': 'Backspace', 'func': disable_steppers}


for i, (py, px), (sy, sx) in zip(SCN_NUMS, BED_POS, JOG_MOV):
    # add absolute positions for leveling
    key_map[(i, LED_ON)] = {
        'key_name': 'NumLck{}'.format(i+1),
        'route': 'printer/printhead', 'tasks': [
            {'command': 'jog', 'absolute': True, 'z': POS_HEIGHT},
            {'command': 'jog', 'absolute': True, 'x': px, 'y': py},
        ]
    }

    # add relative movements for manual control
    key_map[(i, LED_OFF)] = {
        'key_name': 'NumOff{}'.format(i+1),
        'route': 'printer/printhead', 'tasks': [
            {'command': 'jog', 'absolute': False, 'x': sx, 'y': sy},
        ]
    }

logger.debug('registered keys: %s', pformat(key_map, indent=4))


@connected()
def trigger(key, mod, **kwargs):
    action = key_map.get((key, mod))

    if action is None:
        logger.debug('nothing to do for key=%s mod=%s', key, mod)

    else:
        logger.debug('action = {}'.format(json.dumps(action, indent=4, default=str)))

        func = action.get('func')
        if func is not None:
            func(**kwargs)

        else:
            for data in action['tasks']:
                api_post(action['route'], data)


def keypress_handler(event, event_type='down', test_mode=TEST_MODE):

    if event.event_type != event_type:
        return

    logger.debug(vars(event))

    if event.name == 'num lock':
        toggle_led_state()

    elif not test_mode:
        trigger(event.scan_code, LED_STATE)
