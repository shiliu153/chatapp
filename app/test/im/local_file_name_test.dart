import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/im/local_file_name.dart';

void main() {
  group('localFileName:两种分隔符都要取到 basename', () {
    test('POSIX 形态 `/`', () {
      expect(localFileName('/tmp/app_image_upload/a.jpg'), 'a.jpg');
    });

    test('Windows 形态 `\\`', () {
      expect(localFileName(r'C:\Users\me\AppData\Local\Temp\a.jpg'), 'a.jpg');
    });

    // 这一条是本单的原始 bug:`Platform.pathSeparator` 在 Windows 上是 `\`,
    // 路径却是 `/` 拼的,切不动 → 整条路径被当成文件名。故意两种混用来钉死。
    test('两种混用', () {
      expect(localFileName(r'C:\Users\me/AppData/Local\Temp/a.jpg'), 'a.jpg');
    });

    test('不含分隔符:原样返回', () {
      expect(localFileName('a.jpg'), 'a.jpg');
    });

    test('以分隔符结尾:跳过末尾空段', () {
      expect(localFileName('/tmp/app_image_upload/a.jpg/'), 'a.jpg');
      expect(localFileName('C:\\tmp\\a.jpg\\'), 'a.jpg');
    });

    test('空路径不炸', () {
      expect(localFileName(''), '');
    });
  });
}
