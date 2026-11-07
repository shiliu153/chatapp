#!/usr/bin/env node
/**
 * proxy.mjs 的自测。纯本地:假上游 + 真代理进程,不联网、不碰真网关。
 *
 * 跑法:node --test scripts/superagent-failover/selftest.mjs
 *
 * 覆盖的是「什么时候该换线路、什么时候不该换」这组判断,以及流的透传与冷却/恢复。
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';

const PROXY = fileURLToPath(new URL('./proxy.mjs', import.meta.url));
const CHAIN = 'cn:m,global:m,global:m-sg';

/**
 * 起一个假上游:记录每次请求的 model 与 body,响应交给 handler。
 * @param {(ctx: {model: string|null, parsed: any, req: http.IncomingMessage, res: http.ServerResponse, hits: any[]}) => void|Promise<void>} handler 响应脚本
 * @returns {Promise<{url: string, hits: any[], close: () => Promise<void>}>} 假上游句柄
 */
async function startUpstream(handler) {
  const hits = [];
  const server = http.createServer(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const body = Buffer.concat(chunks).toString('utf8');
    let parsed = null;
    try {
      parsed = JSON.parse(body);
    } catch {
      parsed = null;
    }
    const model = parsed?.model ?? null;
    hits.push({ model, parsed, auth: req.headers.authorization, path: req.url });
    await handler({ model, parsed, req, res, hits });
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address();
  return {
    url: `http://127.0.0.1:${port}`,
    hits,
    close: () => new Promise((resolve) => server.close(resolve)),
  };
}

/**
 * 起一个代理进程,等它打印监听地址后返回。
 * @param {Record<string, string>} env 覆盖的环境变量
 * @returns {Promise<{base: string, logs: () => string, stop: () => void}>} 代理句柄
 */
async function startProxy(env) {
  const child = spawn(process.execPath, [PROXY], {
    env: {
      ...process.env,
      FAILOVER_LISTEN: '127.0.0.1:0',
      FAILOVER_MODELS: CHAIN,
      FAILOVER_QUIET: '1',
      ...env,
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let buffered = '';
  const base = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`代理启动超时:${buffered}`)), 15000);
    const onData = (chunk) => {
      buffered += chunk.toString();
      const match = buffered.match(/listening on ([\d.]+):(\d+)/);
      if (match) {
        clearTimeout(timer);
        resolve(`http://${match[1]}:${match[2]}`);
      }
    };
    child.stdout.on('data', onData);
    child.stderr.on('data', (chunk) => { buffered += chunk.toString(); });
    child.on('exit', (code) => {
      clearTimeout(timer);
      reject(new Error(`代理进程退出(${code}):${buffered}`));
    });
  });
  return {
    base,
    logs: () => buffered,
    stop: () => child.kill('SIGTERM'),
  };
}

/**
 * 向代理发一次 chat/completions 请求。
 * @param {string} base 代理根地址
 * @param {any} payload 请求体
 * @returns {Promise<{status: number, text: string, headers: Headers}>} 响应
 */
async function chat(base, payload) {
  const res = await fetch(`${base}/v1/chat/completions`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', authorization: 'Bearer test-key' },
    body: JSON.stringify(payload),
  });
  return { status: res.status, text: await res.text(), headers: res.headers };
}

/**
 * 组装一次完整用例的现场:假上游 + 代理,用完自动清理。
 * @param {any} t node:test 上下文
 * @param {(ctx: any) => void|Promise<void>} handler 假上游脚本
 * @param {Record<string, string>} [env] 代理环境变量覆盖
 * @returns {Promise<{base: string, upstream: any}>} 现场句柄
 */
async function setup(t, handler, env = {}) {
  const upstream = await startUpstream(handler);
  const proxy = await startProxy({ FAILOVER_UPSTREAM: upstream.url, ...env });
  t.after(async () => {
    proxy.stop();
    await upstream.close();
  });
  return { base: proxy.base, upstream, logs: proxy.logs };
}

/** 一个成功的 chat 响应体。 */
function answer(model) {
  return {
    id: 'cmpl-test',
    object: 'chat.completion',
    model: String(model).replace(/^[a-z]+:/, ''),
    choices: [{ index: 0, message: { role: 'assistant', content: 'ok' }, finish_reason: 'stop' }],
  };
}

test('正常:走链上第一条,请求体里除 model 外一个字节都不动', async (t) => {
  const { base, upstream } = await setup(t, ({ model, res }) => {
    const payload = Buffer.from(JSON.stringify(answer(model)));
    res.writeHead(200, { 'content-type': 'application/json', 'content-length': String(payload.length) });
    res.end(payload);
  });

  const result = await chat(base, {
    model: 'cn:m',
    messages: [{ role: 'user', content: '你好' }],
    temperature: 0.3,
    stream: false,
    tools: [{ type: 'function', function: { name: 'x' } }],
  });

  assert.equal(result.status, 200);
  assert.equal(upstream.hits.length, 1);
  assert.equal(upstream.hits[0].model, 'cn:m');
  assert.equal(upstream.hits[0].auth, 'Bearer test-key', '鉴权头必须原样透传');
  assert.deepEqual(upstream.hits[0].parsed.tools, [{ type: 'function', function: { name: 'x' } }]);
  assert.equal(upstream.hits[0].parsed.temperature, 0.3);
});

test('model_unavailable:换下一条,并保住请求体其它字段', async (t) => {
  const { base, upstream } = await setup(t, ({ model, res }) => {
    if (model === 'cn:m') {
      const payload = Buffer.from(JSON.stringify({ error: { code: 'model_unavailable', message: 'no such model' } }));
      res.writeHead(400, { 'content-type': 'application/json', 'content-length': String(payload.length) });
      res.end(payload);
      return;
    }
    const payload = Buffer.from(JSON.stringify(answer(model)));
    res.writeHead(200, { 'content-type': 'application/json', 'content-length': String(payload.length) });
    res.end(payload);
  });

  const result = await chat(base, { model: 'cn:m', messages: [{ role: 'user', content: 'hi' }], max_tokens: 7 });

  assert.equal(result.status, 200);
  assert.deepEqual(upstream.hits.map((hit) => hit.model), ['cn:m', 'global:m']);
  assert.equal(upstream.hits[1].parsed.max_tokens, 7, '改写 model 不能把别的字段弄丢');
  assert.deepEqual(upstream.hits[1].parsed.messages, [{ role: 'user', content: 'hi' }]);
});

test('连续 5xx:一路退到第三条', async (t) => {
  const { base, upstream } = await setup(t, ({ model, res }) => {
    if (model === 'global:m-sg') {
      const payload = Buffer.from(JSON.stringify(answer(model)));
      res.writeHead(200, { 'content-type': 'application/json', 'content-length': String(payload.length) });
      res.end(payload);
      return;
    }
    res.writeHead(503, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ error: { code: 'no_healthy_account', message: '池里没有健康账号' } }));
  });

  const result = await chat(base, { model: 'cn:m', messages: [] });

  assert.equal(result.status, 200);
  assert.deepEqual(upstream.hits.map((hit) => hit.model), ['cn:m', 'global:m', 'global:m-sg']);
});

test('401 鉴权错:不换线路,原样返回并只打一次', async (t) => {
  const { base, upstream } = await setup(t, ({ res }) => {
    res.writeHead(401, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ error: { code: 'invalid_api_key', message: 'bad key' } }));
  });

  const result = await chat(base, { model: 'cn:m', messages: [] });

  assert.equal(result.status, 401);
  assert.match(result.text, /invalid_api_key/);
  assert.equal(upstream.hits.length, 1, '鉴权失败换模型没有意义');
});

test('400 参数错:不换线路', async (t) => {
  const { base, upstream } = await setup(t, ({ res }) => {
    res.writeHead(400, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ error: { code: 'invalid_request_error', message: 'messages 不能为空' } }));
  });

  const result = await chat(base, { model: 'cn:m' });

  assert.equal(result.status, 400);
  assert.equal(upstream.hits.length, 1);
});

test('链外模型:不替换,原样单发', async (t) => {
  const { base, upstream } = await setup(t, ({ model, res }) => {
    const payload = Buffer.from(JSON.stringify(answer(model)));
    res.writeHead(200, { 'content-type': 'application/json', 'content-length': String(payload.length) });
    res.end(payload);
  });

  const result = await chat(base, { model: 'cn:glm-5.3', messages: [] });

  assert.equal(result.status, 200);
  assert.deepEqual(upstream.hits.map((hit) => hit.model), ['cn:glm-5.3']);
});

test('SSE 首帧就是 error:换线路,客户端只看到后面的成功流', async (t) => {
  const { base, upstream } = await setup(t, ({ model, res }) => {
    res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' });
    if (model === 'cn:m') {
      res.end('data: {"error":{"code":"model_unavailable"}}\n\n');
      return;
    }
    res.write('data: {"choices":[{"delta":{"content":"你"}}]}\n\n');
    res.write('data: {"choices":[{"delta":{"content":"好"}}]}\n\n');
    res.end('data: [DONE]\n\n');
  });

  const result = await chat(base, { model: 'cn:m', messages: [], stream: true });

  assert.equal(result.status, 200);
  assert.match(result.text, /你/);
  assert.match(result.text, /好/);
  assert.match(result.text, /\[DONE\]/);
  assert.ok(!result.text.includes('model_unavailable'), '失败线路的内容不能漏给客户端');
  assert.deepEqual(upstream.hits.map((hit) => hit.model), ['cn:m', 'global:m']);
});

test('SSE 正常:整条流按顺序透传', async (t) => {
  const { base, upstream } = await setup(t, ({ res }) => {
    res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' });
    res.write('data: {"choices":[{"delta":{"content":"A"}}]}\n\n');
    res.write('data: {"choices":[{"delta":{"content":"B"}}]}\n\n');
    res.end('data: [DONE]\n\n');
  });

  const result = await chat(base, { model: 'cn:m', messages: [], stream: true });

  assert.equal(result.status, 200);
  assert.equal(upstream.hits.length, 1);
  assert.match(result.text, /"A"/);
  assert.match(result.text, /"B"/);
  assert.match(result.text, /\[DONE\]/);
});

test('冷却:失败过的线路在冷却期内不再被打', async (t) => {
  const { base, upstream } = await setup(t, ({ model, res }) => {
    if (model === 'cn:m') {
      res.writeHead(503, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ error: { code: 'no_healthy_account' } }));
      return;
    }
    const payload = Buffer.from(JSON.stringify(answer(model)));
    res.writeHead(200, { 'content-type': 'application/json', 'content-length': String(payload.length) });
    res.end(payload);
  }, { FAILOVER_COOLDOWN_MS: '5000' });

  await chat(base, { model: 'cn:m', messages: [] });
  await chat(base, { model: 'cn:m', messages: [] });

  assert.deepEqual(
    upstream.hits.map((hit) => hit.model),
    ['cn:m', 'global:m', 'global:m'],
    '第二次请求应直接跳过冷却中的 cn',
  );
});

test('恢复:冷却一过就重新试第一条,不需要人工干预', async (t) => {
  const { base, upstream } = await setup(t, ({ model, res }) => {
    if (model === 'cn:m') {
      const payload = Buffer.from(JSON.stringify(answer(model)));
      res.writeHead(200, { 'content-type': 'application/json', 'content-length': String(payload.length) });
      res.end(payload);
      return;
    }
    res.writeHead(503, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ error: { code: 'no_healthy_account' } }));
  }, { FAILOVER_COOLDOWN_MS: '200' });

  const first = await chat(base, { model: 'cn:m', messages: [] });
  assert.equal(first.status, 200);
  await delay(300);
  const second = await chat(base, { model: 'cn:m', messages: [] });
  assert.equal(second.status, 200);

  assert.deepEqual(upstream.hits.map((hit) => hit.model), ['cn:m', 'cn:m']);
});

test('三条全挂:把最后一个错误交给客户端', async (t) => {
  const { base, upstream } = await setup(t, ({ res }) => {
    res.writeHead(503, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ error: { code: 'no_healthy_account', message: '池里没有健康账号' } }));
  });

  const result = await chat(base, { model: 'cn:m', messages: [] });

  assert.equal(result.status, 503);
  assert.match(result.text, /no_healthy_account/);
  assert.equal(upstream.hits.length, 3);
});

test('状态端点:报得出每条线路的成败与冷却', async (t) => {
  const { base } = await setup(t, ({ model, res }) => {
    if (model === 'cn:m') {
      res.writeHead(400, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ error: { code: 'model_unavailable' } }));
      return;
    }
    const payload = Buffer.from(JSON.stringify(answer(model)));
    res.writeHead(200, { 'content-type': 'application/json', 'content-length': String(payload.length) });
    res.end(payload);
  }, { FAILOVER_COOLDOWN_MS: '5000' });

  await chat(base, { model: 'cn:m', messages: [] });
  const health = await fetch(`${base}/__failover/health`);
  assert.equal(await health.text(), 'ok');

  const status = await (await fetch(`${base}/__failover/status`)).json();
  assert.deepEqual(status.chain, CHAIN.split(','));
  const cn = status.lines.find((line) => line.id === 'cn:m');
  const global = status.lines.find((line) => line.id === 'global:m');
  assert.equal(cn.failed, 1);
  assert.equal(cn.lastError, 'model_unavailable');
  assert.ok(cn.coolingDownMs > 0);
  assert.equal(global.served, 1);
  assert.equal(status.failovers, 1);
});
