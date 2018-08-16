# pixiv-to-weibo
自动转P站图片到微博。图片会使用[weibo-img-crypto](https://github.com/xfgryujk/weibo-img-crypto)的算法加密

## 使用方法
1. 复制一份`config.template.json`并改名为`config.json`
2. 打开`config.json`，填入P站cookie和微博的用户名、密码
3. 设置定时任务执行`main.py`，例如Linux下用cron：
   ```
   */20 * * * * cd /home/ubuntu/pixiv-to-weibo && python3 main.py >out.log 2>&1
   ```
