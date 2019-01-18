#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微博登录需要验证码时的临时解决方案
"""

import base64
import binascii
import json
import re
from asyncio import get_event_loop
from io import BytesIO
from random import randint
from urllib.parse import quote_plus

import rsa
from PIL import Image
from aiohttp import ClientSession


class WeiboApi:
    def __init__(self):
        self._session = ClientSession()

    async def close(self):
        await self._session.close()

    def save_cookie(self, path):
        self._session.cookie_jar.save(path)

    # https://github.com/xchaoinfo/fuck-login/blob/master/007%20weibo.com/weibo.com.py
    async def login(self, username, password):
        print('登录中')
        su = self._get_su(username)
        sever_data = await self._pre_login(su)
        servertime = sever_data['servertime']
        nonce = sever_data['nonce']
        rsakv = sever_data['rsakv']
        pubkey = sever_data['pubkey']
        showpin = sever_data['showpin']
        password_secret = self._get_password(password, servertime, nonce, pubkey)
        door = '' if showpin == 0 else await self._input_verif_code(sever_data['pcid'])

        async with self._session.post('http://login.sina.com.cn/sso/login.php', params={
            'client': 'ssologin.js(v1.4.18)',
        }, data={
            'entry':      'weibo',
            'gateway':    '1',
            'from':       '',
            'savestate':  '7',
            'useticket':  '1',
            'pagerefer':  'http://login.sina.com.cn/sso/logout.php?entry=miniblog'
                          '&r=http%3A%2F%2Fweibo.com%2Flogout.php%3Fbackurl',
            'vsnf':       '1',
            'su':         su,
            'service':    'miniblog',
            'servertime': servertime,
            'nonce':      nonce,
            'pwencode':   'rsa2',
            'rsakv':      rsakv,
            'sp':         password_secret,
            'sr':         '1366*768',
            'encoding':   'UTF-8',
            'prelt':      '115',
            'url':        'http://weibo.com/ajaxlogin.php?framelogin=1&callback='
                          'parent.sinaSSOController.feedBackUrlCallBack',
            'returntype': 'META',
            'door':       door
        }) as r:
            res = await r.text()
        url = re.findall(r'location\.replace\([\'"](.*?)[\'"]\)', res)[0]

        async with self._session.get(url) as r:
            await r.read()

    @staticmethod
    def _get_su(username):
        """URL编码再BASE64编码"""
        return base64.b64encode(quote_plus(username).encode()).decode()

    async def _pre_login(self, su):
        async with self._session.get('http://login.sina.com.cn/sso/prelogin.php', params={
            'entry':    'weibo',
            'callback': 'sinaSSOController.preloginCallBack',
            'su':       su,
            'rsakt':    'mod',
            'checkpin': '1',
            'client':   'ssologin.js(v1.4.18)'
        }) as r:
            res = await r.text()
        res = res[res.find('{'): res.rfind('}') + 1]
        return json.loads(res)

    @staticmethod
    def _get_password(password, servertime, nonce, pubkey):
        key = rsa.PublicKey(int(pubkey, 16), 65537)
        res = rsa.encrypt(f'{servertime}\t{nonce}\n{password}'.encode(), key)
        res = binascii.b2a_hex(res)
        return res.decode()

    async def _input_verif_code(self, pcid):
        async with self._session.get('https://login.sina.com.cn/cgi/pin.php', params={
            'r': randint(0, 100000000),
            's': '0',
            'p': pcid
        }) as r:
            img_data = await r.read()
        img = Image.open(BytesIO(img_data))
        img.show()
        return input('输入验证码：')


async def main():
    with open('config.json') as f:
        config = json.load(f)
    weibo = WeiboApi()
    await weibo.login(config['weibo_username'], config['weibo_password'])
    weibo.save_cookie('weibo_cookie.pickle')
    await weibo.close()


if __name__ == '__main__':
    get_event_loop().run_until_complete(main())
