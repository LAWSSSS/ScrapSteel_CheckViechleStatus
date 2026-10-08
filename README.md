# 永锋废钢检判开始提醒

1# 工位没有车时，检判页显示「空闲」，车牌是 `--`。有车开始检判后，接口里会出现车牌和车次号。这个程序每隔几秒看一次这个状态。一旦检判开始，就弹出一个红色窗口，并循环播放提示音。

窗口不会自动关掉。必须点「我已查看并记录，关闭提醒」。右上角小窗只表示监控还在跑，点「退出监控」才会结束程序。

需要先连上永锋 VPN，否则访问不到检判系统。

## 另一台电脑怎么跑

1. 安装 [Python 3.12](https://www.python.org/downloads/)。Mac 安装包自带可用的窗口库。Windows 安装时勾选 **tcl/tk**。不要用 Mac 自带的 `/usr/bin/python3`，它的窗口库太旧，弹出来会是一块空白。
2. 克隆这个仓库。
3. 在仓库根目录复制配置并填入工号、密码：

```bash
cp config.example.json config.json
```

```json
{
  "base_url": "http://vision.lg.china-yongfeng.com/srape-steel",
  "employee_id": "你的工号",
  "password": "你的密码",
  "station_numbers": [1],
  "poll_interval_seconds": 3,
  "request_timeout_seconds": 8
}
```

`station_numbers` 是要盯的工位。只看 1 号工位就写 `[1]`。

4. 连上永锋 VPN 后启动：

- Mac：双击 `启动提醒.command`。若没反应，右键该文件，选「打开」。
- Windows：双击 `启动提醒.bat`。

`config.json` 不会被提交。每台电脑各自留一份。

## 它在看什么

检判页上的「空闲」不是单独的标志。页面请求 `getIntelliHomePageInfo`，用返回的 `stationInfoDTOList` 画工位。列表里没有这台工位，或没有车牌、状态也不是「质检中 / 暂停」时，页面就画成「空闲」。

程序登录后轮询同一个接口。某一工位第一次出现有效车次（优先用 `flowCode`）时提醒一次。同一车次重复出现不会再响。点过「已记录」之后，这个车次号会被记住，重启也不会再弹。没点就退出的，下次启动还会把这张提醒拉回来。
