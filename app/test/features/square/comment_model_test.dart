import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/square/models.dart';

import '../../support/sample_data.dart';

void main() {
  test('解析楼中楼字段', () {
    final item = PostCommentItem.fromJson(commentJson(
      id: 5,
      parentId: 3,
      replyTo: replyToJson(userId: 7, nickname: '阿哲'),
      replyCount: 2,
      replies: [
        commentJson(id: 6, text: '回复一', parentId: 3),
        commentJson(id: 7, text: '回复二', parentId: 3),
      ],
    ));
    expect(item.parentId, 3);
    expect(item.replyTo?.nickname, '阿哲');
    expect(item.replyCount, 2);
    expect(item.replies.map((e) => e.text), ['回复一', '回复二']);
  });

  test('顶级评论无 reply_to 时解析为 null', () {
    final item = PostCommentItem.fromJson(commentJson());
    expect(item.parentId, isNull);
    expect(item.replyTo, isNull);
    expect(item.replies, isEmpty);
  });
}
