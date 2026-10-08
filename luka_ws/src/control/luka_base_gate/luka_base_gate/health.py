import time
import rclpy

def navigation_ready(self):
        now=time.monotonic()
        self.nav_reason='ready'
        if self.held or now-self.feedback_at>.5:
            self.nav_reason=f'LB={self.held}, encoder_age={now-self.feedback_at:.3f}'
            return False
        if any(now-self.scan_times.get(t,0)>.5 for t in ('/scan','/scan_low_filtered')):
            self.nav_reason='scan ages: '+str({t:round(now-self.scan_times.get(t,0),3) for t in ('/scan','/scan_low_filtered')})
            return False
        try:
            tf=self.tf_buffer.lookup_transform('map','base_link',rclpy.time.Time())
            age=(self.get_clock().now().nanoseconds-tf.header.stamp.sec*10**9-tf.header.stamp.nanosec)/1e9
            self.nav_reason=f'TF age={age:.3f}'
            return -.5<age<.6
        except Exception as exc:
            self.nav_reason='TF: '+str(exc)
            return False

def follow_ready(self):
        now=time.monotonic()
        self.follow_reason='ready'
        if self.held or now-self.feedback_at>.5:
            self.follow_reason=f'LB={self.held}, encoder_age={now-self.feedback_at:.3f}'
            return False
        if any(now-self.scan_times.get(t,0)>.5 for t in ('/scan','/scan_low_filtered')):
            self.follow_reason='scan ages: '+str({t:round(now-self.scan_times.get(t,0),3) for t in ('/scan','/scan_low_filtered')})
            return False
        return True
