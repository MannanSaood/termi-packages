"""Bounded transport retries; seed metadata and archives are verified afterward."""
import os
import re
import subprocess
import time


def download(tag, directory, runner=subprocess.run, sleep=time.sleep):
    if not re.fullmatch(r'candidate-[0-9]+-[0-9]+-[0-9]+', tag):
        raise ValueError('Require a Termi candidate tag')
    command = ['gh', 'release', 'download', tag, '--repo', 'MannanSaood/termi-packages',
               '--pattern', '*.json', '--pattern', '*.deb', '--pattern', '*.tar', '--dir', str(directory)]
    for attempt in range(3):
        env = dict(os.environ)
        if attempt:
            env['GODEBUG'] = env.get('GODEBUG', '') + ',http2client=0'
        result = runner(command + (['--clobber'] if attempt else []), env=env, capture_output=True, text=True)
        if result.returncode == 0:
            return
        message = (result.stderr or '') + (result.stdout or '')
        print(message, flush=True)
        transient = any(s in message.lower() for s in (
            'protocol_error', 'unexpected eof', 'connection reset', 'connection timed out',
            'i/o timeout', 'tls handshake timeout', 'http 502', 'http 503', 'http 504'))
        if not transient or attempt == 2:
            raise subprocess.CalledProcessError(result.returncode, command, output=message)
        print('Retry seed transport with HTTP/2 disabled; hash verification remains mandatory', flush=True)
        sleep(5 * (attempt + 1))
