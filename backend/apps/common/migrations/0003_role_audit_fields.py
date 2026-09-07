import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """INVARIANT ข้อ 6 — roles ตกหล่น audit fields ตอนสร้างครั้งแรก

    ตารางมีข้อมูลอยู่แล้วจึงต้องให้ค่าเริ่มต้นครั้งเดียว หลังจากนี้
    created_at/updated_at ทำงานอัตโนมัติเหมือนตารางอื่น
    """

    dependencies = [
        ("common", "0002_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="role",
            name="created_at",
            field=models.DateTimeField(
                auto_now_add=True, db_index=True, default=django.utils.timezone.now
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="role",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="role",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="role",
            name="updated_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
