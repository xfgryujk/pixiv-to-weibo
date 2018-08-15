#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import base64
import json
import math
import re
import time
from asyncio import get_event_loop, ensure_future, gather, sleep, TimeoutError
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pprint import pprint

from PIL import Image
from aiohttp import ClientSession, ContentTypeError, ClientError

JP_TZ = timezone(timedelta(hours=9))


# https://github.com/xfgryujk/weibo-img-crypto/blob/8083e7288d188e430ba84aa33c2f01afefa90523/src/random.js#L1
class Random:
    def __init__(self, seed=None):
        self._rng_state = [0, 0]
        self._set_rng_state(seed)

    def _set_rng_state(self, seed=None):
        if seed is None:
            seed = str(int(time.time() * 1000))
        else:
            seed = str(seed)
        if re.fullmatch(r'^-?\d{1,10}$', seed) and -0x80000000 <= int(seed) <= 0x7FFFFFFF:
            seed = int(seed)
        else:
            seed = self._hash_code(seed)
        self._rng_state = [seed & 0xFFFF, (seed & 0xFFFFFFFF) >> 16]

    @staticmethod
    def _hash_code(s):
        hash_ = 0
        for c in s:
            hash_ = (hash_ * 31 + ord(c)) & 0xFFFFFFFF
        return hash_

    def random(self):
        """返回[0, 1)"""
        r0 = (18030 * (self._rng_state[0] & 0xFFFF) + ((self._rng_state[0] & 0xFFFFFFFF) >> 16)) | 0
        self._rng_state[0] = r0
        r1 = (36969 * (self._rng_state[1] & 0xFFFF) + ((self._rng_state[1] & 0xFFFFFFFF) >> 16)) | 0
        self._rng_state[1] = r1
        x = (((r0 << 16) & 0xFFFFFFFF) + (r1 & 0xFFFF)) | 0
        return ((x + 0x100000000) if x < 0 else x) * 2.3283064365386962890625e-10

    def randint(self, min_, max_):
        """返回[min, max]的整数"""
        return int(math.floor(min_ + self.random() * (max_ - min_ + 1)))


class RandomSequence:
    def __init__(self, length, seed):
        self._rng = Random(seed)
        self._list = list(range(length))
        self._next_min = 0

    def next(self):
        if self._next_min >= len(self._list):
            self._next_min = 0
        index = self._rng.randint(self._next_min, len(self._list) - 1)
        result = self._list[index]
        self._list[index] = self._list[self._next_min]
        self._list[self._next_min] = result
        self._next_min += 1
        return result


# https://github.com/xfgryujk/weibo-img-crypto/blob/8083e7288d188e430ba84aa33c2f01afefa90523/src/codec.js#L160
def encrypt_image(data, seed=114514):
    f = BytesIO(data)
    img = Image.open(f)
    block_width = img.width // 8
    block_height = img.height // 8
    new_img = Image.new('RGB', (block_width * 8, block_height * 8))
    seq = RandomSequence(block_width * block_height, seed)
    for block_y in range(block_height):
        for block_x in range(block_width):
            index = seq.next()
            new_block_x = index % block_width
            new_block_y = index // block_width
            block = img.crop((block_x * 8, block_y * 8, (block_x + 1) * 8, (block_y + 1) * 8))
            new_img.paste(block, (new_block_x * 8, new_block_y * 8))
    f = BytesIO()
    new_img.save(f, 'JPEG', quality='maximum')  # 大概减少一半文件尺寸
    return f.getvalue()


class PixivApi:
    def __init__(self, cookie):
        self._session = ClientSession(cookies={
            'PHPSESSID': cookie,
        })

    async def close(self):
        await self._session.close()

    async def get_image_info(self):
        async def get_ranking_page(page, mode, content):
            params_ = {
                'mode':    mode,
                'format':  'json',
                'p':       page
            }
            if content:
                params_['content'] = content
            async with self._session.get('https://www.pixiv.net/ranking.php', params=params_) as r:
                data = await r.json()
                # print(data)
            return data['contents']

        params = (
            ('male', ''),             # 受男性欢迎
            ('male_r18', ''),         # 受男性欢迎 R18
            ('daily', 'illust'),      # 今日 插画
            ('daily_r18', 'illust'),  # 今日 插画 R18
        )
        # 每类爬2页
        pages = await gather(*(
            get_ranking_page(page, *param) for page in range(1, 2) for param in params
        ))
        image_info = sum(pages, [])
        image_info = self._process_image_info(image_info)
        # print(image_info)
        return image_info

    @staticmethod
    def _process_image_info(image_info):
        # 过滤BL
        image_info = filter(lambda info: not info['illust_content_type']['bl'], image_info)
        # 去重
        image_info = {
            info['illust_id']: info
            for info in image_info
        }
        # 按排名升序
        image_info = sorted(image_info.values(), key=lambda info: info['rank'])
        return image_info

    async def get_image_data(self, image_info):
        async def get_by_url(url_):
            async with self._session.get(url_, headers={
                'referer': 'https://www.pixiv.net/member_illust.php'
            }) as r_:
                return await r_.read() if r_.status < 400 else None

        date = datetime.fromtimestamp(image_info['illust_upload_timestamp'],
                                      JP_TZ).strftime('%Y/%m/%d/%H/%M/%S')
        illust_id = image_info['illust_id']
        # 最多9图
        urls = [
            f'https://i.pximg.net/img-master/img/{date}/{illust_id}_p{i}_master1200.jpg'
            for i in range(min(9, int(image_info['illust_page_count'])))
        ]
        pprint(urls)
        return await gather(*(
            get_by_url(url) for url in urls
        ))


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


class Pixiv2Weibo:
    CONFIG_PATH = 'config.json'
    CACHE_PATH = 'cache.json'

    def __init__(self):
        self._config = self._load_json(self.CONFIG_PATH, {
            'pixiv_cookie': '',
            'weibo_cookie': ''
        })
        self._cache = None
        self._pixiv = PixivApi(self._config['pixiv_cookie'])
        self._weibo = WeiboApi(self._config['weibo_cookie'])
        # TODO 保持微博session

    async def close(self):
        await gather(self._pixiv.close(), self._weibo.close())

    @staticmethod
    def _load_json(path, default=None):
        try:
            with open(path) as f:
                return json.load(f)
        except FileNotFoundError:
            return default

    async def start(self):
        # 取要发的图信息
        self._cache = await self._load_cache()
        try:
            image_info = self._cache['image_info'][self._cache['next_index']]
        except IndexError:
            print('没图了')
            return
        self._cache['next_index'] += 1
        with open(self.CACHE_PATH, 'w') as f:
            json.dump(self._cache, f)
        print('图片信息：')
        pprint(image_info)

        # 爬图
        image_data = await self._pixiv.get_image_data(image_info)
        image_data = map(encrypt_image, filter(lambda x: x, image_data))
        # for index, data in enumerate(image_data):
        #     with open(str(index) + '.jpg', 'wb') as f:
        #         f.write(data)

        # 上传
        print('正在上传图片')
        futures = []
        for data in image_data:
            futures.append(ensure_future(self._weibo.upload_image(data)))
            # 加密同时上传，而不是全部加密后再全部上传
            await sleep(0)
        image_ids = await gather(*futures)
        image_ids = list(filter(lambda x: x, image_ids))
        print('image_ids：')
        pprint(image_ids)

        # 发微博
        text = (
            f'#{image_info["rank"]} {image_info["title"]}\n'
            f'作者：{image_info["user_name"]}\n'
            f'标签：{",".join(image_info["tags"])}\n'
            f'www.pixiv.net/member_illust.php?mode=medium&illust_id={image_info["illust_id"]}'
        )
        await self._weibo.post_weibo(text, image_ids)
        print('OK')

    async def _load_cache(self):
        # 日本时间中午12点更新
        date = (datetime.now(JP_TZ) - timedelta(hours=12, minutes=10)).strftime('%Y-%m-%d')
        cache = self._load_json(self.CACHE_PATH)
        if cache and cache['date'] == date:
            return cache

        cache = {
            'date':       date,
            'next_index': 0,
            'image_info': await self._pixiv.get_image_info()
        }
        with open(self.CACHE_PATH, 'w') as f:
            json.dump(cache, f)
        return cache


async def main():
    p2w = Pixiv2Weibo()
    await p2w.start()
    await p2w.close()


if __name__ == '__main__':
    get_event_loop().run_until_complete(main())
