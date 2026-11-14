"""客户端错误上报:Web / App 的未捕获异常统一落进服务端日志与指标。

设计要点:
    1. **不落库**。前端错误量大、价值密度低,存表只会带来无谓的写放大与清理成本;
       落进单行 JSON 日志即可,由 Loki/Grafana 检索聚合(与 ``request_id`` 对齐);
    2. **允许匿名**。最有价值的信号恰恰出现在登录页与启动白屏——那时还没有令牌,
       所以这个接口必须 ``AllowAny``,靠 IP 限流 + 字段长度上限控制滥用;
    3. **永远 204**。上报是 fire-and-forget,客户端不该因为它失败而受影响;
       字段非法才回 400(说明客户端代码有 bug,值得在日志里看见)。

文件信息:
    文件名称          telemetry/__init__.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""
