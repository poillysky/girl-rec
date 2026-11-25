# 直播录制标准规范

> 版本：v1.0　日期：2026-11-25
> 适用：本项目（基于 DouyinLiveRecorder 逆向资产二次开发）录制引擎
> 强约束：本文档定义的是"标准做法"，代码实现须与之逐条对齐，不得简化。

---

## 一、录制总体逻辑

录制遵循「**底层分片抗中断 + 按单次时长封顶 + 自动合并成品 mp4 + 无缝续录**」四个环节组成的闭环：

```
          ┌──────────────────────────────────────────────────┐
          │  分片录制（ts，抗中断）                            │
          │  ffmpeg -f segment -segment_time 1800 -c:v copy   │
          └───────────────────────┬──────────────────────────┘
                                  │ 累计录满 单次最大时长（默认 3600s = 1 小时）
                                  ▼
          ┌──────────────────────────────────────────────────┐
          │  本批分片 ffmpeg concat 合并 → 一个完整 mp4        │
          │  -c:v copy -c:a copy -movflags +faststart          │
          │  合并成功后删除本批 ts 分片                         │
          └───────────────────────┬──────────────────────────┘
                                  │ 主播仍在直播
                                  ▼
          ┌──────────────────────────────────────────────────┐
          │  重新探测取流 → 开始录制下一批（循环）              │
          └──────────────────────────────────────────────────┘
```

**核心承诺**：

1. 底层**始终分片录制**（ts），中途断流/崩溃最多损失当前一片，绝不整段全毁。
2. 每录满「单次最大时长」**自动合并成一个完整 mp4**，绝不留十几 G 的单文件。
3. 合并完成即**无缝续录下一批**，主播不断播则持续产出每小时一个 mp4。
4. 成品 mp4 一律 **faststart**（索引在文件头），**支持秒开与拖动**。

---

## 二、最终成品格式标准（硬性）

| 指标 | 标准 | 校验方法 |
|---|---|---|
| 容器 | MP4（`ftyp isom … avc1 mp41`） | `xxd` 文件头 |
| **索引位置** | **moov 在文件头（faststart）** | `ffmpeg -v trace -i x.mp4` 见 `moov` 位置 < `mdat` |
| 视频编码 | H.264（copy 直拷，无损） | `ffprobe -show_entries stream=codec_name` |
| 音频编码 | AAC，48kHz，立体声 | `ffprobe` |
| 首帧 | 关键帧（I 帧）→ 秒开立即出画面 | `ffprobe -show_frames` 首个 `key_frame=1` |
| 音画同步 | 差值 < 1s | 视频时长 vs 音频时长 |

> **为什么必须 faststart**：moov 若在文件尾，网络/手机播放必须先下载完整个文件才能开始、拖动卡死。
> `-movflags +faststart` 把索引前移，边下边播、拖动即时响应。这是本项目成品的强制要求。

### 转码 / 合并命令（全部 4 条路径已加 faststart）

```bash
# 分段合并（copy 无损，默认）
ffmpeg -y -f concat -safe 0 -i list.txt -c:v copy -c:a copy \
       -movflags +faststart -f mp4 输出.mp4

# 分段合并（h264 重编码）
ffmpeg -y -f concat -safe 0 -i list.txt -c:v libx264 -preset veryfast -crf 23 \
       -vf format=yuv420p -c:a aac -movflags +faststart -f mp4 输出.mp4

# 单文件转码（copy）
ffmpeg -y -i 输入.ts -c:v copy -c:a copy -movflags +faststart -f mp4 输出.mp4

# 单文件转码（h264）
ffmpeg -y -i 输入.ts -c:v libx264 -preset veryfast -crf 23 \
       -vf format=yuv420p -c:a copy -movflags +faststart -f mp4 输出.mp4
```

---

## 三、录制 ffmpeg 命令标准（逐项对齐原版）

命令顺序固定如下（`-reconnect_*` 系列**必须在 `-i` 之后**，否则报 234 参数错误）：

```
ffmpeg -y -v verbose -rw_timeout {RW} -loglevel error -hide_banner \
  -user_agent {UA} \
  -protocol_whitelist rtmp,crypto,file,http,https,tcp,tls,udp,rtp,httpproxy \
  -thread_queue_size 1024 -analyzeduration {AN} -probesize {PR} \
  -fflags +discardcorrupt -re -i {URL} -bufsize {BS} -sn -dn \
  -reconnect_delay_max 60 -reconnect_streamed -reconnect_at_eof \
  -max_muxing_queue_size {MMQS} -correct_ts_overflow 1 -avoid_negative_ts 1 \
  [格式参数 / 分段参数]
```

### 参数取值

| 参数 | 国内 | 海外（按域名判定） |
|---|---|---|
| `-rw_timeout` | 15000000（15s） | 50000000（50s） |
| `-analyzeduration` | 20000000 | 40000000 |
| `-probesize` | 10000000 | 20000000 |
| `-bufsize` | 8000k | 15000k |
| `-max_muxing_queue_size` | 1024 | 2048 |

**海外判定**：`record_url` 命中以下 20 个域名任一 → 用海外参数：
`www.tiktok.com / play.sooplive.co.kr / m.sooplive.co.kr / www.sooplive.com / m.sooplive.com / www.pandalive.co.kr / www.winktv.co.kr / www.flextv.co.kr / www.ttinglive.com / www.popkontv.com / www.twitch.tv / www.liveme.com / www.showroom-live.com / chzzk.naver.com / m.chzzk.naver.com / live.shopee.* / *.shp.ee / www.youtube.com / youtu.be / www.faceit.com`

### 分段参数（ts）

```
-c:v copy -c:a copy -map 0 -f segment \
-segment_time {分段秒} -segment_format mpegts -reset_timestamps 1
输出名：{base}_%03d.ts
```

### 纯音频平台（猫耳FM / Look直播）

```
MP3：-map 0:a -c:a libmp3lame -ab 320k [-f segment …]
M4A：-map 0:a -c:a aac -bsf:a aac_adtstoasc -ab 320k [-f segment -segment_format mpegts …]
```

> **务必带 `-c:v copy -c:a copy`**：缺了它 ffmpeg 会默认重编码 mpeg2video，报
> "Either both buffer size and max rate or neither must be specified"（退出码 234）。

---

## 四、配置项（DB configs 表，页面可改）

| 配置键 | 当前值 | 含义 |
|---|---|---|
| `录制设置:分段录制是否开启` | 是 | 开启分片（抗中断） |
| `录制设置:视频分段时间(秒)` | 1800 | 30 分钟一片 |
| `录制设置:单次录制最大时长(秒)` | **3600** | **每 1 小时合成一个 mp4** |
| `录制设置:单次录制最大大小(mb)` | 0 | 0=不限（按时长切，不按大小） |
| `录制设置:录制完成后自动转为mp4格式` | 是 | 录完转 mp4 |
| `录制设置:追加格式后删除原文件` | 是 | 合并后删 ts 分片 |
| `录制设置:mp4格式重新编码为h264` | 否 | 否=copy 无损；是=h264 重编码 |
| `录制设置:视频保存格式` | ts | 中间产物格式（ts 抗中断最佳） |
| `录制设置:录制空间剩余阈值(gb)` | 1.0 | 剩余低于此值拒绝开始录制 |
| `录制设置:循环时间(秒)` | 300 | 探测开播间隔 |

> 改「单次录制最大时长」= 改每段 mp4 的时长。设 3600=每 1 小时一个，设 1800=每 30 分钟一个。

---

## 五、健壮性标准（故障处理）

| 场景 | 标准处理 |
|---|---|
| **断流** | `-reconnect_streamed -reconnect_at_eof` 自动重连；重连前**重新探测取流拿最新地址**（旧 m3u8 有时效）；超 5 次置 failed |
| **死流**（300s 无新数据） | 优雅停止当前 ffmpeg → 重连。分段时检测**最新分片**的增长，不查模板路径 |
| **404 页面**（<1KB 含 404 Not Found 标题） | 判废删文件 → 重连 |
| **封禁**（主播违规 status=4） | 暂停 3600s 后重试 |
| **房间不存在/已下架** | 暂停 300s 后重试 |
| **cookie 失效**（连续 5 次风控） | 暂停 600s 并发 cookie_invalid 事件 |
| **磁盘不足** | 录制前预检，低于阈值拒绝开始（不空转） |
| **孤儿 ffmpeg** | 独立进程组（`start_new_session`），停止/重启时 `killpg` 杀整组 + atexit 兜底，绝不残留抢带宽 |
| **小文件**（<1MB，如空流） | 判废删除 |
| **主动停止** | 保留已录内容并合并成 mp4（不留裸 ts） |
| **进程被强杀** | 重启时把磁盘遗留分片合并成 mp4（兜底，不逐片残留） |

---

## 六、自检清单（每次改动录制代码后必须过）

- [ ] ffmpeg 命令中 `-reconnect_*` 全在 `-i` 之后
- [ ] 分段/整段命令都带 `-c:v copy -c:a copy`
- [ ] 转码/合并命令都带 `-movflags +faststart`
- [ ] 成品 mp4 用 `ffmpeg -v trace` 确认 moov 在 mdat 之前
- [ ] 首帧为 I 帧（key_frame=1）
- [ ] 音画时长差 < 1s
- [ ] 分片相关检测（死流/404/大小/后处理）都按实际分片 glob，不查模板路径
- [ ] 封顶合并后能无缝续录下一批
- [ ] 停止/崩溃后无 ffmpeg 残留进程
- [ ] 各平台一条链路：extract（三通道）→ resolve（画质映射+失效降级）→ record_url 择优

---

## 七、验收实测记录（2026-11-25）

以抖音房间 `https://live.douyin.com/26395334526`（主播：郑书一）实测：

- **链路**：extract → status=2、anchor=郑书一、flv+m3u8 全出；resolve 原画 → record_url 正确。
- **时长封顶**：测试配置 60s 封顶 / 30s 分片，连续产出多批：每批精确合并成一个 mp4（60.2s / 90.5s / 90.8s…）。
- **成品校验**：`ftyp → moov(文件头) → mdat`（faststart ✅）；h264 1088×1920 + aac 48kHz 立体声；首帧 I 帧；音画差 0.22s。
- **续录**：封顶合并后日志"开始录制下一批"，无缝续录。
- **无残留**：全程 1 个 ffmpeg 进程，停止后归零。

---

> 本文档为录制引擎的验收基准。代码实现若与本文档冲突，以本文档为准。
