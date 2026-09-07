from django.contrib import admin
from django.urls import include, path
from rest_framework.authtoken.views import obtain_auth_token
from rest_framework.routers import DefaultRouter

from apps.costing import api as costing_api
from apps.inventory.api import StockBalanceViewSet, StockTransactionViewSet
from apps.masterdata.api import (
    ItemViewSet,
    LocationViewSet,
    ScrapReasonViewSet,
    WorkCenterViewSet,
)
from apps.production.api import WorkOrderViewSet, shop_floor_report

router = DefaultRouter()
router.register("items", ItemViewSet, basename="item")
router.register("locations", LocationViewSet, basename="location")
router.register("work-centers", WorkCenterViewSet, basename="work-center")
router.register("scrap-reasons", ScrapReasonViewSet, basename="scrap-reason")
router.register("work-orders", WorkOrderViewSet, basename="work-order")
router.register("stock/balances", StockBalanceViewSet, basename="stock-balance")
router.register("stock/transactions", StockTransactionViewSet, basename="stock-transaction")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(router.urls)),
    path("api/auth/token/", obtain_auth_token, name="auth-token"),
    path("api/shop-floor/report", shop_floor_report, name="shop-floor-report"),
    path("api/reports/wo-status", costing_api.report_wo_status),
    path("api/reports/plan-vs-actual", costing_api.report_plan_vs_actual),
    path("api/reports/scrap", costing_api.report_scrap),
    path("api/reports/so-at-risk", costing_api.report_so_at_risk),
    path("api/work-orders/<str:wo_no>/cost", costing_api.work_order_cost_detail),
    path("api/stock/trace/<str:item_code>", costing_api.stock_trace),
]
