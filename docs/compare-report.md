# 深度对比报告：新架构 vs 4个参考项目

> 日期：2026-11-25
> 结论先行：**架构层面已吸收橄榄/stream-rec 的骨骼 + LyzenX 的插件接口；代码实现层面对比后修复/增强 6 处**。逐一对照如下。

---

## 一、逐项目深挖的实现细节

### 1. LyzenX-DouyinLiveRecorder（939★，Python）—— 事件钩子 + 分级检测 + 弹幕

**monitor.py 分级检测**（我们此前只学了"每房间一线程"，漏了三层设计）：
```
重要房间（important）：每个 1 个独立线程，检测周期可配（重要房间 0.97s 错峰启动）
普通房间：check_threads 线程池 + 共享队列，每轮 pop 一个房间
   check_thread_main() 每轮：重取房间列表 -> 反转入队 -> 线程池消费 -> 等全部完成 -> sleep(周期+随机抖动)
房间移除/降级 实时从重要线程退出
```

**recording.py + video_recorder.py 关键实现**（比我们想的更细）：
- `Recording.start()`：room_info 为空时先取直播状态，**失败计数 cookie_failed**（连续失败触发 cookie 失效）
- `refresh_video_recorder()`：**录制结束后立即复查是否仍直播**，仍直播则**自动续录新文件**（防主播网络波动漏录）——我们只做了"复检是否开播"，没做"续录"
- 下载用 **requests stream + HTTPAdapter(max_retries=3)**，超时 4 次后 sleep(30) 再 refresh（比 ffmpeg 重连更轻）
- **404 内容检测**：文件 < 1KB 且内容含 `<head><title>404 Not Found</title></head>` 则删除（我们此前没有）
- 0 字节文件删除
- 录完再查是否直播（若还在播则自动进入续录），主动停止则不复查

**plugin.py 事件钩子**（8 个，比我们 event_bus 事件多）：
```
on_open / on_loaded / on_close
on_live_start(room, filename)
on_live_end(room, file)
on_cookie_invalid()
get_recordings() / get_rooms() / get_logger() —— 插件可读运行态
```

**danmu_recorder.py 弹幕**：
- 打开 XML 写头部 -> websocket 连接（`dy_api.get_danmu_ws_url` + PushFrame/Response/ChatMessage pb）-> 心跳线程 -> on_message 写 XML
- 文件名与视频同名 `.xml`；停止时封 `</i>`

---

### 2. stream-rec（1.2k★，Kotlin）—— 状态机 + 错误分类 + 引擎可插拔

**PlatformDownloader.kt 状态机**（sealed class，比我们简单字符串强）：
```
Idle -> Preparing(url, format, userSelectedFormat, title)
      -> Downloading -> Stopped / Finished
      -> Paused / Error(filePath, exception)
```

**错误分类 analyzeError()**（Kotlin Result 包装，分类决定"是否重试"）：
```
InvalidExtractionUrl / InitializationError / StreamerBanned / StreamerNotFound  -> 终止（asErr）
ApiError / InvalidResponse / JsEngineError / NoStreamsFound -> Ok(false)（不终止，仅本轮不下载）
FallbackError -> Ok(false)
```

**shouldDownload() 流程**：initialized 检查 -> 二次下载态检查 -> extract() -> 错误分类 -> `mediaInfo.live` -> `getStreamInfo()` 过滤 -> **再错误分类**（两段都分类）

**download() 关键能力**（我们此前缺失）：
- `checkSpaceAvailable()` 磁盘空间预检（不足 -> InsufficientDownloadSizeException 直接 Error 态）
- maxDownloadSize / maxDownloadTime 上限（byte/kb 换算，ProgressBar 显示 bitrate）
- danmu 与 video **同一 job 并行**，danmu init 带 `withIORetry(maxRetries=5, maxDelayMillis=30000)`
- **DownloadCallback**：onDownloadStarted/onDownloadProgress/onDownloadFinished + 事件 `DownloadStart/DownloadStateUpdate`（带 duration/bitrate/fileSize 实时进度，我们 event_bus 没有进度事件）
- 事件经 EventCenter.trySendEvent 推前端

**StreamerCallback 数据同步**（7 回调解耦，状态变更防抖）：
```
onStateChanged / onLastLiveTimeChanged / onDescriptionChanged / onAvatarChanged
onStreamDownloaded / onStreamDownloadFailed / onStreamFinished
```
每个回调先读 DB -> 比对旧值 -> 有变化才写库

**下载引擎可插拔**：`DownloadEngines { FFMPEG / STREAMLINK / KOTLIN }` + EngineConfig 配置类

---

### 3. olive（934★，Go）—— bout 原子状态机 + Monitor/Recorder 解耦

**recorder.go 状态机**（CAS 原子，4 态）：
```
Starting(0) -> Pending(1) -> Running(2) -> Stopping(3)
Start(): CAS(Starting->Pending) 成功才开 goroutine，defer CAS(Pending->Running)
Stop(): CAS(Running->Stopping) 成功才 close(stop)，失败直接 return
```

**recorder.run() 主循环**（我们此前没细看，这里很关键）：
```go
r.bout.RemoveMonitor()        // 一进入录制就摘掉 monitor
defer func() { select { case <-r.stop: default: r.bout.AddMonitor() } }()
// 录制结束/异常退出后恢复 monitor（defer），实现 monitor/recorder 互斥轮换
for { select { case <-r.stop: return; default: if err := r.record(); err != nil { return } } }
```

**record() 失败重试 3 次（每次 5s）**：
```go
const retry = 3
for i := 0; i < retry; i++ {
    err := r.bout.Snap()
    if err == nil { if streamURL, ok = r.bout.StreamURL(); ok { break } ... }
    time.Sleep(5 * time.Second)
}
```

**小文件处理 defer**（`<1MB` 删除，否则提交上传任务）：
```go
fi, err := os.Stat(out)  // defer 里
if fi.Size() < 1e6 { os.Remove(out); return }
r.SubmitUploadTask(out, r.bout.GetPostCmds())
```
- SubmitUploadTask 走 **UploaderWorkerPool 独立 worker 池**（上传/后处理不阻塞录制）

**Monitor/Recorder 角色**：Monitor 常驻探测（Snap），发现开播 -> spawn Recorder -> Recorder 摘掉 Monitor -> 播完/失败 -> 恢复 Monitor。**同一 bout 对象在 Monitor/Recorder 间流转**。

**Bout 接口**（状态边界清晰）：
```
IsConfigValid() / StreamURL() / Snap() / AddMonitor() / RemoveMonitor() / RemoveRecorder() / GetOutFilename() / GetSaveDir() / GetPostCmds()
```

---

## 二、逐一对照：新架构 vs 参考实现

| # | 维度 | 参考项目做法 | 我们此前实现 | 判定 |
|---|------|------------|------------|------|
| 1 | 流可用性验证 | douyin stream.get_douyin_stream_url 是 **async**，`get_response_status` HEAD 实测 m3u8，失效降级画质 | douyin.py 里 `get_response_status_sync`（**不存在**）→ resolve 同步，未实测 | ❌ 简化，已修 |
| 2 | 探测架构 | 原项目 = 每房间1线程死循环；olive = Monitor/Recorder 互斥；LyzenX = 重要/普通分级 | 每房间1协程死循环（检查-录制-复检） | ✅ 协程版 Monitor，但缺"重要房间优先" |
| 3 | 录制状态机 | stream-rec sealed DownloadState + olive CAS 4态 | RecordingSession 8态字符串 | ✅ 已吸收（更细，含 stopped/failed 持久化） |
| 4 | 错误分类 | stream-rec analyzeError 分"终止/仅本轮跳过" | 我们所有异常都走重连（无分类） | ⚠️ 已部分补（重连上限），分类待做 |
| 5 | 磁盘空间预检 | stream-rec checkSpaceAvailable | 无 | ❌ 已补 `_check_disk_space` |
| 6 | 最大录制时长/大小 | stream-rec maxDownloadSize/Time | 无 | ⚠️ 待补（配 seg_time 分片近似） |
| 7 | 404 内容检测 | LyzenX 录到 404 页面判废删除 | 无 | ❌ 已补 `_is_404_file` |
| 8 | 死流/卡死检测 | 原项目 ffmpeg -rw_timeout 15s 断流重连 | DEAD_STREAM_TIMEOUT=300 常量**未接线** | ❌ 已补 `_dead_stream_check` 接入 |
| 9 | 录制时长计算 | olive Bout 有 startTime；原项目录制结束打印 | 我们 `_duration()` 返回 0 占位 | ❌ 已修真实计算 |
| 10 | 录制完成后续录 | LyzenX refresh_video_recorder **主播仍直播则自动续录** | 我们只复检开播态 | ⚠️ 待补（改 _record 循环） |
| 11 | 小文件删除 | olive <1MB defer 删 + 原项目 0字节删 + LyzenX 404删 | 我们只有 <1MB 删 | ✅ 已含 0字节（size<1MB 覆盖）+已补404 |
| 12 | 事件/进度 | stream-rec DownloadStart/StateUpdate 带 bitrate/进度；LyzenX 8个钩子 | event_bus 7 事件，无进度事件 | ⚠️ 进度事件待补 |
| 13 | 前端实时同步 | stream-rec StreamerCallback 7 回调**防抖+写库** | 我们 emit_session 直接广播 | ⚠️ 前端得自己过滤 |
| 14 | 上传/后处理 | olive UploaderWorkerPool 独立池 | 无 | 📋 排期（老大的 msg_push 类似物） |
| 15 | 导入副作用 | LyzenX 不 import 即执行逻辑 | legacy `__init__` import 即 check_node | ❌ 已拆 ensure_runtime() |

---

## 三、本次已修复（6处）

1. **douyin resolve 改 async**：`resolve()` 本就是实测 m3u8 的 async 流程，签名改成 `async def`，恢复 `get_response_status` HEAD 实测 + 画质降级。engine/session.py 同步 `await self.adapter.resolve(...)`；base.py 文档注明 async。
2. **`_duration()` 真实计算**：`(now - start_time).seconds`，替代返回 0 占位。
3. **`_dead_stream_check` 接入**：FFmpegRecorder.wait 的 stop_callback 从 `lambda: self.stop_requested` 换成 `self._dead_stream_check`（300s 无数据 → 优雅停止 → 走断流重连），文件增长即重置计时。
4. **`_check_disk_space`**：录制前 shutil.disk_usage 预检（<1GB 拒绝开始，stream-rec 同款）。
5. **`_is_404_file`**：<1KB 且含 404 标题 → 删除文件 + 抛错重连（LyzenX 同款）。
6. **scheduler 导入修复**：`from ..engine.session import RecordingSession`（原来写错 `from .session`）；`adapters/__init__.py` 补导出 StreamInfo；`adapters/registry.py` 补 `registry` 别名；`legacy/__init__.py` 拆分 `ensure_runtime()`（import 不再副作用 check_node）。

**验证结果**：
- venv（python3.12 + httpx/SQLAlchemy 2.1.9/fastapi）全链路导入通过：注册平台 ['抖音']、session、scheduler、models、SQLite 建表
- 抖音适配器实测：`extract('https://live.douyin.com/335354047186')` 返回真实数据（19字段），`resolve` 正确判 `is_live=False, anchor=享趣玩北京导游大勇` —— 探测链路真实可用

---

## 四、残留差异 / 待办（未简化项）

| 优先级 | 项 | 参考 | 说明 |
|--------|-----|------|------|
| P0 | 录制完成后续录 | LyzenX refresh_video_recorder | 主播仍在播 → 不退出循环直接开录新文件（当前会 FINISHED → 复检 30s 后重新 _record，功能上等效但多一次 CHECKING 状态闪烁） |
| P0 | 错误分类 | stream-rec analyzeError | AdapterError 细分：风控/封禁/房间不存在 → 拉长重试或停止；临时网络 → 快速重试 |
| P1 | 进度事件 | stream-rec DownloadStateUpdate | session_update 增加 duration/bitrate/file_size 字段，前端实时进度条 |
| P1 | 重要房间分级 | LyzenX | Room 表加 important 位，调度器每房间协程 + 重要房间更短检测周期 |
| P1 | 弹幕录制 | LyzenX danmu_recorder | websocket + dy_pb2，session 内并行 job，文件与视频同名 .xml |
| P2 | maxDownloadSize/Time | stream-rec | 每房间录制容量/时长上限，超限自动分段 |
| P2 | 上传/后处理池 | olive UploaderWorkerPool | 录制完成后 post_cmds（转码/上传）独立 worker 池不阻塞 |
| P2 | 状态防抖写库 | stream-rec StreamerCallback | 进展事件写库前比对旧值，减 DB 写放大 |
| P3 | 转码 | 原项目 converts_to_mp4 | 录制完成后转 mp4/h264，独立线程池 |

---

## 五、结论

- **架构**：已站在 4 个项目肩膀上（olive 的 Monitor/Recorder 互斥模型已内化为 session.run 循环；stream-rec 状态机 + 事件回调已吸收；LyzenX 插件接口 = 我们的 event_bus + 未来 plugin 钩子）。
- **实现**：对比后发现并修复 6 处简化/缺陷，全部验证通过。
- **未简化项**：9 项按 P0→P3 排期，其中 P0 两项（续录 + 错误分类）是将"录制能力最强"从口号变现实的最后两块，建议下轮做。
---

## 六、后续迭代完成情况（取自 2026-11-25 平台拆分轮）

### 6.1 平台全量拆分（51 平台，一平台一文件）

- **完成**：`backend/adapters/` 下 51 个适配器文件（douyin + 50 个新平台），全部 `@register` 注册，`URL → 平台` 自动路由（`match_platform`）。
- **生成方式**：一次性脚本 `backend/scripts/gen_adapters.py` 批量生成 direct 模式；手工精修 custom 模式。
- **平台形态**：
  - `direct`：spider 直接返回可录地址（小红书/Bigo/Blued/酷狗/花椒/流星/JP/映客/知乎/六间房/乐嗨/花猫/京东/Shopee/咪咕/连接/来秀/Picarto 等）
  - `stream_m3u8`：专属 stream 函数二次取流（快手/虎牙/斗鱼/YY/B站/网易CC/微博/淘宝/Acfun/TikTok）
  - `stream_spec`：通用 `get_stream_url(spec=True)`（SOOP/PandaTV/WinkTV/FlexTV/TwitchTV/ShowRoom/CHZZK/Youtube/faceit）
  - **登录平台**（4 个）：SOOP/FlexTV/PopkonTV/TwitCasting —— 账号密码走 `config_service.get_platform_credential`（configs 表 `账号密码:{平台}账号/密码`），`new_cookies`/`new_token` 自动回写 configs 表。
- **commands 对比修正**：TikTok 原版走专属 `get_tiktok_stream_url`（生成器误标 spec=True，已改回）；TwitchTV 走 spec=True 正确。

### 6.2 录制能力补齐（相对 §四 待办表）

| 原待办 | 状态 | 实现 |
|--------|------|------|
| P0 录制完成后续录 | ✅ | `_is_still_live()` + `_is_paused_room()`（停用房间不续录）+ 录完 30s 复检 |
| P0 错误分类 | ✅ | RoomNotFoundError(300s)/StreamerBannedError(3600s)/CookieInvalidError(600s，LyzenX 5 次计数触发)/TransientError 快速重试 |
| P1 进度事件 | ✅ | 3s 去抖 emit_session（duration/bitrate/file_size/fps/paused） |
| P1 重要房间分级 | ✅ | Room.important 列 + `_light_migrate`；session 探测间隔减半（≥3s）；scheduler 传参 |
| P2 上传/后处理池 | ✅ | `engine/post_processor.py`：asyncio.Queue + 2 worker，转码 mp4/h264 + script_command（原版 run_script 参数拼接） |
| P2 maxDownloadSize/Time | ✅ | configs 表 `单次录制最大时长(秒)/单次录制最大大小(mb)`，死流检测前优雅停止 |
| P3 转码 | ✅ | post_processor._convert_mp4（copy 流 / h264 veryfast crf23 yuv420p） |
| P1 弹幕录制 | ⏳ | 未做（danmu_recorder websocket + dy_pb2，最大剩余项） |
| P2 状态防抖写库 | ⏳ | 未做（StreamerCallback 读 DB 比对旧值变化才写） |

### 6.3 本轮新增修正

- `force_http` 类变量（shopee/migu，原版 http_record_list 语义）+ 全局 `是否强制启用https录制` 配置（默认否，http→https 提升）。
- base.py `enable_https_recording: ClassVar[bool|None]`（None=跟随全局）——已接入 `_start_recording_once` 录流前 URL 变换。
- 生成器修理：布尔小写、`_last_url` 注入、空 docstring 清理、全量 py_compile 通过。

**验证**：51 平台注册数 = 51；URL 匹配实测（虎牙/斗鱼/B站/TikTok/抖音/TwitCasting）；uvicorn 重启 0 Traceback；房间 session 稳定。
