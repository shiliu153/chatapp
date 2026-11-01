# 语音录音交互打磨（Web + App）设计

> 日期：2026-11-01
> 状态：已获用户批准（2026-11-01，路线 A）
> 关联：`docs/superpowers/specs/2026-10-27-im-voice-messages-design.md`（语音消息本体，已交付）

## 1. 背景

`CLAUDE.md`「下一步」第 3 条写的是：

> **Web 语音前置已具备**：HTTPS 已上线，`getUserMedia` 可用；但代码里麦克风入口仍**隐藏**，要放开需单独改一版。

这条描述已经过时。核实后的事实是：**Web 麦克风入口早在 2026-10-27 就随语音消息一起交付并上线了**，用户点得到、也能录。真正的问题不是"没入口"，而是"入口做得糙"——存在四个会直接伤到用户的缺陷。

因此本期的目标从"放开入口"改为：**把录音交互打磨到两端一致、可解释、不丢用户的声音**。

## 2. 现状核查

### 2.1 入口确实已经放开（证据链）

| 环节 | 位置 | 结论 |
|---|---|---|
| 按钮渲染 | `web/src/features/chat/ChatPage.vue:394-406` | `v-if="voiceEnabled"`，绑 `pointerdown/up` |
| 开关条件 | `ChatPage.vue:35` | `store.capabilities.voice && canRecordVoice()` |
| 能力位来源 | `web/src/stores/chat.ts:158` | 连接后取 `client.capabilities` |
| 自建后端 | `web/src/im/self/client.ts:36` | `{ image: true, search: true, voice: true }` |
| 腾讯后端 | `web/src/im/client.ts:298` | `voice: false`（该分支已不被走到） |
| 浏览器能力 | `web/src/im/self/voice.ts:27-34` | HTTPS 下 `canRecordVoice()` 为真 |

2026-10-27 已全量切 `IM_SELF_GRAYLIST=all`，所有账号走自建后端 → `capabilities.voice = true`；生产域名是 HTTPS → `canRecordVoice()` 为真。**按钮在线上是可见的。**

代码本身在 2026-10-27 随「已上线交付线」合入 master（`3cdc28c`），并带测试 `web/tests/unit/im-voice.spec.ts`、`web/tests/component/message-voice.spec.ts`。

### 2.2 四个缺陷

| # | 缺陷 | 位置 | 后果 |
|---|---|---|---|
| D1 | 指针拖出按钮后松手，`pointerup` 丢失 | `ChatPage.vue:394-406` 未做 `setPointerCapture` | 录音停不下来，直到 60 秒上限自动把一段 60 秒语音发出去 |
| D2 | 权限被拒 / 无麦克风时静默返回 | `ChatPage.vue:66-70` `catch { return }` | 用户点了按钮什么都没发生，不知道是自己拒了权限 |
| D3 | 能力不支持时按钮直接消失 | `ChatPage.vue:395` `v-if="voiceEnabled"` | 用户以为产品没有语音功能，无任何解释 |
| D4 | 离开聊天页会**发送**正在录的语音 | `ChatPage.vue:249` `onUnmounted` 调 `finishRecording()` | 切走页面把没录完的话发给对方 |

App 侧同类问题（较小）：`app/lib/features/chat/chat_page.dart:573-578` 的 `dispose()` 只取消计时器，**不停止录音**，页面弹出后麦克风仍在采集、临时文件泄漏。

### 2.3 两端现状差异

| 维度 | App | Web |
|---|---|---|
| 手势 | 按住说话 + 上滑 60px 取消 | 按住说话（鼠标场景别扭） |
| 录音反馈 | `VoiceRecordOverlay` 浮层（秒数 + 取消态） | 输入栏上方一条提示 |
| 权限被拒 | `AppToast`「需要麦克风权限才能发语音」 | 静默 |
| 启动失败 | `AppToast`「录音启动失败，请重试」 | 静默 |
| 太短（<1s） | `AppToast`「说话时间太短」 | 静默丢弃 |
| 发送失败 | `isFailed` 气泡 + 重试（`chat_controller.dart:75-84`） | `catch(() => {})` 静默丢弃 |
| 60 秒 | 自动停并发送 | 自动停并发送 |

结论：**App 的行为是对的，Web 缺了几乎所有的错误路径**；而两端都把录音逻辑埋在 UI 组件里（App `_InputBarState` 约 200 行），所以每次都只能打补丁。

## 3. 目标与非目标

### 3.1 目标

1. 两端共用一份**显式录音状态机契约**（状态、事件、非法转移、文案键一一对应）。
2. Web 录音交互改为**点击式**（PC 手势适配），并补全所有错误路径。
3. App 保留按住说话（触屏手势适配），但把录音逻辑从 `_InputBarState` 抽成可单测的 controller。
4. 修掉 D1–D4 与 App 的 dispose 泄漏。
5. 语音发送失败在 Web 上也能**留气泡可重试**（对齐 App 的 `isFailed`）。

### 3.2 非目标

- 不改后端（`POST /im/voices`、`imserver` 的 `kind=4` 均不动）。
- 不做语音转文字、播放进度条、波形可视化。
- 不动图片消息的发送路径（图片失败重试同样有缺陷：`pendingFiles` 只在成功后写入，失败占位没有缓存。**记入待办，不在本期**）。
- 不引入新的 UI 库或动画库。

## 4. 录音状态机契约

跨语言（TS / Dart）不共享代码，共享**契约**：状态名、事件名、转移表、文案逐条对应，两端测试用例名对齐。

### 4.1 状态（4 个）

| 状态 | 含义 | 允许的输入 |
|---|---|---|
| `idle` | 未录音 | 可发文本/图片/表情 |
| `requesting` | 正在申请麦克风权限（异步） | 全部禁用 |
| `recording` | 录音中，计时器在跑 | 只能"发送"或"取消" |
| `sending` | 已停止录音，正在上传 + 发送 | 只能等待 |

### 4.2 事件与转移

事件：`start` / `stopAndSend` / `cancel` / `tick` / `timeout`

```
idle       --start-------> requesting
requesting --granted-----> recording
requesting --denied------> idle            （提示 VOICE_PERMISSION_DENIED）
recording  --cancel------> idle            （丢弃，不发送）
recording  --stopAndSend-> sending
recording  --timeout-----> sending         （60 秒到，自动发送）
sending    --ok----------> idle            （消息上屏）
sending    --error-------> idle            （失败态：Web 留可重试气泡 / App 置 isFailed）
sending    --stopAndSend-> sending         （忽略，幂等，防连点）
```

### 4.3 硬约束

1. **时长 < 1000ms** → `tooShort`，不发送，提示 `VOICE_TOO_SHORT`。
2. **60 秒硬上限**，到点自动 `stopAndSend`（沿用两端现状）。
3. `recording` / `sending` 期间禁用文本、表情、图片入口。
4. **页面卸载 / 路由离开一律 `cancel`，绝不发送**（修 D4）。
5. 权限被拒后不自动重试，用户再点一次才重新申请（浏览器通常记住拒绝，需用户手动改站点设置）。

### 4.4 文案表（两端逐字一致）

| 键 | 文案 | 触发 |
|---|---|---|
| `VOICE_PERMISSION_DENIED` | 需要麦克风权限才能发语音 | `requesting --denied-->` |
| `VOICE_NO_DEVICE` | 未检测到麦克风 | `NotFoundError` |
| `VOICE_UNSUPPORTED` | 当前浏览器不支持录音（需 HTTPS） | 点击置灰的麦克风 |
| `VOICE_START_FAILED` | 录音启动失败，请重试 | `recorder.start()` 抛错 |
| `VOICE_TOO_SHORT` | 说话时间太短 | 时长 < 1s |
| `VOICE_SEND_FAILED` | 语音发送失败，点击重试 | `sending --error-->` |

**操作提示按手势各自表述**（不强行统一）：

- Web：录音条里 `取消` / `发送` 两个按钮，无需额外文案；按 `Esc` 也可取消。
- App：浮层文案「松开发送，上滑取消」/「松开取消」（现状保留）。

## 5. Web 设计

### 5.1 新增 `useVoiceRecorder` composable

文件：`web/src/features/chat/useVoiceRecorder.ts`

把现在散在 `ChatPage.vue` 里的 MediaRecorder 生命周期收进一个组合函数，对外只暴露状态与三个动作：

```ts
export type VoicePhase = 'idle' | 'requesting' | 'recording' | 'sending'

export interface VoiceRecorderOptions {
  /** 当前是否允许录音（能力位 + 浏览器支持） */
  enabled: () => boolean
  /** 录完一段：由调用方决定怎么发（失败要能回传失败态） */
  onSend: (blob: Blob, durationMs: number) => Promise<void>
  /** 需要给用户的提示（权限被拒 / 太短 / 启动失败 / 不支持） */
  onNotice: (text: string) => void
}

export function useVoiceRecorder(options: VoiceRecorderOptions): {
  phase: Ref<VoicePhase>
  seconds: Ref<number>
  start: () => Promise<void>
  stopAndSend: () => Promise<void>
  cancel: () => Promise<void>
  dispose: () => void          // 卸载时调用：内部走 cancel，绝不发送
}
```

内部要点：

- `start()`：`phase='requesting'` → `getUserMedia({ audio: true })` → 失败按 `error.name` 映射文案（`NotAllowedError`→权限、`NotFoundError`→无设备、其余→启动失败）→ 成功则 `MediaRecorder.start()`、起 200ms 计时器、设 60 秒超时。
- `stopAndSend()`：`phase='sending'`；`duration < 1000` → 走 `VOICE_TOO_SHORT` 回 `idle`；否则拼 Blob（`type` 去掉 `;codecs=opus`，服务端按主类型匹配）→ `onSend` → 成功/失败都回 `idle`（失败态由 `onSend` 的调用方落气泡）。
- `cancel()`：停 track、丢弃 chunks、清计时器、`phase='idle'`。
- `dispose()`：等价 `cancel()`（修 D4）。
- 幂等：`phase !== 'idle'` 时忽略 `start`；`phase !== 'recording'` 时忽略 `stopAndSend`。
- **不再使用指针按下/抬起**，因此 D1 自然消失；取消快捷键 `Esc` 由 `ChatPage` 在 `document` 级 `keydown` 监听，转调 `cancel()`。

### 5.2 新增 `VoiceRecordBar` 组件

文件：`web/src/features/chat/VoiceRecordBar.vue`

录音中替换整个输入栏的三段式：

```
[ 取消 ]   ● 00:05   [ 发送 ]
```

- 左：`取消` 按钮（次要色，`aria-label="取消录音"`）。
- 中：脉冲圆点（`prefers-reduced-motion` 下不闪）+ 等宽数字计时（`font-variant-numeric: tabular-nums`，避免宽度跳动）。
- 右：`发送` 按钮（主色）。
- `sending` 态：发送按钮转 loading、取消禁用、计时冻结。
- 全部走 token：`--color-brand` / `--space-*` / `--radius-*` / `--text-*`，不写裸值。

### 5.3 `ChatPage.vue` 接线

- 删掉 `recording / cancelArmed / recordSeconds / mediaRecorder / mediaStream / chunks / recordStartedAt / recordStartY / recordTimer` 与 `startRecording / onVoiceMove / finishRecording`（约 60 行）。
- `const voice = useVoiceRecorder({ enabled: () => voiceEnabled.value, onSend, onNotice })`。
- 模板：

```vue
<footer class="chat__composer">
  <VoiceRecordBar v-if="voice.phase.value !== 'idle'"
    :phase="voice.phase.value" :seconds="voice.seconds.value"
    @cancel="voice.cancel()" @send="voice.stopAndSend()" />
  <template v-else>
    …现有输入栏（麦克风 / 图片 / 表情 / 输入框 / 发送）…
  </template>
</footer>
```

- 麦克风按钮：**始终渲染**（修 D3）。`enabled` 为真 → 点击 `start()`；为假 → 置灰 + `@click="toast(VOICE_UNSUPPORTED)"`。
- 挂 `Escape` 监听：`recording` 时取消。
- `onUnmounted` 调 `voice.dispose()`（修 D4）。

### 5.4 store：语音乐观发送与重试

文件：`web/src/stores/chat.ts`

现状是"发成功才 append"，失败后没有消息可重试。改为**乐观插入 + 失败标记**（与 `ChatPage.vue:294-331` 的图片路径同思路，但收敛进 store，页面不再自己拼占位消息）：

```ts
async function sendVoice(peerId: string, blob: Blob, durationMs: number): Promise<ChatMessage> {
  await ensureConnected()
  const placeholder: ChatMessage = {
    msgId: `local-${Date.now()}`, peerId, isSelf: true, seq: 0,
    timestamp: Date.now(), kind: ChatMessageKind.voice, text: '',
    senderName: '', senderAvatar: null,
    isPending: true, isFailed: false,
    imageUrl: null, imageLargeUrl: null,
    voiceUrl: null, voiceDurationMs: durationMs, isRevoked: false,
  }
  appendMessage(peerId, placeholder)
  pendingVoices.set(placeholder.msgId, { blob, durationMs })
  try {
    const sent = await client.sendVoice(peerId, blob, durationMs)
    replaceMessage(placeholder.msgId, sent)          // 就地替换，不 concat
    pendingVoices.delete(placeholder.msgId)
    pendingVoices.set(sent.msgId, { blob, durationMs })
    upsertConversation({ ...sent, isSelf: true })
    return sent
  } catch (error) {
    replaceMessage(placeholder.msgId, { ...placeholder, isPending: false, isFailed: true })
    throw error
  }
}
```

- 新增内部工具 `replaceMessage(msgId, next)`（现有代码是页面里手写 filter，收敛进 store）。
- `resend(message)` 的语音分支改为：`pendingVoices` 取 blob → 先移除旧消息 → 走 `sendVoice` 重新乐观插入。占位消息与真实消息共用同一套逻辑。
- `MessageVoice.vue`：`voiceUrl` 为空时渲染**不可播放**的占位（灰色麦克风 + 时长），不再把空串丢给 `Audio`。

### 5.5 新增 `AppToast` 组件

文件：`web/src/components/AppToast.vue`

Web 目前只有 `ChatPage` 里一段内联 `.chat__toast`（"已复制"）。本期需要多处提示，抽成组件：

```ts
defineProps<{ text: string }>()   // 空串不渲染；非空 1.5s 后由调用方清空
```

- 底部居中、深色底、白字、圆角走 token。
- 配合 `useToast()`（`web/src/composables/useToast.ts`）返回 `{ text, show(msg) }`。
- `ChatPage` 现有的"已复制"改用它，避免两套提示。

### 5.6 降级

| 场景 | 表现 |
|---|---|
| 腾讯后端（`capabilities.voice = false`） | 麦克风置灰，点击提示 `VOICE_UNSUPPORTED` |
| HTTP 访问 / 老浏览器（`canRecordVoice()` 为假） | 同上 |
| 权限被拒 | toast `VOICE_PERMISSION_DENIED`，按钮保持可用（用户可改站点设置后再点） |

## 6. App 设计

### 6.1 新增 `VoiceRecordController`

文件：`app/lib/features/chat/voice_record_controller.dart`

`ChangeNotifier`，把 `_InputBarState` 里的录音逻辑整体搬出来：

```dart
enum VoicePhase { idle, requesting, recording, sending }

class VoiceRecordController extends ChangeNotifier {
  VoiceRecordController({
    required VoiceRecorder recorder,
    required Future<String> Function() tempPath,
    required void Function(String message) onNotice,
    required Future<void> Function(String path, int durationMs) onSend,
  });

  VoicePhase get phase;
  int get seconds;
  bool get cancelArmed;

  Future<void> start();              // requesting -> recording
  Future<void> stopAndSend();        // recording -> sending -> idle
  Future<void> cancel();             // 丢弃
  void updateCancelArm(bool armed);  // 上滑取消态
  @override void dispose();          // 录音中则 recorder.cancel()（修泄漏）
}
```

- 依赖 `VoiceRecorder` 抽象（已存在：`app/lib/im/voice_recorder.dart`），测试可注入假实现（`test/support/fake_voice.dart` 已有先例）。
- 60 秒 `Timer` 在 controller 内，触发 `stopAndSend()`。
- 提示统一走 `onNotice`，由页面转成 `AppToast`。

### 6.2 `_InputBar` 改造

- 删除 `_recording / _cancelArmed / _stopwatch / _ticker / _autoStop` 与 `_startRecording / _finishRecording`。
- `initState` 里构造 controller，`ListenableBuilder` 订阅渲染；手势仍是 `onLongPressStart / onLongPressMoveUpdate / onLongPressEnd`（触屏语义不变）。
- `VoiceRecordOverlay` 保持不变，数据从 controller 取。
- `dispose` 里 `controller.dispose()`（内部停录音）。

### 6.3 文案对齐

`_startRecording` 里的三条 `AppToast` 文案替换为 §4.4 的常量（值不变，收敛到 `voice_record_controller.dart` 顶部的 `const`）。

## 7. 失败与重试

| 阶段 | 两端行为 |
|---|---|
| 权限被拒 | toast，按钮保持可用 |
| 无设备 | toast `VOICE_NO_DEVICE` |
| 启动失败 | toast `VOICE_START_FAILED` |
| 太短（<1s） | toast `VOICE_TOO_SHORT`，不发送 |
| 发送失败 | **留气泡**：`isFailed = true`，气泡内「重发」；点击用缓存的 blob 重发 |

App 侧发送失败已经由 `_sendOut` 的 catch 落地（`chat_controller.dart:81-83`），无需改动；本期只是把 Web 补齐到同一水平。

## 8. 测试计划

### 8.1 Web

| 文件 | 用例 |
|---|---|
| `tests/unit/voice-recorder.spec.ts`（新） | 状态机全转移；<1s 不发送；60s 自动发送；`dispose` 不发送；权限被拒映射文案 |
| `tests/component/voice-record-bar.spec.ts`（新） | 三段式渲染；点取消/发送 emit；`sending` 态禁用 |
| `tests/component/chat-page.spec.ts`（改） | 能力不支持时按钮**存在且置灰**（D3）；点击给提示；点麦克风进入录音态；Esc 取消 |
| `tests/unit/chat-store.spec.ts`（改） | `sendVoice` 乐观插入；失败标 `isFailed` 并抛错；`resend` 复用缓存 blob |

### 8.2 App

| 文件 | 用例 |
|---|---|
| `test/features/chat/voice_record_controller_test.dart`（新） | 状态机全转移；<1s；60s 自动；`dispose` 时 `cancel` 被调用 |
| `test/features/chat/chat_page_test.dart`（改） | 麦克风长按进入录音、浮层出现；权限被拒 toast 文案 |

### 8.3 门槛

- Web：`npm run type-check` 零错误、`npm run lint --max-warnings 0` 零告警、`npm run test:run` 全绿（覆盖率 70/60/70/70）。
- App：`flutter analyze` 零告警、`flutter test` 全绿。

## 9. 兼容与降级

- 不影响已上线的语音消息收发与播放（只动录制端与失败态）。
- 腾讯后端分支保持"入口置灰"而不是"消失"，行为等价于原来隐藏，但可解释。
- 移动端浏览器按 UA 进引导页，不进聊天页，所以点击式录音不需要兼容触屏长按。

## 10. 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| App 抽 controller 动了聊天页结构 | 现有 405 个测试可能红 | 先抽后改，每步 `flutter test` 全绿再继续 |
| `MediaRecorder` 在 Safari 上 MIME 不同 | 上传被服务端拒 | 已有 `pickMimeType()` 兜底；服务端按主类型匹配 |
| 乐观插入与真实消息重复 | 气泡出现两条 | 用 `replaceMessage` 就地替换；测试覆盖 |
| 失败占位没有 `voiceUrl` | 播放器报错 | `MessageVoice` 空 URL 渲染不可播放占位 |

## 11. 上线清单

1. Web `npm run build`，部署 `dist` 到 `/www/wwwroot/chatapp-web/`。
2. App 出签名包（版本三件套同改：`pubspec.yaml` + `app_info.dart` + 关于页测试）。
3. 手测：Web 录音 → 发送 → App 播放；App 录音 → 发送 → Web 播放；拒权限、离开页面、断网重发各一次。
4. 更新 `CLAUDE.md`「下一步」第 3 条（删除过时描述，改为已交付说明）。
