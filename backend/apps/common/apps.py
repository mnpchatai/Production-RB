import decimal

from django.apps import AppConfig


class CommonConfig(AppConfig):
    name = "apps.common"
    label = "common"
    verbose_name = "ส่วนกลาง"

    def ready(self):
        # ความละเอียดระหว่างคำนวณต้องสูงกว่าที่เก็บลงฐานข้อมูล (18,4)
        # เพราะการคูณหารหลายชั้นของ BOM สะสมความคลาดเคลื่อนได้
        decimal.getcontext().prec = 34
