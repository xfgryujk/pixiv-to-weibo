# -*- coding: utf-8 -*-

from asyncio import gather
from datetime import datetime, timedelta, timezone
from pprint import pprint

from aiohttp import ClientSession
from yarl import URL

JP_TZ = timezone(timedelta(hours=9))


class PixivApi:
    def __init__(self, cookie, proxy=None):
        self._session = ClientSession()
        self._session.cookie_jar.update_cookies({
            'PHPSESSID': cookie,
        }, URL('https://www.pixiv.net'))
        self._proxy = proxy or None

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
            async with self._session.get('https://www.pixiv.net/ranking.php', params=params_,
                                         proxy=self._proxy) as r:
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
            }, proxy=self._proxy) as r_:
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
