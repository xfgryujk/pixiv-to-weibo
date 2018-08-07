#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import base64
import json
import math
import random
import re
import time
from asyncio import get_event_loop, gather
from io import BytesIO

from PIL import Image
from aiohttp import ClientSession, ContentTypeError


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
def encrypt_image(data):
    f = BytesIO(data)
    img = Image.open(f)
    block_width = img.width // 8
    block_height = img.height // 8
    new_img = Image.new('RGBA', (block_width * 8, block_height * 8))
    seq = RandomSequence(block_width * block_height, 114514)
    for block_y in range(block_height):
        for block_x in range(block_width):
            index = seq.next()
            new_block_x = index % block_width
            new_block_y = index // block_width
            block = img.crop((block_x * 8, block_y * 8, (block_x + 1) * 8, (block_y + 1) * 8))
            new_img.paste(block, (new_block_x * 8, new_block_y * 8))
    f = BytesIO()
    new_img.save(f, 'PNG')
    return f.getvalue()


class Pixiv2Weibo:
    CONFIG_PATH = 'config.json'
    CACHE_PATH = 'cache.json'

    def __init__(self):
        self._config = self._load_json(self.CONFIG_PATH, {
            'pixiv_cookie': '',
            'weibo_cookie': ''
        })
        self._cache = None
        self._session = ClientSession(cookies={
            'PHPSESSID': self._config['pixiv_cookie'],
            'SUB':       self._config['weibo_cookie']
        })

    async def close(self):
        await self._session.close()

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
        except IndexError:  # 没图了
            return
        self._cache['next_index'] += 1
        with open(self.CACHE_PATH, 'w') as f:
            json.dump(self._cache, f)
        print('图片信息：')
        print(image_info)

        # 爬图
        image_data = await self._get_image_data(image_info['illust_id'])
        image_data = map(encrypt_image, image_data)
        # for index, data in enumerate(image_data):
        #     with open(str(index) + '.jpg', 'wb') as f:
        #         f.write(data)

        # 上传
        print('正在上传图片')
        image_ids = await gather(*(
            self._upload_image(data) for data in image_data
        ))
        image_ids = list(filter(lambda x: x, image_ids))
        print('image_ids：')
        print(image_ids)

        # 发微博
        text = f'{image_info["title"]} 作者：{image_info["user_name"]} illust_id={image_info["illust_id"]}'
        await self.post_weibo(text, image_ids)

    async def _load_cache(self):
        date = time.strftime('%Y-%m-%d')
        cache = self._load_json(self.CACHE_PATH)
        if cache and cache['date'] == date:
            return cache

        cache = {
            'date':       date,
            'next_index': 0,
            'image_info': await self._get_image_info()
        }
        with open(self.CACHE_PATH, 'w') as f:
            json.dump(cache, f)
        return cache

    async def _get_image_info(self):
        async def get_ranking_page(page):
            async with self._session.get('https://www.pixiv.net/ranking.php', params={
                'mode':   'male_r18',
                'format': 'json',
                'p':      page
            }) as r:
                data = await r.json()
                # print(data)
            return data['contents']

        # 爬3页
        pages = await gather(*(
            get_ranking_page(page) for page in range(1, 4)
        ))
        image_info = sum(pages, [])
        image_info = self._sort_image_info(image_info)
        # print(image_info)
        return image_info

    @staticmethod
    def _sort_image_info(image_info):
        # 前20一定要发，后面随机排序
        image_info = sorted(image_info, key=lambda info: info['rank'])
        rand_list = image_info[20:]
        random.shuffle(rand_list)
        return image_info[:20] + rand_list

    async def _get_image_data(self, illust_id):
        async def get_by_url(url_):
            async with self._session.get(url_, headers={
                'referer': 'https://www.pixiv.net/member_illust.php'
            }) as r_:
                return await r_.read()

        async with self._session.get('https://www.pixiv.net/member_illust.php', params={
            'mode':      'manga',
            'illust_id': illust_id
        }) as r:
            html = await r.text()
        # 最多9图
        urls = re.findall(r'"([^"]*?//i.pximg.net/img-master/img[^"]*?)"', html)[:9]
        print(urls)
        return await gather(*(
            get_by_url(url) for url in urls
        ))

    async def _upload_image(self, data):
        async with self._session.post('https://picupload.weibo.com/interface/pic_upload.php', params={
            'cb':          'https://weibo.com/aj/static/upimgback.html?_wv=5&callback=STK_ijax_1533624300509412',
            'mime':        'image/png',
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
                print(r.headers)
                print(await r.text())
                return None
            res = re.findall(r'&pid=(.*?)(&|$)', r.headers['Location'])
        return res[0][0] if res else None

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


async def main():
    p2w = Pixiv2Weibo()
    await p2w.start()
    await p2w.close()


if __name__ == '__main__':
    get_event_loop().run_until_complete(main())
