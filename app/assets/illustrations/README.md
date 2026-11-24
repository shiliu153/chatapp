# 空态插画(E-5.2 / E-5.3 / E-5.5)

[unDraw](https://undraw.co) 插画,服务发现页(E-5.2)、对话线(E-5.3)与回声 / 广场
(E-5.5)的空 / 错误态。

| 文件 | unDraw 原名 | 用在哪 |
|---|---|---|
| `discovery_empty_light/dark.png` | [No data](https://undraw.co/illustration/no-data_ig65) | 附近暂时没有新的人了 |
| `discovery_profile_incomplete_light/dark.png` | [Profile data](https://undraw.co/illustration/profile-data_xkr9) | 资料没完善 |
| `discovery_load_failed_light/dark.png` | [Connection lost](https://undraw.co/illustration/connection-lost_am29) | 加载失败 |
| `chat_empty_light/dark.png` | [Chatting](https://undraw.co/illustration/chatting_29rn) | 会话列表空(「还没有对话」) |
| `chat_error_light/dark.png` | [Connection lost](https://undraw.co/illustration/connection-lost_am29) | 会话列表 / 聊天页加载失败 |
| `square_empty_light/dark.png` | [Online posts](https://undraw.co/illustration/online-posts_avfn) | 动态流空(「还没有人留下回声」) |
| `square_error_light/dark.png` | [Connection lost](https://undraw.co/illustration/connection-lost_am29) | 广场 / 动态详情加载失败 |

## 为什么每张两份(明 / 暗)

unDraw 的默认着色是「浅色纸 + 深墨 + 紫色强调」,直接放进深色页会整张消失
(深墨 `#3f3d56` 落在 `#14110F` 上对比度约 1.6:1)。所以每张矢量图导出两套:

| 角色 | 浅色 | 深色 |
|---|---|---|
| 强调色 | `#C93C22`(`brand.default` 浅色值) | `#FF9370`(`brand.default` 深色值) |
| 墨色 | 原图 `#3f3d56` / `#2f2e41` | `#C4B9AD` / `#A39789`(`text.secondary` 深色档附近) |
| 浅灰面 | 原图 `#e6e6e6` / `#f2f2f2` / `#ccc` | `#3A332D` / `#55493F`(`border.strong` 深色档附近) |

`Chatting` 那张图比前几张多两类填充,深色版按同样思路翻转(不新增颜色):

| 角色 | 原图 | 浅色 | 深色 |
|---|---|---|---|
| 手机屏面 | `#fff` | 原样(白) | `#1E1916`(`surface.card` 深色档) |
| 描边墨 / 手机边 | `#090814` | 原样 | `#F6F1EB`(`text.primary` 深色档) |
| 人物浅粉 | `#ed9da0` | 原样 | `#6B4A3E`(暖中性,与朱砂同族) |

## 导出口径

- 源文件是 unDraw 的 SVG(主色 `#6c63ff` 是它的默认强调色),用
  [`@resvg/resvg-js`](https://www.npmjs.com/package/@resvg/resvg-js) 栅格化:
  `fitTo.width = 288`(显示尺寸 96dp 的 3× 备图),**透明背景**、RGBA PNG。
- **不引 `flutter_svg`**:插画一律 PNG,依赖锁零变动(拍板结果 + 规格 §6 第 8 条)。
- 颜色替换是「按 fill 值精确替换」,所以图上只剩上表那几种颜色,没有别的紫。

## 许可

unDraw 的插画为**免署名**授权(https://undraw.co/license),可免费用于商业或
个人项目、无需注明来源;本目录保留出处只为可追溯与重新导出。

## 重新导出

改配色或换图时:取同名 SVG → 按上表替换 fill → `resvg` 以 `width: 288` 导出
透明 PNG → 覆盖同名文件。不要在页面里做 `ColorFiltered` 着色(那样等于把配色
写进代码,而配色是设计资产的一部分)。
