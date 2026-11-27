"""业务路由汇总：所有模块共用一套资源路由，流水线与缺测核验路由独立注册。"""
from __future__ import annotations

from app.routers import resource, pipeline_routes, gap_check_routes

ROUTERS = [resource, pipeline_routes, gap_check_routes]