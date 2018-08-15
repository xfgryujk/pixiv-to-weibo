# -*- coding: utf-8 -*-

import math
import re
import time
from io import BytesIO

from PIL import Image


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
