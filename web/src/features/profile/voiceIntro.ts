/**
 * 资料语音自我介绍的时长上限。
 *
 * 与服务端 `settings.PROFILE_VOICE_MAX_MS`(30000)一致:服务端用 ffprobe 实测时长,
 * 超 30 秒直接 400。前端先卡住,避免录满 60 秒才在上传时被打回。
 */
export const PROFILE_VOICE_MAX_SECONDS = 30

/** 毫秒口径,传给 `useVoiceRecorder` 的 `maxDurationMs`(与 App 端 maxDurationMs 同口径)。 */
export const PROFILE_VOICE_MAX_MS = PROFILE_VOICE_MAX_SECONDS * 1000
