# Copyright (c) 2021 TurnkeyLinux <admin@turnkeylinux.org>
#
# turnkey-chroot is open source software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 3 of the
# License, or (at your option) any later version.

import os
from os.path import abspath, join, realpath
import shlex
import subprocess
from contextlib import contextmanager

from typing import Dict, Optional


class MountError(Exception):
    pass

def is_mounted(path: os.PathLike) -> bool:
    ''' determines if a given path is currently mounted.

    This method supports any path-like object (any object which implements the
    os.PathLike interface, this includes `str`, `bytes` and path objects
    provided by `pathlib` in the standard library.
    '''
    raw_path: Union[str, bytes] = os.fspath(path)
    mode = 'rb' if isinstance(raw_path, bytes) else 'r'
    sep = b' ' if isinstance(raw_path, bytes) else ' '
    with open('/proc/mounts', mode) as fob:
        for line in fob:
            host, guest, *others = line.split(sep)
            if guest == path:
                return True
    return False

@contextmanager
def mount(target: os.PathLike, environ: Optional[Dict[str, str]] = None):
    '''magic mount context manager

    Usage:

        >>> with chroot.mount('/path/to/chroot') as mnt:
        >>>     assert mnt.path == '/path/to/chroot'
        >>>     assert mnt.run(['ls', '-la', '/proc']).returncode == 1
        >>>     assert os.path.exists('/path/to/chroot/proc')

    Args:
        target: either a `MagicMounts` object or a path

    Yields:
        a `Chroot` object representing a mounted chroot at the given location
        
    '''
    yield Chroot(target, environ)

class MagicMounts:
    '''MagicMounts: An object which manages mounting/unmounting a chroot.

    You *probably* don't want to use this object directly but rather the `mount`
    context manager, or the `Chroot` object.
    '''
    def __init__(self, root: os.PathLike = "/"):
        root = os.fspath(abspath(root))

        self.path_proc = join(root, "proc")
        self.path_dev_pts = join(root, "dev/pts")

        self.mounted_proc_myself = False
        self.mounted_devpts_myself = False

        self.mount()

    def mount(self):
        ''' mount this chroot

        Raises:
            MountError: An error occured while trying to mount chroot
        '''
            
        if not is_mounted(self.path_proc):
            try:
                subprocess.run(['mount', '-t', 'proc', 'proc-chroot',
                    self.path_proc], check=True)
            except subprocess.CalledProcessError as e:
                raise MountError(*e.args) from e
            self.mounted_proc_myself = True

        if not is_mounted(self.path_dev_pts):
            try:
                subprocess.run(['mount', '-t', 'devpts', 'devpts-chroot',
                    self.path_dev_pts], check=True)
            except subprocess.CalledProcessError as e:
                raise MountError(*e.args) from e
            self.mounted_devpts_myself = True

    def umount(self):
        ''' un-mount this chroot

        Raises:
            MountError: An error occured while trying to un-mount chroot
        '''
        if self.mounted_devpts_myself:
            try:
                subprocess.run(['umount', self.path_dev_pts], check=True)
            except subprocess.CalledProcessError as e:
                raise MountError(*e.args) from e
            self.mounted_devpts_myself = False

        if self.mounted_proc_myself:
            try:
                subprocess.run(['umount', self.path_proc], check=True)
            except subprocess.CalledProcessError as e:
                raise MountError(*e.args) from e
            self.mounted_proc_myself = False

    def __del__(self):
        self.umount()

class Chroot:
    '''represents a chroot on your system that you can run commands inside.
    This class automatically attempts to mount the given chroot.

    Example usage:

        >>> foo = Chroot('/path/to/chroot', { 'ENVVAR': 'bar' })
        >>> assert 'ENVVAR=bar' in foo.run(['env'], text=True).stdout
    '''
    def __init__(
            self, newroot: os.PathLike,
            environ: Optional[Dict[str, str]] = None):

        if environ is None:
            environ = {}
        self.environ = {
            'HOME': '/root',
            'TERM': os.environ['TERM'],
            'LC_ALL': 'C',
            'PATH': "/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/bin:/usr/sbin"
        }
        self.environ.update(environ)

        self.path = realpath(newroot)
        self.magicmounts = MagicMounts(self.path)

    def _prepare_command(self, *command):
        env = ['env', '-i', *(
            shlex.quote(name + "=" + val)
                for name, val in self.environ.items())]
        command = [shlex.quote(part) for part in command]
        return [
            'chroot', self.path,
            'sh', '-c',
            ' '.join(env) + ' ' + ' '.join(command)
        ]
    
    def system(self, *command) -> int:
        """execute system command in chroot

        roughly analagous to `os.system` except within the context of a chroot
        (uses subprocess internally)

        Args:
            *command: command to run inside a chroot followed by args

        Returns:
            returncode of process as an int 

        Raises:
            FileNotFoundError: chroot program doesn't exist
        """

        return subprocess.run(self._prepare_command(*command)).returncode

    def run(self, command, *args, **kwargs) -> subprocess.CompletedProcess:
        """execute system command in chroot

        roughly analagous to `subprocess.run` except within the context of a
        chroot

        Args:
            command: command to run inside a chroot followed by args as a list
                e.g. ``['ls', '-la', '/tmp']``

            *args: forwarded to subprocess.run
            **kwargs: forwarded to subprocess.run


        Returns:
            The completed process object (`subprocess.CompletedProcess`) of
            the chroot call. Note: this applies to the `chroot` command, not
            the inner command. As a result some attributes of thi may be
            counter-intuitive.

        Raises:
            FileNotFoundError: chroot program doesn't exist
            CalledProcessError: check=True was passed in kwargs and
                exitcode != 0
        """
        return subprocess.run(self._prepare_command(*command), *args, **kwargs)

