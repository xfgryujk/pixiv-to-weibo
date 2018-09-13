#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from asyncio import get_event_loop, ensure_future, gather, sleep
from datetime import datetime, timedelta
from pprint import pprint

from imgcry import encrypt_image
from pixiv import PixivApi, JP_TZ
from weibo import WeiboApi


class Pixiv2Weibo:
    CONFIG_PATH = 'config.json'
    CACHE_PATH = 'cache.json'
    WEIBO_COOKIE_PATH = 'weibo_cookie.pickle'

    def __init__(self):
        self._config = self._load_json(self.CONFIG_PATH, {
            'pixiv_cookie':   '',
            'pixiv_proxy':    '',
            'weibo_username': '',
            'weibo_password': ''
        })
        self._pixiv = PixivApi(self._config['pixiv_cookie'], self._config['pixiv_proxy'])
        self._weibo = WeiboApi()
        try:
            self._weibo.load_cookie(self.WEIBO_COOKIE_PATH)
        except FileNotFoundError:
            pass

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
        # 登录微博
        login_future = ensure_future(self._weibo.login_if_need(
            self._config['weibo_username'], self._config['weibo_password']
        ))

        # 取要发的图信息
        cache = await self._load_cache()
        try:
            image_info = cache['image_info'][cache['next_index']]
        except IndexError:
            print('没图了')
            return
        cache['next_index'] += 1
        with open(self.CACHE_PATH, 'w') as f:
            json.dump(cache, f)
        print('图片信息：')
        pprint(image_info)

        # 爬图
        image_data = await self._pixiv.get_image_data(image_info)
        image_data = map(encrypt_image, filter(lambda x: x, image_data))
        # for index, data in enumerate(image_data):
        #     with open(str(index) + '.jpg', 'wb') as f:
        #         f.write(data)

        await login_future
        self._weibo.save_cookie(self.WEIBO_COOKIE_PATH)

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
