#!/usr/bin/env python3
"""Luka MCP tools for D-Robotics xiaozhi-in-rdk.

This process never creates ROS motion publishers/clients. Every robot action is
revalidated by Luka's existing localhost assistant API.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from luka_assistant_client import LukaAssistantClient


mcp = FastMCP("LukaRobot")
client = LukaAssistantClient()


def _require_original(user_text: str, required: str = "") -> str:
    user_text = str(user_text or "").strip()
    if not 1 <= len(user_text) <= 1000:
        raise ValueError("必须传入用户原话 user_text")
    if required and required not in user_text:
        raise ValueError("目标名称必须原样出现在 user_text 中")
    return user_text


@mcp.tool()
def robot_status() -> dict:
    """查询 Luka 当前任务、定位等状态；不会启动运动。"""
    return client.execute("robot_status", {}, "查询小车状态")


@mcp.tool()
def destinations() -> dict:
    """列出 Luka 当前楼层已登记且可导航的目的地。"""
    return client.execute("destinations", {}, "有哪些目的地")


@mcp.tool()
def localization_status() -> dict:
    """查询定位是否已通过地图核验；不会启动重定位。"""
    return client.execute("localization_status", {}, "查询定位状态")


@mcp.tool()
def functions_status() -> dict:
    """查询 Luka 各功能服务是否运行。"""
    return client.execute("functions_status", {}, "查询服务状态")


@mcp.tool()
def patrol_route() -> dict:
    """查询当前保存的巡航路线；不会启动巡航。"""
    return client.execute("patrol_route", {}, "查询巡航路线")


@mcp.tool()
def follow_status() -> dict:
    """查询当前人体跟随是否启用以及安全阻塞原因。"""
    return client.execute("follow_status", {}, "查询跟随状态")


@mcp.tool()
def object_where(query: str = "") -> dict:
    """查询物体记忆中的观察位置；不会让机器人移动。"""
    query = str(query or "").strip()
    source = f"{query}在哪里" if query else "东西在哪里"
    args = {"query": query} if query else {}
    return client.execute("object_where", args, source)


@mcp.tool()
def stop_robot() -> dict:
    """立即请求停止导航、巡航、找物和人体跟随。始终允许调用。"""
    return client.execute("cancel_all", {}, "停止")


@mcp.tool()
def stop_following() -> dict:
    """停止人体跟随并请求停车。始终允许调用。"""
    return client.execute("follow_stop", {}, "停止跟随")


@mcp.tool()
def navigate(name: str, user_text: str) -> dict:
    """导航到已登记目的地。user_text 必须是用户原话且包含目的地名称。"""
    name = str(name or "").strip()
    return client.execute(
        "navigate", {"name": name}, _require_original(user_text, name)
    )


@mcp.tool()
def start_patrol(user_text: str) -> dict:
    """开始已保存路线的一次巡航。user_text 必须是用户原话。"""
    return client.execute("patrol_start", {}, _require_original(user_text))


@mcp.tool()
def find_object(query: str, user_text: str) -> dict:
    """按当前产品找物流程查找物品。user_text 必须包含 query。"""
    query = str(query or "").strip()
    return client.execute(
        "find_object", {"query": query}, _require_original(user_text, query)
    )


@mcp.tool()
def bring_to_object(query: str, user_text: str) -> dict:
    """带用户到已找到的物品位置。房间/目的地应使用 navigate。"""
    query = str(query or "").strip()
    return client.execute(
        "object_bring", {"query": query}, _require_original(user_text, query)
    )


@mcp.tool()
def start_following(user_text: str) -> dict:
    """开始跟随当前已在 Luka 中选择/核验的人；不会自动改选陌生人。"""
    return client.execute("follow_start", {}, _require_original(user_text))


@mcp.tool()
def auto_relocalize(user_text: str) -> dict:
    """在停止任务后尝试自动重定位。可能产生原地定位动作，默认被 motion gate 禁用。"""
    return client.execute("localization_auto", {}, _require_original(user_text))


if __name__ == "__main__":
    mcp.run()
