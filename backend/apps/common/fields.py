"""ฟิลด์ตัวเลขมาตรฐาน — INVARIANT ข้อ 5 ห้าม float กับจำนวนและเงิน

ทุกฟิลด์จำนวนและเงินต้องสร้างผ่านฟังก์ชันในไฟล์นี้เท่านั้น
ถ้าเห็น DecimalField ประกาศเองใน models.py แปลว่ามีคนหลุดกฎ
"""

from decimal import Decimal

from django.db import models

QTY_DIGITS = 18
QTY_PLACES = 4
AMOUNT_DIGITS = 18
AMOUNT_PLACES = 4

# ตัวคูณแปลงหน่วยไม่ใช่ "จำนวน" จึงต้องละเอียดกว่า 4 ตำแหน่ง
# มิฉะนั้น กรัม -> ตัน (0.000001) จะปัดเป็นศูนย์
RATE_DIGITS = 28
RATE_PLACES = 12

ZERO = Decimal("0")


def QtyField(**kwargs):
    kwargs.setdefault("max_digits", QTY_DIGITS)
    kwargs.setdefault("decimal_places", QTY_PLACES)
    return models.DecimalField(**kwargs)


def AmountField(**kwargs):
    kwargs.setdefault("max_digits", AMOUNT_DIGITS)
    kwargs.setdefault("decimal_places", AMOUNT_PLACES)
    return models.DecimalField(**kwargs)


def RateField(**kwargs):
    kwargs.setdefault("max_digits", RATE_DIGITS)
    kwargs.setdefault("decimal_places", RATE_PLACES)
    return models.DecimalField(**kwargs)


def PercentField(**kwargs):
    """เปอร์เซ็นต์เก็บเป็น 0-100 ไม่ใช่ 0-1 เพื่อให้ตรงกับที่ผู้ใช้กรอก"""
    kwargs.setdefault("max_digits", 7)
    kwargs.setdefault("decimal_places", 4)
    return models.DecimalField(**kwargs)
