# -*- coding: utf-8 -*-

import asyncio
import base64
import binascii
import json
import random
import re
from urllib.parse import quote_plus

import rsa
from aiohttp import ClientSession, ContentTypeError, ClientError

# 修复cookie expire星期不能匹配的BUG
import http.cookies
http.cookies.BaseCookie._BaseCookie__parse_string.__defaults__ = (
    re.compile(r"""
        \s*                            # Optional whitespace at start of cookie
        (?P<key>                       # Start of group 'key'
        [""" + http.cookies._LegalKeyChars + r"""]+?   # Any word of at least one letter
        )                              # End of group 'key'
        (                              # Optional group: there may not be a value.
        \s*=\s*                          # Equal Sign
        (?P<val>                         # Start of group 'val'
        "(?:[^\\"]|\\.)*"                  # Any doublequoted string
        |                                  # or
        \w{3,},\s[\w\d\s-]{9,11}\s[\d:]{8}\sGMT  # Special case for "expires" attr
        |                                  # or
        [""" + http.cookies._LegalValueChars + r"""]*      # Any word or empty string
        )                                # End of group 'val'
        )?                             # End of optional value group
        \s*                            # Any number of spaces.
        (\s+|;|$)                      # Ending either at space, semicolon, or EOS.
        """, re.ASCII | re.VERBOSE),   # re.ASCII may be removed if safe.
)


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
        if not await self.restore_session():
            await self.login(username, password)

    async def restore_session(self):
        async with self._session.get('https://weibo.com/') as r:
            return await self.__handle_login_page(str(r.url), await r.text())

    async def __handle_login_page(self, url, res):
        while True:
            # 登录页
            if url.startswith('https://login.sina.com.cn/sso/login.php'):
                next_url = self.__get_next_url(res)

            # 新浪访客系统，用来恢复cookie
            elif url.startswith('https://passport.weibo.com/visitor/visitor'):
                if 'a=enter' in url:
                    next_url = 'https://passport.weibo.com/visitor/visitor?a=restore&cb=restore_back&from=weibo'
                else:
                    res_ = self.__get_jsonp_response(res)
                    next_url = (
                        f'https://login.sina.com.cn/sso/login.php?entry=sso&alt={res_["data"]["alt"]}'
                        f'&returntype=META&gateway=1&savestate={res_["data"]["savestate"]}'
                        f'&url=https%3A%2F%2Fweibo.com%2F%3Fdisplay%3D0%26retcode%3D6102'
                    )

            # 跨域登录广播
            elif url.startswith('https://login.sina.com.cn/crossdomain2.php'):
                async def cross_domain_callback(url_, i):
                    async with self._session.get(url_, params={
                        'callback': 'sinaSSOController.doCrossDomainCallBack',
                        'scriptId': 'ssoscript' + str(i),
                        'client': 'ssologin.js(v1.4.2)'
                    }) as r_:
                        await r_.read()

                url_list = re.search(r'setCrossDomainUrlList\((.*?)\);', res)[1]
                url_list = json.loads(url_list)['arrURL']
                await asyncio.gather(*(
                    cross_domain_callback(url, i) for i, url in enumerate(url_list)
                ))

                next_url = self.__get_next_url(res)

            # 调用parent.sinaSSOController.feedBackUrlCallBack跳转到weibo.com/nguide/interest
            elif url.startswith('https://weibo.com/ajaxlogin.php'):
                res_ = self.__get_jsonp_response(res)
                next_url = res_['redirect']

            # 登录完毕
            elif url.startswith('https://weibo.com'):
                return '/home' in url

            # 未知的地址
            else:
                print('未知的地址：' + url)
                print(res)
                return False

            async with self._session.get(next_url, headers={
                'Referer': url  # 访问visitor?a=restore必须带referer
            }) as r:
                url = str(r.url)
                res = await r.text()

    @staticmethod
    def __get_next_url(html):
        match = re.search(r'location\.replace\([\'"](.*?)[\'"]\)', html)
        return match[1] if match is not None else None

    @staticmethod
    def __get_jsonp_response(js):
        return json.loads(js[js.find('{'): js.rfind('}') + 1])

    async def login(self, username, password):
        print('登录中')
        # URL编码再BASE64编码
        su = base64.b64encode(quote_plus(username).encode()).decode()
        data = await self._pre_login(su)

        async with self._session.post('https://login.sina.com.cn/sso/login.php', params={
            'client': 'ssologin.js(v1.4.19)',
        }, data={
            'entry':       'weibo',
            'gateway':     '1',
            'from':        '',
            'savestate':   '7',
            'qrcode_flag': 'false',
            'useticket':   '1',
            'pagerefer':   'https://login.sina.com.cn/crossdomain2.php?action=logout&'
                           'r=https%3A%2F%2Fpassport.weibo.com%2Fwbsso%2Flogout%3Fr%3'
                           'Dhttps%253A%252F%252Fweibo.com%26returntype%3D1',
            'vsnf':        '1',
            'su':          su,
            'service':     'miniblog',
            'servertime':  data['servertime'],
            'nonce':       data['nonce'],
            'pwencode':    'rsa2',
            'rsakv':       data['rsakv'],
            'sp':          self._get_secret_password(password, data['servertime'],
                                                     data['nonce'], data['pubkey']),
            'sr':          '1366*768',
            'encoding':    'UTF-8',
            'prelt':       '233',
            'url':         'https://weibo.com/ajaxlogin.php?framelogin=1&callback='
                           'parent.sinaSSOController.feedBackUrlCallBack',
            'returntype':  'META',
            'door':        '' if data['showpin'] == 0
                           else await self._input_verif_code(data['pcid'])
        }) as r:
            return await self.__handle_login_page(str(r.url), await r.text())

    async def _pre_login(self, su):
        async with self._session.get('https://login.sina.com.cn/sso/prelogin.php', params={
            'entry':    'weibo',
            'callback': 'sinaSSOController.preloginCallBack',
            'su':       su,
            'rsakt':    'mod',
            'checkpin': '1',
            'client':   'ssologin.js(v1.4.18)'
        }) as r:
            return self.__get_jsonp_response(await r.text())

    async def _input_verif_code(self, pcid):
        async with self._session.get('https://login.sina.com.cn/cgi/pin.php', params={
            'r': random.randint(0, 100000000),
            's': '0',
            'p': pcid
        }) as r:
            img_data = await r.read()
        self._show_image(img_data)
        return input('输入验证码：')

    def _show_image(self, img_data):
        raise NotImplementedError('需要验证码')

    @staticmethod
    def _get_secret_password(password, servertime, nonce, pubkey):
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
                    res = re.search(r'&pid=(.*?)(&|$)', r.headers['Location'])
            except (ClientError, IOError, TimeoutError):
                print('超时')
                continue
            if res is None:
                print(r.headers)
                print(await r.text())
                continue
            return res[1]
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
