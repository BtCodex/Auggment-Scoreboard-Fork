#!/usr/bin/python3 -I
"""Narrow privileged Wi-Fi operations used by the scoreboard settings UI.

Install a reviewed copy root-owned at /usr/local/libexec/scoreboard-network.
Never sudo a writable copy in the application checkout. No shells, arbitrary
executables, tool flags, action scripts, or filesystem paths are accepted.
"""
import json
import os
import re
import sys
from pathlib import Path

TOOL_DIRS = ('/usr/sbin', '/usr/bin', '/sbin', '/bin')
INTERFACE_PATTERN = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,14}\Z')


def valid_interface(value):
    """Only an actual OS wireless device can be changed through this helper."""
    return bool(INTERFACE_PATTERN.fullmatch(value)) and Path(
        '/sys/class/net', value, 'wireless').is_dir()


def _text(value, maximum):
    return (isinstance(value, str) and 0 < len(value.encode('utf-8')) <= maximum
            and not any(ord(char) < 32 or ord(char) == 127 for char in value))


def _wpa_value(field, value):
    if field == 'key_mgmt':
        return value == 'NONE'
    if field == 'psk' and re.fullmatch(r'[0-9a-fA-F]{64}', value):
        return True
    try:
        decoded = json.loads(value)
    except (ValueError, TypeError):
        return False
    if not isinstance(decoded, str):
        return False
    if field == 'ssid':
        return _text(decoded, 32)
    return field == 'psk' and _text(decoded, 63) and len(decoded) >= 8


def validate_command(argv):
    """Return an allowed tool name and arguments; raise on everything else."""
    if not argv or not all(isinstance(arg, str) and '\x00' not in arg for arg in argv):
        raise ValueError('Invalid network operation')
    tool, args = argv[0], argv[1:]
    allowed = False
    if tool == 'ip':
        allowed = (len(args) == 4 and args[:2] == ['link', 'set']
                   and valid_interface(args[2]) and args[3] == 'up')
    elif tool == 'iw':
        allowed = (len(args) == 3 and args[0] == 'dev'
                   and valid_interface(args[1]) and args[2] == 'scan')
    elif tool == 'iwlist':
        allowed = len(args) == 2 and valid_interface(args[0]) and args[1] == 'scan'
    elif tool == 'nmcli':
        scan = ['--escape', 'no', '-t', '-f', 'SSID,SIGNAL,SECURITY,ACTIVE',
                'device', 'wifi', 'list']
        if args in (scan, scan + ['--rescan', 'yes']):
            allowed = True
        elif len(args) == 5 and args[:2] == ['device', 'set']:
            allowed = valid_interface(args[2]) and args[3:] == ['managed', 'yes']
        elif len(args) == 3 and args[:2] == ['device', 'disconnect']:
            allowed = valid_interface(args[2])
        # Values remain separate argv entries. An SSID starting with '-' is a
        # positional value after 'connect', never a root-executable tool flag.
        elif len(args) in (6, 8) and args[:3] == ['device', 'wifi', 'connect']:
            allowed = (_text(args[3], 32) and args[4] == 'ifname'
                       and valid_interface(args[5]))
            if len(args) == 8:
                allowed = allowed and args[6] == 'password' and _text(args[7], 64)
    elif tool == 'wpa_cli':
        if len(args) >= 3 and args[0] == '-i' and valid_interface(args[1]):
            operation, values = args[2], args[3:]
            if operation in {'scan', 'scan_results', 'add_network', 'list_networks',
                             'disconnect', 'reconfigure', 'save_config'}:
                allowed = not values
            elif operation in {'enable_network', 'disable_network', 'select_network', 'remove_network'}:
                allowed = len(values) == 1 and bool(re.fullmatch(r'[0-9]{1,6}', values[0]))
            elif operation == 'set_network':
                allowed = (len(values) == 3 and bool(re.fullmatch(r'[0-9]{1,6}', values[0]))
                           and _wpa_value(values[1], values[2]))
    if not allowed:
        raise ValueError('Network operation is not permitted')
    return tool, args


def main(argv=None):
    try:
        tool, args = validate_command(sys.argv[1:] if argv is None else argv)
        executable = next((str(Path(directory, tool)) for directory in TOOL_DIRS
                           if Path(directory, tool).is_file()
                           and os.access(Path(directory, tool), os.X_OK)), None)
        if not executable:
            raise ValueError('Required distribution network tool is not installed')
        # Use a known environment and absolute distro binary, never PATH from
        # the web server or caller. Keep credentials out of diagnostics.
        os.execve(executable, [executable] + args,
                  {'PATH': ':'.join(TOOL_DIRS), 'LANG': 'C.UTF-8'})
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
