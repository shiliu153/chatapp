import 'package:image_picker/image_picker.dart';

typedef PickImage = Future<XFile?> Function();

/// 相册选图:统一压缩参数(资料照片与聊天图片共用)。
Future<XFile?> pickImageFromGallery() => ImagePicker().pickImage(
      source: ImageSource.gallery,
      maxWidth: 1080,
      imageQuality: 85,
    );

typedef PickImages = Future<List<XFile>> Function();

/// 相册多选(发布动态用);部分平台不支持 limit,前端再做一次截断。
Future<List<XFile>> pickImagesFromGallery({int limit = 9}) =>
    ImagePicker().pickMultiImage(maxWidth: 1080, imageQuality: 85, limit: limit);
