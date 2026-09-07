from rest_framework import serializers


class StrictSerializer(serializers.Serializer):
    """ปฏิเสธฟิลด์ที่ไม่รู้จัก แทนที่จะ ignore เงียบ ๆ

    จำเป็นสำหรับ endpoint หน้างาน เพราะฟิลด์อย่าง user/work_center/ต้นทุน
    ระบบต้องเติมเอง ถ้า client ส่งมาแล้วเราเงียบ จะดูเหมือนรับไปแล้ว
    """

    def to_internal_value(self, data):
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {
                    field: "ฟิลด์นี้ระบบเป็นผู้เติมเอง ห้ามส่งมาจากเครื่องหน้างาน"
                    for field in sorted(unknown)
                }
            )
        return super().to_internal_value(data)
