#
# This file is part of raviron. Raviron is free software available under
# the terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2015 the raviron authors. See the file "AUTHORS" for a
# complete list.

import re
import os
import shlex
import subprocess
import textwrap

from . import node, util


# proxy-create command

def create_ssh_keypair(keyname, comment):
    """Create a new ssh keypair."""
    sshdir = os.path.join(util.get_homedir(), '.ssh')
    util.create_directory(sshdir, 0o700)
    keyfile = os.path.join(sshdir, keyname)
    if util.try_stat(keyfile):
        raise RuntimeError('~/.ssh/{} already exists'.format(keyname))
    subprocess.check_call(['ssh-keygen', '-f', keyfile, '-N', "", '-q', '-C', comment])
    os.chmod(keyfile, 0o600)
    os.chmod(keyfile + '.pub', 0o644)
    return keyfile


def create_proxy(proxyname):
    """Create a proxy wrapper."""
    # Running in a software collection?
    enable_scls = []
    scls = os.environ.get('X_SCLS', '')
    for scl in scls.split():
        with open('/etc/scl/conf/{}'.format(scl)) as fin:
            prefix = fin.readline().rstrip()
        enable_scls.append('. {}/{}/enable'.format(prefix, scl))
    if scls:
        enable_scls.append('X_SCLS={}'.format(shlex.quote(scls)))
        enable_scls.append('export X_SCLS')
    else:
        enable_scls.append('# No software collections enabled.')
    enable_scls = '\n'.join(enable_scls)
    # Running in a virtualenv?
    venv = os.environ.get('VIRTUAL_ENV')
    enable_venv = '. {}/bin/activate'.format(venv) if venv else '# No virtualenv enabled.'
    # Create the ~/bin directory if needed
    bindir = os.path.join(util.get_homedir(), 'bin')
    proxyfile = os.path.join(bindir, proxyname)
    util.create_directory(bindir, 0o755)
    contents = textwrap.dedent("""\
            #!/bin/sh
            {}
            {}
            exec raviron proxy-run
            """).format(enable_scls, enable_venv)
    with open(proxyfile, 'w') as fout:
        fout.write(contents)
    os.chmod(proxyfile, 0o700)
    return proxyfile


def install_proxy(pubkey, command):
    """Add a public key to the authorized_keys file."""
    with open(pubkey) as fin:
        keydata = fin.read()
    sshdir = os.path.join(util.get_homedir(), '.ssh')
    authentry = 'no-pty,no-port-forwarding,no-X11-forwarding,no-agent-forwarding'
    authentry += ',command="{}" '.format(command)
    authentry += keydata
    authfile = os.path.join(sshdir, 'authorized_keys')
    with open(authfile, 'a') as fout:
        fout.write(authentry)
    os.chmod(authfile, 0o600)


_key_name = 'id_raviron'
_proxy_name = 'raviron-proxy'

def do_create(env):
    """The `raviron proxy-create` command."""
    keyname = env.config['proxy']['key_name']
    proxyname = env.config['proxy']['proxy_name']
    keyfile = create_ssh_keypair(keyname, proxyname)
    proxyfile = create_proxy(proxyname)
    install_proxy(keyfile + '.pub', proxyfile)
    print('Private key created as: ~/.ssh/{}'.format(keyname))
    print('Proxy created at: ~/bin/{}'.format(proxyname))


# proxy-run command

# These are the virsh commands used by the ssh power driver in Ironic.
# They need to match and be kept up to date with the following file:
# https://github.com/openstack/ironic/blob/master/ironic/drivers/modules/ssh.py#L151

_virsh_commands = [
    ('start', re.compile(' start ([^ ]+)')),
    ('stop', re.compile(' destroy ([^ ]+)')),
    ('reboot', re.compile(' reset ([^ ]+)')),
    ('get_node_macs', re.compile(' dumpxml ([^ ]+) .*mac')),
    ('list_running', re.compile(' list --all.*running')),
    ('list_all', re.compile(' list --all')),
    ('get_boot_device', re.compile(' dumpxml ([^ ]+) .*boot')),
    ('set_boot_device', re.compile(r'boot dev=\\"([^\\]+)\\".* edit ([^ ]+)')),
]


def parse_virsh_command_line():
    """Parse the virsh command line.

    The proxy script is run as a forced command specified in an ssh private
    key. The original command is available in the $SSH_ORIGINAL_COMMAND
    environment variable.
    """
    command = os.environ.get('SSH_ORIGINAL_COMMAND')
    if command is None:
        raise RuntimeError('This command needs to be run through ssh.')
    for cmd, regex in _virsh_commands:
        match = regex.search(command)
        if match:
            return (cmd,) + match.groups()
    raise RuntimeError('unrecognized command: {}'.format(command))


def do_run(env):
    """The `proxy-run` command."""
    log = env.logger
    log.debug('New request, command = {}'.format(os.environ.get('SSH_ORIGINAL_COMMAND', '?')))

    cmdline = parse_virsh_command_line()
    log.info('Parsed command: {}'.format(' '.join(cmdline)))

    env.args['--cached'] = True

    if cmdline[0] == 'start':
        node.do_start(env, cmdline[1])
    elif cmdline[0] == 'stop':
        node.do_stop(env, cmdline[1])
    elif cmdline[0] == 'reboot':
        node.do_reboot(env, cmdline[1])
    elif cmdline[0] == 'list_running':
        node.do_list_running(env, True)
    elif cmdline[0] == 'list_all':
        node.do_list_all(env)
    elif cmdline[0] == 'get_boot_device':
        node.do_get_boot_device(env, cmdline[1])
    elif cmdline[0] == 'set_boot_device':
        node.do_set_boot_device(env, cmdline[2], cmdline[1])
    elif cmdline[0] == 'get_node_macs':
        node.do_get_macs(env, cmdline[1], True)
