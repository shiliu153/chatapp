/// 从本地路径里取「文件名」部分(basename),不看当前运行平台。
///
/// **为什么不能用 `Platform.pathSeparator` 去切**:它取的是「本机」的分隔符
/// (Windows `\`、其它 `/`),而路径本身的分隔符由「产出路径的那一方」决定。
/// 典型错位:`Directory.systemTemp` / `path_provider` / `image_picker` / `record`
/// 在 Windows 上给的路径里常混着 `/`,单测为省事也用 `/` 拼临时路径 —— 这时按
/// `Platform.pathSeparator` split 根本切不动,整条路径被当成文件名发给服务端
/// (Windows 上实测 `app_image_uploadc88e529f/a.jpg`),服务端存下来的名字跟着变形。
/// 所以这里两种分隔符都切:文件名只和字符串里出现过什么有关,和进程跑在哪无关。
///
/// 参数说明:
/// - [path] 本地路径,可以是 `/a/b.jpg`、`C:\a\b.jpg` 或混用两种分隔符;
///   不含分隔符时原样返回。
///
/// 返回参数:
/// - 文件名部分;路径以分隔符结尾时跳过末尾的空段(`/a/b/` → `b`)。
///
/// 使用示例:
/// ```dart
/// localFileName(r'/tmp/app_image_upload/a.jpg'); // 'a.jpg'
/// localFileName(r'C:\Users\me\a.jpg');           // 'a.jpg'
/// ```
String localFileName(String path) {
  final parts = path.split(RegExp(r'[\\/]')).where((part) => part.isNotEmpty);
  return parts.isEmpty ? path : parts.last;
}
