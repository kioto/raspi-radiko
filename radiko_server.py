# -*- coding:utf-8 -*-

import os
import re
from pathlib import Path
import socket
import subprocess
from subprocess import Popen, PIPE, DEVNULL


PLAYER_URL = 'http://radiko.jp/apps/js/flash/myplayer-release.swf'
OUTDIR = Path('radio')
PID = os.getpid()
PLAYER_FILE = OUTDIR.joinpath('player.swf')
KEY_FILE = OUTDIR.joinpath('authkey.png')
AUTH1_FMS_FILE = OUTDIR.joinpath('auth1_fms_'+str(PID))
AUTH2_FMS_FILE = OUTDIR.joinpath('auth2_fms_'+str(PID))


class RadikoServer(object):

    def __init__(self):
        if not OUTDIR.is_dir():
            OUTDIR.mkdir()

        self.set_player()
        self.set_keydata()
        self.set_areaid()
        print(self.areaid)

    def set_player(self):
        """playerファイルを取得
        """
        if not PLAYER_FILE.exists():
            print('Get player file')
            cmd = ['wget', '-q', '-O', str(PLAYER_FILE), str(PLAYER_URL)]
            subprocess.call(cmd)

    def set_keydata(self):
        """keyファイルを取得
        """
        if not KEY_FILE.exists():
            print('Get key file')
            cmd = ('swfextract', '-b', '12', str(PLAYER_FILE),
                   '-o', str(KEY_FILE))
            subprocess.call(cmd)

    def set_areaid(self):
        # auth1_fmsを取得
        if AUTH1_FMS_FILE.exists():
            print('Remove', AUTH1_FMS_FILE)
            AUTH1_FMS_FILE.unlink()

        print('Get', AUTH1_FMS_FILE)
        cmd = ['wget', '-q',
               '--header="pragma: no-cache"',
               '--header="X-Radiko-App: pc_ts"',
               '--header="X-Radiko-App-Version: 4.0.1"',
               '--header="X-Radiko-User: test-stream"',
               '--header="X-Radiko-Device: pc"',
               "--post-data='\\r\\n'",
               '--no-check-certificate',
               '--save-headers',
               '-O', str(AUTH1_FMS_FILE),
               'https://radiko.jp/v2/api/auth1_fms']
        subprocess.run(' '.join(cmd), shell=True)

        # パラメータを取得
        authtoken = ''
        key_offset = ''
        key_length = ''
        with open(AUTH1_FMS_FILE, 'r') as f:
            for line in f.read().splitlines():
                if re.match('x-radiko-authtoken', line, re.IGNORECASE):
                    authtoken = re.sub(r'^.*=', '', line)
                elif re.match('x-radiko-keyoffset', line, re.IGNORECASE):
                    key_offset = re.sub(r'^.*=', '', line)
                elif re.match('x-radiko-keylength', line, re.IGNORECASE):
                    key_length = re.sub(r'^.*=', '', line)

        self.authtoken = authtoken

        AUTH1_FMS_FILE.unlink()

        # パーシャルキーの取得
        cmd = ('dd', 'if='+str(KEY_FILE), 'bs=1', 'skip='+key_offset,
               'count='+key_length, '2> /dev/null | base64')
        pc = subprocess.run(' '.join(cmd), shell=True, stdout=subprocess.PIPE)
        partial_key = pc.stdout.decode().rstrip()

        # auth2_fmsの取得
        print('Get', AUTH2_FMS_FILE)
        cmd = ('wget', '-q',
               '--header="pragma: no-cache"',
               '--header="X-Radiko-App: pc_1"',
               '--header="X-Radiko-App: pc_ts"',
               '--header="X-Radiko-App-Version: 4.0.1"',
               '--header="X-Radiko-Device: pc"',
               '--header="X-Radiko-AuthToken: '+authtoken+'"',
               '--header="X-Radiko-PartialKey: '+partial_key+'"',
               "--post-data='\\r\\n'",
               '--no-check-certificate',
               '-O', str(AUTH2_FMS_FILE),
               'https://radiko.jp/v2/api/auth2_fms')
        subprocess.run(' '.join(cmd), shell=True)

        # エリアIDの習得
        areaid = ''
        with open(AUTH2_FMS_FILE, 'r') as f:
            for line in f.read().splitlines():
                if ',' in line:
                    areaid = line.split(',')[0]
        AUTH2_FMS_FILE.unlink()

        self.areaid = areaid

    def play_radio(self, ch):
        """ラジオを再生
        """
        # チャンネルファイルを取得
        channel_file = OUTDIR.joinpath(ch+'.xml')
        cmd = ('wget', '-q',
               f'"http://radiko.jp/v2/station/stream/{ch}.xml"',
               '-O', str(channel_file))
        subprocess.run(' '.join(cmd), shell=True)

        # stream urlを取り出し
        stream_url = ''
        with open(channel_file, 'r') as f:
            for line in f.read().splitlines():
                if '<item>' in line:
                    stream_url = re.sub('^.*<item>', '', line)
                    stream_url = re.sub('</item.*$', '', stream_url)
                    break

        channel_file.unlink()

        # パラメータ取り出し
        p = re.match(r'^(.*)://(.*?)/(.*)/(.*?)$', stream_url)
        serverurl = f'{p[1]}://{p[2]}'
        app = p[3]
        playpath = p[4]
        proc1 = Popen(('rtmpdump', '-v',
                       '-r', serverurl,
                       '--app', app,
                       '--playpath',  playpath,
                       '-W', PLAYER_URL,
                       '-C', 'S:""', '-C', 'S:""', '-C', 'S:""',
                       '-C', f'S:{self.authtoken}',
                       '--live'), stdout=PIPE)
        proc2 = Popen(('mplayer', '-'), stdin=proc1.stdout, stdout=DEVNULL)
        print('Done')


    def run(self):
        self.play_radio('FMJ')
        print('Running...')
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            # IPアドレスとポートを設定
            s.bind(('0.0.0.0', 50007))
            # 1 接続
            s.listen(1)
            # connectionするまで待つ
            while True:
                # 誰かがアクセスしてきたら、コネクションとアドレスを入れる
                conn, addr = s.accept()
                with conn:
                    while True:
                        # データを受け取る
                        data = conn.recv(1024)
                        if not data:
                            break
                        print('data : {}, addr: {}'.format(data, addr))
                        resv_msg = data.decode()
                        if 'get areaid' == resv_msg:
                            send_msg = 'areaid=' + self.areaid
                            print('send:', send_msg)
                            conn.sendall(send_msg.encode())
                        elif 'radio ' in resv_msg:
                            ch = re.sub(r'^.* ', '', resv_msg)
                            self.play_radio(ch)
                            conn.sendall(ch.encode())
                        else:
                            conn.sendall(b'Unknown: ' + data)


if __name__ == '__main__':
    rs = RadikoServer()
    rs.run()
