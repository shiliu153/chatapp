#!/usr/bin/env node
/**
 * superagent 的模型兜底代理(failover proxy)。
 *
 * 背景:DSH 的 `agent-default-model` 与 `llm-pi-ai` 都只认「一个 provider + 一个模型 id」,
 * 没有内置回退链;而 wb-pool 网关下同一份 key 有 cn / global / global-sg 三条线路。
 * 这个进程挡在 DSH 与网关之间:把请求体里的 `model` 依次换成链上的下一个,直到某次
 * 真正返回 2xx 或流里的首个事件不是错误。除 `model` 与随之变化的 `content-length` 外,
 * 请求与响应字节原样转发,不解释、不改写。
 *
 * 只在「线路类」错误上切换 —— 模型不可用、池里没有健康账号、5xx、402(按模型计费/额度)、
 * 连接失败超时、SSE 首帧即 error;请求本身写错(400 invalid_request、401 鉴权)一律原样
 * 返回,免得把真实 bug 变成「换了三条线路还是同样报错」的噪声。
 *
 * 一条线路失败后进入冷却(默认 30s),期间直接跳过它;冷却结束后的下一次请求重新试它,
 * 所以 cn 线路恢复后不需要人工干预就能自动切回。
 *
 * 配置(env,全部有默认值):
 *   FAILOVER_LISTEN             监听地址,默认 127.0.0.1:8788(端口写 0 = 随机,启动时打印实际端口)
 *   FAILOVER_UPSTREAM           上游根地址,默认 https://wb.shiliu153.me
 *   FAILOVER_MODELS             回退链,逗号分隔,书写顺序即优先级
 *   FAILOVER_COOLDOWN_MS        线路失败后多久内不再尝试,默认 30000
 *   FAILOVER_HEADER_TIMEOUT_MS  等上游响应头的最长时间,默认 600000(10 分钟,长上下文首字节可能很慢)
 *   FAILOVER_MAX_BODY_BYTES     请求体超过它就完全不改写 model、原样单发,默认 64MiB
 *   FAILOVER_QUIET              非空 = 只打切换与失败日志,不打每次请求
 *
 * 观测接口:
 *   GET /__failover/health  活着 → 200 `ok`
 *   GET /__failover/status  每条线路的成败计数、冷却剩余、最近一次请求
 *
 * 自测:node --test scripts/superagent-failover/selftest.mjs(纯本地假上游,不联网)
 */

import http from 'node:http';
import https from 'node:https';
import { once } from 'node:events';

const LISTEN = process.env.FAILOVER_LISTEN || '127.0.0.1:8788';
const UPSTREAM = (process.env.FAILOVER_UPSTREAM || 'https://wb.shiliu153.me').replace(/\/+$/, '');
const CHAIN = (process.env.FAILOVER_MODELS
  || 'cn:deepseek-v4.1-flash,global:deepseek-v4.1-flash,global:deepseek-v4.1-flash-sg')
  .split(',')
  .map((item) => item.trim())
  .filter(Boolean);
const COOLDOWN_MS = Number(process.env.FAILOVER_COOLDOWN_MS || 30000);
const HEADER_TIMEOUT_MS = Number(process.env.FAILOVER_HEADER_TIMEOUT_MS || 600000);
const MAX_BODY_BYTES = Number(process.env.FAILOVER_MAX_BODY_BYTES || 64 * 1024 * 1024);
const QUIET = Boolean(process.env.FAILOVER_QUIET);

const STATUS_PATH = '/__failover/status';
const HEALTH_PATH = '/__failover/health';

/** 网关自称「这条线路现在不可用」的错误码;只有命中它们才换下一个模型。 */
const RETRYABLE_CODES = new Set([
  'model_unavailable',
  'no_healthy_account',
  'no_available_account',
  'account_unavailable',
  'upstream_unavailable',
  'upstream_error',
]);

/** 逐跳头,不能转发(转发会破坏连接语义)。 */
const HOP_BY_HOP = new Set([
  'host',
  'connection',
  'keep-alive',
  'proxy-connection',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
  'content-length',
]);

if (CHAIN.length === 0) {
  console.error('FAILOVER_MODELS 为空,无事可做');
  process.exit(2);
}

/** 每条线路的健康记账。 */
const lines = new Map(CHAIN.map((id) => [id, {
  id,
  served: 0,
  failed: 0,
  badUntil: 0,
  lastError: null,
  lastServedAt: 0,
}]));

const stats = {
  startedAt: Date.now(),
  requests: 0,
  failovers: 0,
  lastRequest: null,
};

/**
 * 打一行日志(带时间戳,进 journald)。
 * @param {string} message 日志正文
 */
function log(message) {
  console.log(`${new Date().toISOString()} ${message}`);
}

/**
 * 把一段字节解析成 JSON,失败返回 null。
 * @param {Buffer} buffer 待解析字节
 * @returns {any|null} 解析结果
 */
function parseJson(buffer) {
  if (!buffer || buffer.length === 0) return null;
  try {
    return JSON.parse(buffer.toString('utf8'));
  } catch {
    return null;
  }
}

/**
 * 从一个 OpenAI 风格的错误响应体里取错误码。
 * @param {Buffer} buffer 错误响应字节
 * @returns {string|null} 错误码
 */
function errorCode(buffer) {
  const parsed = parseJson(buffer.subarray(0, 8192));
  if (!parsed || typeof parsed !== 'object') return null;
  const code = parsed?.error?.code ?? parsed?.code;
  return typeof code === 'string' ? code : null;
}

/**
 * 判定一次失败的响应/异常是否属于「换条线路也许就行」。
 * @param {number} status 上游 HTTP 状态码;网络层失败传 0
 * @param {Buffer} body 上游错误响应体
 * @returns {{retryable: boolean, reason: string}} 判定结果
 */
function classify(status, body) {
  if (status === 0) return { retryable: true, reason: 'network' };
  if (status >= 500) return { retryable: true, reason: `http_${status}` };
  if (status === 402) return { retryable: true, reason: 'http_402' };
  const code = errorCode(body);
  if (code && RETRYABLE_CODES.has(code)) return { retryable: true, reason: code };
  return { retryable: false, reason: code ? code : `http_${status}` };
}

/**
 * 按请求里的 model 决定这次要走哪些线路。
 *
 * 请求的模型在链上 → 从它开始按链序轮转(后面的都是兜底);
 * 不在链上(例如有人把模型换成别的)→ 返回 null,表示原样单发、不做任何替换。
 * @param {string} requested 请求体里的 model
 * @returns {string[]|null} 依次尝试的模型 id
 */
function candidateOrder(requested) {
  const index = CHAIN.indexOf(requested);
  if (index < 0) return null;
  const rotated = [...CHAIN.slice(index), ...CHAIN.slice(0, index)];
  const now = Date.now();
  const ready = rotated.filter((id) => lines.get(id).badUntil <= now);
  // 全在冷却里也得发一次:宁可赌一把,也不要凭空失败。
  return ready.length > 0 ? ready : rotated;
}

/**
 * 记一次成功:清冷却、累加计数。
 * @param {string|null} id 实际服务的模型 id
 */
function recordSuccess(id) {
  if (!id) return;
  const line = lines.get(id);
  if (!line) return;
  line.served += 1;
  line.badUntil = 0;
  line.lastServedAt = Date.now();
}

/**
 * 记一次失败:进入冷却、记住原因。
 * @param {string|null} id 失败的模型 id
 * @param {string} reason 失败原因
 */
function recordFailure(id, reason) {
  if (!id) return;
  const line = lines.get(id);
  if (!line) return;
  line.failed += 1;
  line.badUntil = Date.now() + COOLDOWN_MS;
  line.lastError = reason;
}

/**
 * 读完整个请求体。
 * @param {http.IncomingMessage} req 请求
 * @returns {Promise<Buffer>} 请求体字节
 */
function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on('data', (chunk) => {
      size += chunk.length;
      chunks.push(chunk);
    });
    req.on('end', () => resolve(Buffer.concat(chunks, size)));
    req.on('error', reject);
  });
}

/**
 * 读完一个上游响应体(带上限,超了就截断,用于把错误原样返回给客户端)。
 * @param {http.IncomingMessage} res 上游响应
 * @returns {Promise<Buffer>} 响应体字节
 */
async function readAll(res) {
  const chunks = [];
  let size = 0;
  for await (const chunk of res) {
    chunks.push(chunk);
    size += chunk.length;
    if (size > MAX_BODY_BYTES) break;
  }
  return Buffer.concat(chunks, size);
}

/**
 * 组装发往上游的头:丢掉逐跳头,按实际请求体重算 content-length,
 * 并强制 `accept-encoding: identity` —— 本代理要读响应体才能发现「200 其实是错误」,
 * 让上游压缩就把这个判断能力换成了省下来的那点字节,不划算。
 * @param {http.IncomingHttpHeaders} raw 客户端原始头
 * @param {number} bodyLength 实际请求体字节数
 * @returns {Record<string, string|string[]>} 上游头
 */
function forwardHeaders(raw, bodyLength) {
  /** @type {Record<string, string|string[]>} */
  const out = {};
  for (const [key, value] of Object.entries(raw)) {
    if (value === undefined) continue;
    const lower = key.toLowerCase();
    if (HOP_BY_HOP.has(lower) || lower === 'accept-encoding') continue;
    out[key] = value;
  }
  out['accept-encoding'] = 'identity';
  out['content-length'] = String(bodyLength);
  return out;
}

/**
 * 组装回给客户端的响应头:同样丢掉逐跳头。
 * @param {http.IncomingHttpHeaders} raw 上游响应头
 * @returns {Record<string, string|string[]>} 客户端响应头
 */
function responseHeaders(raw) {
  /** @type {Record<string, string|string[]>} */
  const out = {};
  for (const [key, value] of Object.entries(raw)) {
    if (value === undefined) continue;
    if (HOP_BY_HOP.has(key.toLowerCase())) continue;
    out[key] = value;
  }
  return out;
}

/**
 * 向上游发一次请求,拿到响应头就返回(不读 body)。
 * @param {{method: string, path: string, headers: Record<string, string|string[]>, body: Buffer}} attempt 请求要素
 * @returns {Promise<http.IncomingMessage>} 上游响应流
 */
function sendUpstream(attempt) {
  const url = new URL(UPSTREAM + attempt.path);
  const lib = url.protocol === 'https:' ? https : http;
  return new Promise((resolve, reject) => {
    const req = lib.request({
      protocol: url.protocol,
      hostname: url.hostname,
      port: url.port || (url.protocol === 'https:' ? 443 : 80),
      path: url.pathname + url.search,
      method: attempt.method,
      headers: attempt.headers,
      timeout: HEADER_TIMEOUT_MS,
    }, resolve);
    req.on('timeout', () => req.destroy(new Error('upstream_timeout')));
    req.on('error', reject);
    req.end(attempt.body.length > 0 ? attempt.body : undefined);
  });
}

/**
 * 从 SSE 首帧里找「网关级错误事件」。有些网关先回 200 再在流里报错,
 * 这时客户端还没收到任何字节,还来得及换线路。
 * @param {Buffer} chunk 首个数据块
 * @returns {string|null} 错误码,没问题返回 null
 */
function sseErrorCode(chunk) {
  const text = chunk.toString('utf8');
  for (const line of text.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed.startsWith('data:')) continue;
    const payload = trimmed.slice(5).trim();
    if (!payload || payload === '[DONE]') continue;
    const parsed = parseJson(Buffer.from(payload));
    if (parsed && typeof parsed === 'object' && parsed.error) {
      const code = parsed.error?.code ?? parsed.error?.type ?? 'sse_error';
      return typeof code === 'string' ? code : 'sse_error';
    }
  }
  return null;
}

/**
 * 写一块字节并处理背压。
 * @param {http.ServerResponse} res 客户端响应
 * @param {Buffer|string} chunk 待写字节
 * @returns {Promise<void>} 可写时结束
 */
async function writeChunk(res, chunk) {
  if (!res.write(chunk)) await once(res, 'drain');
}

/**
 * 收尾:把上游流原样送到客户端。
 * @param {http.IncomingMessage} upstream 上游响应
 * @param {http.ServerResponse} res 客户端响应
 * @param {any} first 已经读到的第一块(可能为 null)
 * @param {AsyncIterator<Buffer>} iterator 继续读的迭代器
 * @returns {Promise<void>} 送完即结束
 */
async function pump(upstream, res, first, iterator) {
  if (first) await writeChunk(res, first);
  for (;;) {
    const { value, done } = await iterator.next();
    if (done) break;
    await writeChunk(res, value);
  }
  res.end();
  upstream.destroy();
}

/**
 * 处理一次「换模型重试」的完整过程。
 * @param {http.IncomingMessage} req 客户端请求
 * @param {http.ServerResponse} res 客户端响应
 * @returns {Promise<void>} 响应写完即结束
 */
async function proxy(req, res) {
  const body = await readBody(req);
  const parsed = parseJson(body);
  const requested = parsed && typeof parsed.model === 'string' ? parsed.model : null;
  const streamExpected = Boolean(parsed && parsed.stream === true);
  const plan = requested && body.length <= MAX_BODY_BYTES ? candidateOrder(requested) : null;
  const attempts = plan ?? [null];

  stats.requests += 1;
  const startedAt = Date.now();
  let lastFailure = null;

  for (let index = 0; index < attempts.length; index += 1) {
    const candidate = attempts[index];
    const isLast = index === attempts.length - 1;
    let attemptBody = body;
    if (candidate && requested && candidate !== requested) {
      attemptBody = Buffer.from(JSON.stringify({ ...parsed, model: candidate }));
    }

    let upstream;
    try {
      upstream = await sendUpstream({
        method: req.method || 'POST',
        path: req.url || '/',
        headers: forwardHeaders(req.headers, attemptBody.length),
        body: attemptBody,
      });
    } catch (err) {
      const verdict = classify(0, Buffer.alloc(0));
      recordFailure(candidate, `${verdict.reason}:${err?.message ?? 'unknown'}`);
      lastFailure = {
        status: 502,
        headers: { 'content-type': 'application/json' },
        body: Buffer.from(JSON.stringify({
          error: {
            code: 'failover_upstream_unreachable',
            message: `所有线路都连不上上游:${err?.message ?? 'unknown'}`,
            type: 'api_error',
          },
        })),
      };
      if (!isLast) {
        stats.failovers += 1;
        log(`failover ${candidate} -> ${attempts[index + 1]}(network:${err?.message ?? 'unknown'})`);
      }
      continue;
    }

    const status = upstream.statusCode || 502;
    const headers = responseHeaders(upstream.headers);
    const contentType = String(upstream.headers['content-type'] || '');

    if (status >= 200 && status < 300) {
      const iterator = upstream[Symbol.asyncIterator]();
      const firstChunk = await iterator.next();

      // 流式:首帧就报错的,当作线路失败,换下一条重来(此时客户端还什么都没收到)。
      if (streamExpected || contentType.includes('text/event-stream')) {
        if (!firstChunk.done && Buffer.isBuffer(firstChunk.value)) {
          const code = sseErrorCode(firstChunk.value);
          if (code) {
            recordFailure(candidate, `sse:${code}`);
            lastFailure = {
              status: 502,
              headers: { 'content-type': 'application/json' },
              body: Buffer.from(JSON.stringify({
                error: { code, message: `线路 ${candidate} 在流首帧即报错`, type: 'api_error' },
              })),
            };
            upstream.destroy();
            if (isLast) {
              log(`give up model=${candidate} status=${status} reason=sse:${code}`);
              break;
            }
            stats.failovers += 1;
            log(`failover ${candidate} -> ${attempts[index + 1]}(sse:${code})`);
            continue;
          }
        }
        recordSuccess(candidate);
        if (!QUIET) log(`served model=${candidate ?? requested} status=${status} attempts=${index + 1} ms=${Date.now() - startedAt}`);
        stats.lastRequest = { model: candidate, status, attempts: index + 1, at: Date.now() };
        res.writeHead(status, headers);
        await pump(upstream, res, firstChunk.done ? null : firstChunk.value, iterator);
        return;
      }

      // 非流式:整段读完再判定,避免「200 + 错误 JSON」蒙混过关。
      const chunks = firstChunk.done ? [] : [firstChunk.value];
      for (;;) {
        const next = await iterator.next();
        if (next.done) break;
        chunks.push(next.value);
      }
      const payload = Buffer.concat(chunks);
      const verdict = classify(status, payload);
      const looksLikeError = !contentType.includes('text/event-stream')
        && errorCode(payload) !== null;
      if (looksLikeError && verdict.retryable && !isLast) {
        recordFailure(candidate, verdict.reason);
        stats.failovers += 1;
        log(`failover ${candidate} -> ${attempts[index + 1]}(${verdict.reason})`);
        continue;
      }
      recordSuccess(candidate);
      if (!QUIET) log(`served model=${candidate ?? requested} status=${status} attempts=${index + 1} ms=${Date.now() - startedAt}`);
      stats.lastRequest = { model: candidate, status, attempts: index + 1, at: Date.now() };
      res.writeHead(status, headers);
      res.end(payload);
      return;
    }

    // 非 2xx:读完错误体,决定是「换线路」还是「原样返回」。
    const errorBody = await readAll(upstream);
    const verdict = classify(status, errorBody);
    lastFailure = { status, headers, body: errorBody };
    if (verdict.retryable) recordFailure(candidate, verdict.reason);
    if (verdict.retryable && !isLast) {
      stats.failovers += 1;
      log(`failover ${candidate} -> ${attempts[index + 1]}(${verdict.reason})`);
      continue;
    }
    log(`give up model=${candidate ?? requested} status=${status} reason=${verdict.reason}`);
    stats.lastRequest = { model: candidate, status, attempts: index + 1, at: Date.now() };
    res.writeHead(status, headers);
    res.end(errorBody);
    return;
  }

  // 所有线路都试过了:把最后一个错误交给客户端。
  const failure = lastFailure ?? {
    status: 502,
    headers: { 'content-type': 'application/json' },
    body: Buffer.from(JSON.stringify({ error: { code: 'failover_exhausted', message: '所有备用线路都失败', type: 'api_error' } })),
  };
  stats.lastRequest = { model: null, status: failure.status, attempts: attempts.length, at: Date.now() };
  res.writeHead(failure.status, failure.headers);
  res.end(failure.body);
}

/** 状态快照:给面板与排障看。 */
function statusPayload() {
  const now = Date.now();
  return {
    listen: LISTEN,
    upstream: UPSTREAM,
    chain: CHAIN,
    cooldownMs: COOLDOWN_MS,
    uptimeMs: now - stats.startedAt,
    requests: stats.requests,
    failovers: stats.failovers,
    lastRequest: stats.lastRequest,
    lines: [...lines.values()].map((line) => ({
      id: line.id,
      served: line.served,
      failed: line.failed,
      coolingDownMs: Math.max(0, line.badUntil - now),
      lastError: line.lastError,
      lastServedAt: line.lastServedAt,
    })),
  };
}

const server = http.createServer((req, res) => {
  const path = req.url || '/';
  if (path === HEALTH_PATH) {
    res.writeHead(200, { 'content-type': 'text/plain' });
    res.end('ok');
    return;
  }
  if (path === STATUS_PATH) {
    const payload = Buffer.from(JSON.stringify(statusPayload(), null, 2));
    res.writeHead(200, { 'content-type': 'application/json', 'content-length': String(payload.length) });
    res.end(payload);
    return;
  }
  proxy(req, res).catch((err) => {
    log(`internal error ${err?.stack ?? err}`);
    if (!res.headersSent) {
      const payload = Buffer.from(JSON.stringify({
        error: { code: 'failover_internal_error', message: String(err?.message ?? err), type: 'api_error' },
      }));
      res.writeHead(502, { 'content-type': 'application/json', 'content-length': String(payload.length) });
      res.end(payload);
    } else {
      res.end();
    }
  });
});

const [host, portText] = LISTEN.includes(':') ? LISTEN.split(':') : ['127.0.0.1', LISTEN];
server.listen(Number(portText), host, () => {
  const address = server.address();
  const actual = typeof address === 'object' && address ? `${address.address}:${address.port}` : LISTEN;
  log(`listening on ${actual} upstream=${UPSTREAM} chain=${CHAIN.join(' -> ')} cooldown=${COOLDOWN_MS}ms`);
});

/**
 * 优雅收尾:先停止接新连接,再退出。
 * @param {string} signal 信号名
 */
function shutdown(signal) {
  log(`${signal} received, shutting down`);
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 3000).unref();
}

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));
