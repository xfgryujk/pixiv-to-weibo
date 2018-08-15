# -*- coding: utf-8 -*-

import base64
import re

from aiohttp import ClientSession, ContentTypeError, ClientError


class WeiboApi:
    def __init__(self, cookie):
        self._session = ClientSession(cookies={
            'SUB': cookie,
        })

    async def close(self):
        await self._session.close()

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
