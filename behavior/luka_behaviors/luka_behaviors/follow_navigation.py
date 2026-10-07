"""Lease-aware Nav2 action adapter for the unchanged official follow controller."""
import math
from rclpy.action import ActionClient, ActionServer, GoalResponse, CancelResponse
from nav2_msgs.action import NavigateToPose
from rclpy.callback_groups import ReentrantCallbackGroup


class FollowNavigationProxy:
    def __init__(self,node,lease,enabled):
        self.node=node;self.lease=lease;self.enabled=enabled;self.handle=None;self.active=False
        self.group=ReentrantCallbackGroup()
        self.client=ActionClient(node,NavigateToPose,'/navigate_to_pose',callback_group=self.group)
        self.server=ActionServer(node,NavigateToPose,'/luka/behavior/follow_navigation',
                                 execute_callback=self.execute,goal_callback=self.goal,
                                 cancel_callback=self.cancel,callback_group=self.group)
        node.create_timer(.1,self.watchdog)

    def watchdog(self):
        if self.handle and (not self.enabled() or not self.lease.valid('nav')):
            self.handle.cancel_goal_async();self.lease.release()

    def goal(self,goal):
        if self.active or not self.enabled() or not self.client.server_is_ready():return GoalResponse.REJECT
        if goal.pose.header.frame_id!='map':return GoalResponse.REJECT
        p=goal.pose.pose.position;q=goal.pose.pose.orientation
        if not all(math.isfinite(value) for value in (p.x,p.y,p.z,q.x,q.y,q.z,q.w)):return GoalResponse.REJECT
        if abs(q.x*q.x+q.y*q.y+q.z*q.z+q.w*q.w-1.)>.05:return GoalResponse.REJECT
        self.active=True;return GoalResponse.ACCEPT

    def cancel(self,goal):
        if self.handle:self.handle.cancel_goal_async()
        self.lease.release()
        return CancelResponse.ACCEPT

    async def execute(self,goal):
        result=NavigateToPose.Result()
        try:
            await self.lease.request('nav')
            if not self.enabled() or goal.is_cancel_requested:raise ValueError('follow was cancelled')
            self.handle=await self.client.send_goal_async(goal.request,
                feedback_callback=lambda event:goal.publish_feedback(event.feedback))
            if not self.handle.accepted:raise ValueError('Nav2 rejected follow goal')
            if not self.enabled() or goal.is_cancel_requested or not self.lease.valid('nav'):
                await self.handle.cancel_goal_async()
            response=await self.handle.get_result_async();result=response.result
            if goal.is_cancel_requested:goal.canceled()
            elif response.status==4 and self.enabled():goal.succeed()
            else:goal.abort()
        except Exception as error:
            self.node.get_logger().warn('Follow navigation failed: '+str(error))
            if self.handle:self.handle.cancel_goal_async()
            if goal.is_active:goal.abort()
        finally:
            self.handle=None;self.active=False
            if self.enabled():
                try:await self.lease.request('follow')
                except Exception:self.lease.release()
            else:self.lease.release()
        return result
