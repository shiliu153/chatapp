import 'package:image_picker/image_picker.dart';

typedef PickImage = Future<XFile?> Function();

/// 相册选图:统一压缩参数(资料照片与聊天图片共用)。
Future<XFile?> pickImageFromGallery() => ImagePicker().pickImage(
      source: ImageSource.gallery,
      maxWidth: 1080,
      imageQuality: 85,
    );
