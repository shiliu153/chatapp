# docs/learning/ — 后端通读教学材料

这里是**给新手（包括未来的自己）读代码用的教学材料**,不是工程规范也不是踩坑手册:
目标是「从零读懂 `chatapp/` 的每一行后端代码」,写法是教学式的(先建概念 → 精确行号清单 →
可复制实验 → 自查题)。

> **完整清单见 [`docs/README.md`](../README.md)**(由 `scripts/docs_index.py` 扫描生成,
> 禁止手改)。下面这张表是**精选入口**(怎么用),P00–P14 逐册清单以生成物为准。

> 找「现在该做什么」看 [`docs/backlog/`](../backlog/2026-11-03-todo.md);
> 找「踩过的坑」看 [`docs/pitfalls/`](../pitfalls/README.md);
> 找「规范怎么写」看 [`docs/standards/`](../standards/README.md)。三者都不在这里。

## 1. 入口

| 文档 | 是什么 | 怎么用 |
|---|---|---|
| [backend-reading-path.md](backend-reading-path.md) | **总纲**:批次路线图 + 进度表 + 五步学习法 | 先打开它,确认下一批编号 |
| [backend-guide/README.md](backend-guide/README.md) | **逐批指导书索引**:P00–P14 十五册 | 按总纲给的编号打开对应那一册 |

## 2. 两条使用约定

1. **顺序推进,不要跳批。** P00–P03 是地基(环境与反馈回路 → 请求进门 → settings → 请求出门),
   跳过后面的批次会变成「看天书」。
2. **每批必须改一行代码。** 指导书 §4 的实验是「看懂」与「以为看懂」的分界;
   只读不跑,学完仍然写不出。

## 3. 状态

本目录**只增不改**:批次读完后在 [backend-reading-path.md](backend-reading-path.md) 里勾
checkbox、在 [backend-guide/README.md](backend-guide/README.md) 底部进度表更新一行,
**不要**新建「第二份进度表」。
