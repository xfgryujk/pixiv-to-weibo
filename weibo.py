# -*- coding: utf-8 -*-

import base64
import binascii
import json
import re
import time
from urllib.parse import quote_plus

import rsa
from aiohttp import ClientSession, ContentTypeError, ClientError
from yarl import URL


class WeiboApi:
    def __init__(self):
        self._session = ClientSession()

    async def close(self):
        await self._session.close()

    def load_cookie(self, path):
        self._session.cookie_jar.load(path)

    def save_cookie(self, path):
        self._session.cookie_jar.save(path)

    async def login_if_need(self, username, password):
        async with self._session.get('https://weibo.com/') as r:
            url = URL(r.url)
        # 被重定向到访客系统
        if url.host != 'weibo.com' or url.path == '/':
            await self.login(username, password)

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
        assert showpin == 0, '需要验证码'

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
            'returntype': 'META'
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

    async def upload_image(self, data):
        # 最多试5次
        for i in range(5):
            try:
                async with self._session.post('https://picupload.weibo.com/interface/pic_upload.php', params={
                    'cb':          'https://weibo.com/aj/static/upimgback.html?_wv=5&callback=STK_ijax_1',
                    'mime':        'image/jpeg',
                    'data':        'base64',
                    'url':         '0',
                    'markpos':     '1',
                    'logo':        '',
                    'nick':        '0',
                    'marks':       '0',
                    'app':         'miniblog',
                    's':           'rdxt',
                    'pri':         'null',
                    'file_source': '1'
                }, data={
                    'b64_data': base64.b64encode(data).decode()
                }, allow_redirects=False) as r:
                    if 'Location' not in r.headers:
                        continue
                    res = re.findall(r'&pid=(.*?)(&|$)', r.headers['Location'])
            except (ClientError, IOError, TimeoutError):
                print('超时')
                continue
            if not res:
                print(r.headers)
                print(await r.text())
                continue
            return res[0][0]
        return None

    async def post_weibo(self, text, image_ids):
        async with self._session.post('https://weibo.com/aj/mblog/add', params={
            'ajwvr': '6',
        }, data={
            'location':       'v6_content_home',
            'appkey':         '',
            'style_type':     '1',
            'tid':            '',
            'pdetail':        '',
            'mid':            '',
            'isReEdit':       'false',
            'gif_ids':        '',
            'rank':           '0',
            'rankid':         '',
            'module':         'stissue',
            'pub_source':     'main_',
            'pub_type':       'dialog',
            'isPri':          'null',
            'text':           text,
            'pic_id':         '|'.join(image_ids),
            'updata_img_num': len(image_ids),
        }, headers={
            'referer': 'https://weibo.com/'
        }) as r:
            try:
                res = await r.json()
            except ContentTypeError:
                print(await r.text())
                return
        if res['code'] != '100000':
            print(res)
