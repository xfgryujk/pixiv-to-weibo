#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微博登录需要验证码时的解决方案，要在GUI环境下运行
"""

import json
from asyncio import get_event_loop
from io import BytesIO

from PIL import Image

from weibo import WeiboApi


class WeiboApiGui(WeiboApi):
    def _show_image(self, img_data):
        img = Image.open(BytesIO(img_data))
        img.show()


async def main():
    with open('config.json') as f:
        config = json.load(f)
    weibo = WeiboApiGui()
    await weibo.login(config['weibo_username'], config['weibo_password'])
    weibo.save_cookie('weibo_cookie.pickle')
    await weibo.close()


if __name__ == '__main__':
    get_event_loop().run_until_complete(main())
